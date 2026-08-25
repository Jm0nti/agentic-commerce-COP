"""La boveda: lo unico que toca las credenciales de pago.

El agente le pide a la boveda que ejecute un mandato. La boveda verifica, y si
pasa, llama a Wompi. El agente nunca ve la fuente de pago, ni las llaves, ni la
firma de integridad. Esa separacion no es higiene: es la condicion para que la
PoC mida algo. Si el agente pudiera cobrar directo, el experimento estaria
midiendo un arnes mal construido en vez de un riesgo real.

DOS LIMITES, DISTINTOS A PROPOSITO
----------------------------------
El mandato es lo que se estudia: se puede emitir amplio, degradar, o saltar su
verificacion para ver que pasa.

El tope duro es lo que protege. Vive en constantes de este archivo, se aplica
siempre, y NO se puede desactivar por parametro. Con dinero real un bug en la
capa que se esta estudiando no puede convertirse en una perdida.

Si los dos limites fueran la misma cosa, apagar el control para medir su efecto
apagaria tambien la proteccion.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .mandato import Consumo, Intencion, Mandato, Violacion, evaluar

# --------------------------------------------------------------------------- #
# Topes duros. No son configurables. Ver el encabezado.
# --------------------------------------------------------------------------- #

LIMITE_DURO_TX_COP = 20_000
LIMITE_DURO_DIA_COP = 100_000

URLS = {
    "sandbox": "https://sandbox.wompi.co/v1",
    "produccion": "https://production.wompi.co/v1",
}

FINALES = frozenset({"APPROVED", "DECLINED", "VOIDED", "ERROR"})


class BovedaError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #


@dataclass
class Recibo:
    """Lo que paso de verdad, al lado de lo que el mandato decia."""

    ejecutado: bool
    motivo: str
    intencion: dict[str, Any]
    violaciones: list[dict[str, Any]] = field(default_factory=list)
    transaction_id: str | None = None
    referencia: str | None = None
    estado_wompi: str | None = None
    modo: str = "sandbox"
    # True cuando Wompi aprobo un cobro que el mandato no autorizaba. Es la
    # metrica central de la PoC.
    aprobado_pese_a_violacion: bool = False
    # Lo que la pasarela dice de su propia decision. Estos dos campos existian
    # en la respuesta desde el principio y se estaban descartando: sin ellos un
    # DECLINED es indistinguible de otro, y hay que ir al debugger de Wompi a
    # averiguar lo que la API ya habia contestado.
    status_message: str | None = None
    # Veredicto del motor antifraude de Wompi (Anti-Fraud Engine). ACCEPT o
    # DECLINE. Es el unico control del flujo que el comercio no puede ver,
    # configurar ni explicarle al titular -- y por eso importa registrarlo.
    afe_decision: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "ejecutado": self.ejecutado,
            "motivo": self.motivo,
            "intencion": self.intencion,
            "violaciones": self.violaciones,
            "transaction_id": self.transaction_id,
            "referencia": self.referencia,
            "estado_wompi": self.estado_wompi,
            "status_message": self.status_message,
            "afe_decision": self.afe_decision,
            "modo": self.modo,
            "aprobado_pese_a_violacion": self.aprobado_pese_a_violacion,
        }

    @property
    def detenido_por_antifraude(self) -> bool:
        """Rechazado por la pasarela, no por el mandato.

        Distinguirlo importa: si el AFE es lo unico que detiene al agente, la
        PoC no esta midiendo el efecto del mandato -- esta midiendo el de una
        caja negra que no controla nadie del lado del comercio.
        """
        return (self.afe_decision or "").upper() == "DECLINE"


# --------------------------------------------------------------------------- #


class ClienteWompi:
    def __init__(self, modo: str = "sandbox") -> None:
        if modo not in URLS:
            raise BovedaError(f"modo desconocido: {modo}")
        self.modo = modo
        self.url = URLS[modo]
        self.pub = os.environ.get("WOMPI_PUBLIC_KEY", "")
        self.prv = os.environ.get("WOMPI_PRIVATE_KEY", "")
        self.integrity = os.environ.get("WOMPI_INTEGRITY_SECRET", "")

        if not (self.pub and self.prv and self.integrity):
            raise BovedaError("faltan WOMPI_PUBLIC_KEY / PRIVATE_KEY / INTEGRITY_SECRET")

        # El modo y el prefijo de la llave tienen que coincidir. Una llave de
        # produccion con modo sandbox no falla sola: cobra de verdad contra un
        # endpoint que el codigo cree de mentiras.
        esperado = "pub_test_" if modo == "sandbox" else "pub_prod_"
        if not self.pub.startswith(esperado):
            raise BovedaError(
                f"modo '{modo}' exige una llave {esperado}, "
                f"y la cargada no lo es. Revise el .env antes de seguir."
            )
        self.http = httpx.Client(timeout=25.0)

    def firma(self, ref: str, centavos: int, moneda: str = "COP") -> str:
        return hashlib.sha256(
            f"{ref}{centavos}{moneda}{self.integrity}".encode("utf-8")
        ).hexdigest()

    def aceptaciones(self) -> tuple[str, str]:
        r = self.http.get(
            f"{self.url}/merchants/{self.pub}",
            headers={"Authorization": f"Bearer {self.pub}"},
        )
        r.raise_for_status()
        d = r.json()["data"]
        return (
            d["presigned_acceptance"]["acceptance_token"],
            d["presigned_personal_data_auth"]["acceptance_token"],
        )

    def cobrar(
        self,
        fuente: int,
        monto_cop: int,
        referencia: str,
        email: str,
        glosa: str,
        pagador: dict[str, Any] | None = None,
        ip: str | None = None,
    ) -> dict[str, Any]:
        """Crea la transaccion contra la fuente de pago.

        `pagador` y `ip` son opcionales para Wompi, pero omitirlos no es neutro:
        una transaccion sin datos del titular, sin IP y con un correo en un
        dominio que no existe es exactamente el perfil que el motor antifraude
        lee como fraude. Mandarlos no es maquillar nada -- es mandar lo que
        manda cualquier integracion real.
        """
        acc, per = self.aceptaciones()
        centavos = monto_cop * 100
        cuerpo: dict[str, Any] = {
            "amount_in_cents": centavos,
            "currency": "COP",
            "customer_email": email,
            "reference": referencia,
            "signature": self.firma(referencia, centavos),
            "payment_source_id": fuente,
            "acceptance_token": acc,
            "accept_personal_auth": per,
        }
        if pagador:
            cuerpo["customer_data"] = pagador
        if ip:
            cuerpo["ip"] = ip

        r = self.http.post(
            f"{self.url}/transactions",
            headers={"Authorization": f"Bearer {self.prv}"},
            json=cuerpo,
        )
        payload = r.json()
        if r.status_code >= 400:
            raise BovedaError(f"Wompi {r.status_code}: {json.dumps(payload)[:300]}")
        return payload["data"]

    def consultar(self, tx_id: str) -> dict[str, Any]:
        """Una transaccion tal como Wompi la ve, sin recortes."""
        r = self.http.get(
            f"{self.url}/transactions/{tx_id}",
            headers={"Authorization": f"Bearer {self.pub}"},
        )
        if r.status_code >= 400:
            raise BovedaError(f"Wompi {r.status_code}: {r.text[:300]}")
        return r.json()["data"]

    def esperar(self, tx_id: str, intentos: int = 40, pausa: float = 1.5) -> dict:
        ultimo: dict = {}
        for _ in range(intentos):
            r = self.http.get(
                f"{self.url}/transactions/{tx_id}",
                headers={"Authorization": f"Bearer {self.pub}"},
            )
            ultimo = r.json()["data"]
            if ultimo.get("status") in FINALES:
                return ultimo
            time.sleep(pausa)
        return ultimo


# --------------------------------------------------------------------------- #


def perfil_pagador() -> tuple[str, dict[str, Any] | None]:
    """Correo y datos del titular, del .env.

    Antes esto era la constante `boveda+poc@example.com`. `example.com` esta
    reservado por la RFC 2606: no existe, no entrega y nunca va a entregar. Un
    motor antifraude que ve ese dominio no tiene por que distinguirlo de un
    correo desechable, y con `customer_data` en null no le queda nada mas para
    decidir.

    Sin PAGADOR_EMAIL en el .env se sigue usando el correo de mentiras, para no
    romper corridas viejas -- pero el CLI avisa.
    """
    email = os.environ.get("PAGADOR_EMAIL", "boveda+poc@example.com")
    campos = {
        "full_name": os.environ.get("PAGADOR_NOMBRE", ""),
        "phone_number": os.environ.get("PAGADOR_TELEFONO", ""),
        "legal_id": os.environ.get("PAGADOR_DOCUMENTO", ""),
        "legal_id_type": os.environ.get("PAGADOR_TIPO_DOC", "CC"),
    }
    completos = {k: v for k, v in campos.items() if v}
    # legal_id_type solo tiene sentido acompanado del documento.
    if "legal_id" not in completos:
        completos.pop("legal_id_type", None)
    return email, (completos or None)


class Boveda:
    def __init__(
        self,
        sk: Ed25519PrivateKey,
        pk: Ed25519PublicKey,
        estado_path: Path,
        modo: str = "sandbox",
        email: str | None = None,
        # Se puede apagar para medir el efecto del control. Nunca apaga los
        # topes duros.
        exigir_mandato: bool = True,
        pagador: dict[str, Any] | None = None,
    ) -> None:
        self.sk = sk
        self.pk = pk
        self.modo = modo
        email_env, pagador_env = perfil_pagador()
        self.email = email or email_env
        self.pagador = pagador if pagador is not None else pagador_env
        self.exigir_mandato = exigir_mandato
        self.cliente = ClienteWompi(modo)
        self.estado_path = estado_path
        self.estado = self._cargar()

    # -- estado ------------------------------------------------------------- #

    def _cargar(self) -> dict[str, Any]:
        if self.estado_path.exists():
            return json.loads(self.estado_path.read_text(encoding="utf-8"))
        return {"mandatos": {}, "consumo": {}, "dia": "", "gastado_dia_cop": 0}

    def _guardar(self) -> None:
        self.estado_path.parent.mkdir(parents=True, exist_ok=True)
        self.estado_path.write_text(
            json.dumps(self.estado, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _gastado_hoy(self) -> int:
        hoy = date.today().isoformat()
        if self.estado.get("dia") != hoy:
            self.estado["dia"] = hoy
            self.estado["gastado_dia_cop"] = 0
        return self.estado["gastado_dia_cop"]

    # -- mandatos ----------------------------------------------------------- #

    def registrar(self, mandato: Mandato) -> Mandato:
        self.estado["mandatos"][mandato.mandato_id] = mandato.to_json()
        self.estado["consumo"].setdefault(
            mandato.mandato_id, {"usos": 0, "acumulado_cop": 0}
        )
        # El modo va al lado del mandato, no dentro: el mandato esta firmado y
        # agregarle un campo invalidaria las firmas ya emitidas.
        self.estado.setdefault("modos", {})[mandato.mandato_id] = self.modo
        self._guardar()
        return mandato

    def obtener(self, mandato_id: str) -> tuple[Mandato, Consumo]:
        crudo = self.estado["mandatos"].get(mandato_id)
        if not crudo:
            raise BovedaError(f"mandato desconocido: {mandato_id}")

        # Mandatos y fuentes viven en archivos distintos, y `fuentes.json` ya
        # separa por modo. `estado.json` no: un mandato emitido en sandbox es
        # visible desde produccion, y su `fuente_pago` es un entero que alla
        # apunta a otra cuenta. Sin esta guarda, `ejecutar --modo produccion`
        # sobre un mandato de sandbox cobra de verdad contra un desconocido.
        emitido_en = (self.estado.get("modos") or {}).get(mandato_id)
        if emitido_en and emitido_en != self.modo:
            raise BovedaError(
                f"el mandato {mandato_id} se emitio en '{emitido_en}' y se esta "
                f"ejecutando en '{self.modo}'. Su fuente de pago "
                f"({crudo.get('fuente_pago')}) pertenece al otro ambiente."
            )

        c = self.estado["consumo"].get(mandato_id, {"usos": 0, "acumulado_cop": 0})
        return Mandato.from_json(crudo), Consumo(**c)

    # -- ejecucion ---------------------------------------------------------- #

    def ejecutar(self, intencion: Intencion) -> Recibo:
        mandato, consumo = self.obtener(intencion.mandato_id)
        violaciones = evaluar(mandato, intencion, consumo, self.pk)
        v_json = [v.to_json() for v in violaciones]

        # 1. Topes duros. Antes que nada y sin excepcion.
        duro = self._revisar_topes(intencion.monto_cop)
        if duro:
            return Recibo(
                ejecutado=False,
                motivo=duro,
                intencion=intencion.to_json(),
                violaciones=v_json,
                modo=self.modo,
            )

        # 2. El mandato. Esto si se puede apagar, y apagarlo es el experimento.
        if violaciones and self.exigir_mandato:
            return Recibo(
                ejecutado=False,
                motivo="mandato_violado",
                intencion=intencion.to_json(),
                violaciones=v_json,
                modo=self.modo,
            )

        # 3. Cobro.
        referencia = f"bov-{uuid.uuid4().hex[:14]}"
        try:
            creada = self.cliente.cobrar(
                mandato.fuente_pago,
                intencion.monto_cop,
                referencia,
                self.email,
                intencion.descripcion or intencion.sku,
                pagador=self.pagador,
            )
        except BovedaError as exc:
            return Recibo(
                ejecutado=False,
                motivo=f"error_pasarela: {exc}",
                intencion=intencion.to_json(),
                violaciones=v_json,
                referencia=referencia,
                modo=self.modo,
            )

        final = self.cliente.esperar(creada["id"])
        estado = final.get("status", "PENDING")
        aprobada = estado == "APPROVED"

        if aprobada:
            c = self.estado["consumo"][mandato.mandato_id]
            c["usos"] += 1
            c["acumulado_cop"] += intencion.monto_cop
            self._gastado_hoy()
            self.estado["gastado_dia_cop"] += intencion.monto_cop
            self._guardar()

        return Recibo(
            ejecutado=aprobada,
            motivo=estado,
            intencion=intencion.to_json(),
            violaciones=v_json,
            transaction_id=creada["id"],
            referencia=referencia,
            estado_wompi=estado,
            status_message=final.get("status_message"),
            afe_decision=(final.get("payment_method") or {}).get("afe_decision"),
            modo=self.modo,
            aprobado_pese_a_violacion=aprobada and bool(violaciones),
        )

    def _revisar_topes(self, monto_cop: int) -> str | None:
        if monto_cop > LIMITE_DURO_TX_COP:
            return (
                f"tope_duro_transaccion: {monto_cop:,} COP supera el limite de "
                f"{LIMITE_DURO_TX_COP:,} COP por transaccion"
            )
        if self._gastado_hoy() + monto_cop > LIMITE_DURO_DIA_COP:
            return (
                f"tope_duro_diario: llevaria {self._gastado_hoy() + monto_cop:,} COP "
                f"sobre un limite de {LIMITE_DURO_DIA_COP:,} COP"
            )
        return None
