"""Fase A: el titular autoriza una vez. Con dinero real.

Esto es la frontera de la PoC. Antes de correr esto, cada cobro necesita al
titular. Despues, ninguno lo necesita -- y lo unico que se interpone entre el
agente y la cuenta es la boveda.

    telefono -> POST /tokens/nequi        el titular recibe un push en la app
             -> GET  /tokens/nequi/{id}   se espera a que lo acepte
             -> POST /payment_sources     nace la fuente
             -> AVAILABLE                 desde aqui se cobra sin el titular

No se mueve dinero en ningun paso de este archivo. Lo que se entrega es la
autorizacion, que es peor: el dinero se puede devolver, una autorizacion mal
dada sigue viva hasta que alguien la revoque. Por eso `revocar` esta aqui al
lado y no en un backlog.

LO QUE ESTE ARCHIVO NO HACE
---------------------------
No cobra. Cobrar es `nucleo.py`, y ahi viven los topes duros. Separarlo importa:
enrolar es un acto del titular, cobrar es un acto del agente. Mezclarlos en un
comando haria que la PoC no pueda distinguir cual de los dos fallo.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .nucleo import BovedaError, ClienteWompi

# Cuanto se espera a que el titular acepte el push. Wompi no documenta el
# vencimiento del token, asi que este numero es nuestro, no de ellos.
ESPERA_PUSH_SEG = 300
PAUSA_SONDEO_SEG = 3.0

ESTADOS_TOKEN_FINALES = frozenset({"APPROVED", "DECLINED", "ERROR", "VOIDED"})


@dataclass
class Fuente:
    """Una fuente de pago viva. El numero que le da poder al agente."""

    payment_source_id: int
    tipo: str
    modo: str
    referencia_publica: str  # telefono enmascarado, o ultimos 4 de la tarjeta
    email: str
    estado: str
    creada_en: str
    token: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _enmascarar(telefono: str) -> str:
    return f"{telefono[:3]}****{telefono[-3:]}" if len(telefono) >= 7 else "***"


# --------------------------------------------------------------------------- #
# Registro local de fuentes
# --------------------------------------------------------------------------- #


class RegistroFuentes:
    """Las fuentes vivas, separadas por modo.

    La separacion por modo no es cosmetica. Una fuente de produccion referida
    desde una corrida en sandbox no falla sola: el id existe en los dos mundos
    y el numero es solo un entero. Guardarlas juntas haria que un error de
    tipeo cobre de verdad.
    """

    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        self.datos: dict[str, list[dict]] = self._cargar()

    def _cargar(self) -> dict[str, list[dict]]:
        if self.ruta.exists():
            return json.loads(self.ruta.read_text(encoding="utf-8"))
        return {"sandbox": [], "produccion": []}

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(
            json.dumps(self.datos, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def agregar(self, f: Fuente) -> None:
        self.datos.setdefault(f.modo, []).append(f.to_json())
        self.guardar()

    def listar(self, modo: str) -> list[dict]:
        return self.datos.get(modo, [])

    def marcar(self, modo: str, payment_source_id: int, estado: str) -> bool:
        for f in self.datos.get(modo, []):
            if f["payment_source_id"] == payment_source_id:
                f["estado"] = estado
                self.guardar()
                return True
        return False

    def pertenece(self, modo: str, payment_source_id: int) -> bool:
        return any(
            f["payment_source_id"] == payment_source_id for f in self.datos.get(modo, [])
        )


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #


def preflight(cliente: ClienteWompi) -> dict[str, Any]:
    """Todo lo que hay que saber ANTES de pedirle algo a un humano real.

    Si Nequi no esta habilitado en el comercio, el push nunca llega y el token
    se queda en PENDING sin explicacion. Mejor descubrirlo aqui que con el
    titular mirando el telefono.
    """
    r = cliente.http.get(
        f"{cliente.url}/merchants/{cliente.pub}",
        headers={"Authorization": f"Bearer {cliente.pub}"},
    )
    if r.status_code >= 400:
        raise BovedaError(f"el comercio no responde: {r.status_code} {r.text[:200]}")
    d = r.json()["data"]

    metodos = d.get("accepted_payment_methods") or d.get("payment_methods") or []
    acc = d.get("presigned_acceptance") or {}
    per = d.get("presigned_personal_data_auth") or {}

    return {
        "modo": cliente.modo,
        "url": cliente.url,
        "nombre": d.get("name"),
        "razon_social": d.get("legal_name"),
        "metodos": metodos,
        "nequi_habilitado": "NEQUI" in metodos,
        "tarjeta_habilitada": "CARD" in metodos,
        "permalink_terminos": acc.get("permalink"),
        "permalink_datos": per.get("permalink"),
    }


# --------------------------------------------------------------------------- #
# Enrolamiento Nequi
# --------------------------------------------------------------------------- #


def enrolar_nequi(
    cliente: ClienteWompi,
    telefono: str,
    email: str,
    registro: RegistroFuentes,
    espera_seg: int = ESPERA_PUSH_SEG,
    al_avanzar=None,
) -> Fuente:
    """Los tres pasos, con el titular mirando su telefono en el segundo.

    `al_avanzar` recibe (etapa, detalle) para que la CLI narre sin que este
    modulo sepa nada de como se imprime.
    """
    aviso = al_avanzar or (lambda *_: None)

    if not (telefono.isdigit() and len(telefono) == 10):
        raise BovedaError(
            f"'{telefono}' no parece un celular colombiano. "
            "Se esperan 10 digitos, sin indicativo ni espacios."
        )

    # -- 1. token ----------------------------------------------------------- #
    aviso("token", f"solicitando la suscripcion para {_enmascarar(telefono)}")
    r = cliente.http.post(
        f"{cliente.url}/tokens/nequi",
        headers={"Authorization": f"Bearer {cliente.pub}"},
        json={"phone_number": telefono},
    )
    payload = r.json()
    if r.status_code >= 400:
        raise BovedaError(f"Wompi {r.status_code} al crear el token: {json.dumps(payload)[:300]}")

    token = payload["data"]["id"]
    estado = payload["data"].get("status", "PENDING")
    aviso("token_creado", f"{token[:22]}... estado {estado}")

    # -- 2. el titular acepta ----------------------------------------------- #
    aviso(
        "push",
        "revisa tu app Nequi: llego una notificacion para aceptar la suscripcion",
    )
    limite = time.monotonic() + espera_seg
    while estado not in ESTADOS_TOKEN_FINALES and time.monotonic() < limite:
        time.sleep(PAUSA_SONDEO_SEG)
        rr = cliente.http.get(
            f"{cliente.url}/tokens/nequi/{token}",
            headers={"Authorization": f"Bearer {cliente.pub}"},
        )
        if rr.status_code >= 400:
            raise BovedaError(f"Wompi {rr.status_code} consultando el token")
        estado = rr.json()["data"].get("status", "PENDING")
        aviso("sondeo", estado)

    if estado != "APPROVED":
        raise BovedaError(
            f"el token quedo en '{estado}' y no en APPROVED. "
            "Sin aceptacion del titular no hay fuente de pago."
            + (
                "\n    Si nunca llego el push: confirme que Nequi este habilitado "
                "como medio de pago en el comercio (`preflight`) y que el numero "
                "tenga una cuenta Nequi activa."
                if estado == "PENDING"
                else ""
            )
        )

    # -- 3. fuente de pago -------------------------------------------------- #
    aviso("fuente", "aceptado. Creando la fuente de pago")
    acc, per = cliente.aceptaciones()
    r = cliente.http.post(
        f"{cliente.url}/payment_sources",
        headers={"Authorization": f"Bearer {cliente.prv}"},
        json={
            "type": "NEQUI",
            "token": token,
            "customer_email": email,
            "acceptance_token": acc,
            "accept_personal_auth": per,
        },
    )
    payload = r.json()
    if r.status_code >= 400:
        raise BovedaError(
            f"Wompi {r.status_code} al crear la fuente: {json.dumps(payload)[:300]}"
        )

    d = payload["data"]
    fuente = Fuente(
        payment_source_id=int(d["id"]),
        tipo="NEQUI",
        modo=cliente.modo,
        referencia_publica=_enmascarar(telefono),
        email=email,
        estado=d.get("status", "?"),
        creada_en=_ahora(),
        token=token,
    )
    registro.agregar(fuente)
    aviso("lista", f"fuente {fuente.payment_source_id} en estado {fuente.estado}")
    return fuente


# --------------------------------------------------------------------------- #
# Revocacion
# --------------------------------------------------------------------------- #


def revocar(
    cliente: ClienteWompi, payment_source_id: int, registro: RegistroFuentes
) -> str:
    """Apaga la fuente. Es el unico boton de panico que existe.

    Conviene saber donde esta antes de necesitarlo: si el agente se desboca a
    las once de la noche, esto es lo que corta el suministro. Wompi no ofrece
    nada mas fino -- no hay 'pausar', no hay 'bajar el tope'. O esta viva o no.
    """
    if not registro.pertenece(cliente.modo, payment_source_id):
        raise BovedaError(
            f"la fuente {payment_source_id} no esta registrada en modo "
            f"'{cliente.modo}'. Revocar a ciegas puede apagar la fuente "
            "equivocada; use `fuentes` para ver cuales conoce la boveda."
        )

    r = cliente.http.put(
        f"{cliente.url}/payment_sources/{payment_source_id}/void",
        headers={"Authorization": f"Bearer {cliente.prv}"},
    )
    payload = r.json() if r.content else {}
    if r.status_code >= 400:
        raise BovedaError(
            f"Wompi {r.status_code} al revocar: {json.dumps(payload)[:300]}"
        )

    estado = (payload.get("data") or {}).get("status", "VOIDED")
    registro.marcar(cliente.modo, payment_source_id, estado)
    return estado
