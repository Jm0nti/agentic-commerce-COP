"""`AdaptadorWompi`: el `PasarelaDePagos` que mueve dinero real.

Junto con `EjecutarIntencion` (`aplicacion/ejecutar_intencion.py`), es en lo
que se parte `Boveda.ejecutar` (`boveda/nucleo.py:337-408`). Este archivo es
la traduccion: recibe tipos del dominio (`OrdenDeCobro`, `MedioDePagoRef`),
llama al `ClienteWompi` HTTP puro (`cliente.py`), y devuelve `ResultadoCobro`.

Nunca bloquea esperando un estado final -- a diferencia de
`ClienteWompi.esperar()` en la v1 (`nucleo.py:214-225`, hasta 60s de
`time.sleep`). `cobrar()` devuelve lo que Wompi contesto al crear la
transaccion (tipicamente `PENDING`); el desenlace lo resuelve
`consultar_cobro()` o -- el camino principal en la v2 -- el webhook.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from ....dominio.comun.errores import ErrorDePasarela
from ....dominio.pago.modelo import (
    EstadoCobro,
    MedioDePagoRef,
    OrdenDeCobro,
    Proveedor,
    ResultadoCobro,
)
from ....puertos.pasarela import EstadoMedio, MedioEnProceso, SolicitudEnrolamiento
from .cliente import ClienteWompi
from .config import ConfiguracionWompi

_ESTADOS_WOMPI: dict[str, EstadoCobro] = {
    "PENDING": EstadoCobro.PENDIENTE,
    "APPROVED": EstadoCobro.APROBADO,
    "DECLINED": EstadoCobro.RECHAZADO,
    "VOIDED": EstadoCobro.ANULADO,
    "ERROR": EstadoCobro.ERROR,
}


def _estado_cobro(bruto: str) -> EstadoCobro:
    return _ESTADOS_WOMPI.get(bruto, EstadoCobro.ERROR)


# ADR-6: la referencia sale de `intencion_id`. El prefijo es propio de este
# adaptador -- la v1 (`boveda/nucleo.py:364`) nunca lo uso -- asi que tambien
# es lo que separa un evento de `agora/` de uno viejo de `boveda/` si algun
# dia los dos comparten el mismo webhook de Wompi.
_PREFIJO_REFERENCIA = "agora-"


class AdaptadorWompi:
    """Implementa `puertos.pasarela.PasarelaDePagos`."""

    nombre = "wompi"

    def __init__(
        self, config: ConfiguracionWompi, cliente: ClienteWompi | None = None
    ) -> None:
        self._config = config
        self._cliente = cliente or ClienteWompi(config)

    # -- enrolamiento ----------------------------------------------------------- #

    def preparar_medio(self, solicitud: SolicitudEnrolamiento) -> MedioEnProceso:
        """Solo el paso 1 de `boveda/enrolamiento.py:enrolar_nequi` (crear el
        token). El sondeo hasta que el titular acepta el push (paso 2, hasta
        300s) ya no vive aqui: bloquear un adaptador esperando a un humano es
        el mismo problema que `esperar()` en el cobro. Quien orqueste el
        enrolamiento sondea `estado_medio_por_token` a su propio ritmo.
        """
        data = self._cliente.crear_token_nequi(solicitud.telefono)
        return MedioEnProceso(token=data["id"], estado=data.get("status", "PENDING"))

    def estado_medio_por_token(self, token: str) -> EstadoMedio:
        data = self._cliente.consultar_token_nequi(token)
        return EstadoMedio(estado=data.get("status", "PENDING"))

    def confirmar_medio(self, token: str, correo: str) -> EstadoMedio:
        data = self._cliente.crear_fuente_de_pago(token, correo)
        ref = MedioDePagoRef(Proveedor.WOMPI, self._config.ambiente, str(data["id"]))
        return EstadoMedio(estado=data.get("status", "?"), ref=ref, detalle=data)

    def revocar_medio(self, ref: MedioDePagoRef) -> EstadoMedio:
        data = self._cliente.revocar_fuente_de_pago(ref.id_externo)
        return EstadoMedio(estado=data.get("status", "VOIDED"), ref=ref, detalle=data)

    # -- cobro ----------------------------------------------------------- #

    def cobrar(self, orden: OrdenDeCobro) -> ResultadoCobro:
        if orden.medio.proveedor is not Proveedor.WOMPI:
            raise ErrorDePasarela(
                f"el adaptador Wompi no puede cobrar un medio de "
                f"'{orden.medio.proveedor.value}'"
            )
        # ADR-6: la referencia sale de `intencion_id`, no de un uuid nuevo en
        # cada intento (`nucleo.py:364` generaba uno por llamada). Reintentar
        # deja de poder duplicar un cobro: si el POST llega a Wompi pero la
        # respuesta se pierde, el reintento reusa la misma referencia y Wompi
        # rechaza el duplicado en vez de cobrar dos veces.
        referencia = f"{_PREFIJO_REFERENCIA}{orden.intencion_id}"
        data = self._cliente.crear_transaccion(
            id_externo_fuente=orden.medio.id_externo,
            centavos=orden.monto.centavos,
            referencia=referencia,
            correo=orden.correo_pagador,
            pagador=orden.datos_pagador or None,
        )
        return self._resultado_desde(data, referencia)

    def consultar_cobro(self, id_externo: str) -> ResultadoCobro:
        data = self._cliente.consultar_transaccion(id_externo)
        return self._resultado_desde(data, data.get("reference", ""))

    @staticmethod
    def _resultado_desde(data: dict[str, Any], referencia: str) -> ResultadoCobro:
        metodo = data.get("payment_method") or {}
        return ResultadoCobro(
            estado=_estado_cobro(data.get("status", "ERROR")),
            id_externo=str(data.get("id", "")),
            referencia=referencia,
            status_message=data.get("status_message") or "",
            # El dato mas valioso de toda la corrida real (docs/hallazgo-afe.md):
            # el motor antifraude de Wompi es el unico control del flujo que
            # el comercio no puede ver, configurar ni explicarle al titular.
            afe_decision=metodo.get("afe_decision") or "",
            detalle=data,
        )

    # -- eventos ----------------------------------------------------------- #

    def validar_evento(self, cuerpo: bytes, cabeceras: dict[str, str]) -> dict[str, Any]:
        """Puerto a puerto con `boveda/eventos.py`, pero como funcion pura:
        sin FastAPI, sin `os.environ` (el secreto ya viene en `config`), y
        devolviendo el evento en vez de escribirlo a un `.jsonl` -- eso lo
        decide quien llame.

        Validar el checksum no es opcional (docs de `boveda/eventos.py`): sin
        esto, cualquiera que sepa la URL puede inventarle a la boveda un
        `transaction.updated` con `APPROVED` que nunca paso. Levanta si no
        valida; no hay un "evento invalido pero seguimos".
        """
        try:
            evento = json.loads(cuerpo)
        except ValueError as exc:
            raise ErrorDePasarela("el evento no es JSON valido") from exc

        firma = evento.get("signature") or {}
        propiedades = firma.get("properties")
        data = evento.get("data")
        ts = evento.get("timestamp")
        recibido = firma.get("checksum")

        if not (propiedades and isinstance(data, dict) and ts is not None and recibido):
            raise ErrorDePasarela(
                "el evento no trae lo necesario para calcular el checksum",
                detalle_proveedor=evento,
            )

        partes: list[str] = []
        for ruta in propiedades:
            valor: Any = data
            for parte in ruta.split("."):
                valor = valor.get(parte) if isinstance(valor, dict) else None
            if valor is None:
                raise ErrorDePasarela(
                    f"el evento no trae '{ruta}', no se puede calcular el checksum",
                    detalle_proveedor=evento,
                )
            partes.append(str(valor))
        partes.append(str(ts))
        partes.append(self._config.secreto_eventos)
        esperado = hashlib.sha256("".join(partes).encode("utf-8")).hexdigest()

        # Comparacion en tiempo constante: es barato y evita regalar
        # informacion sobre en que caracter fallo la comparacion.
        if not hmac.compare_digest(esperado, str(recibido)):
            raise ErrorDePasarela("el checksum del evento no coincide", detalle_proveedor=evento)

        return evento

    def resultado_desde_evento(self, evento: dict[str, Any]) -> tuple[str, ResultadoCobro] | None:
        """`evento` ya paso por `validar_evento`: el checksum es de fiar.

        Solo traduce `transaction.updated` con una referencia que empiece con
        `agora-` -- el prefijo que `cobrar()` le puso. Cualquier otra cosa
        (otro tipo de evento, o una referencia sin ese prefijo -- por ejemplo
        de la v1, que nunca lo uso) no es un cobro de esta app: `None`, no un
        error. Wompi manda todos los eventos de un comercio al mismo webhook,
        asi que un dia podria convivir trafico de `boveda/` y de `agora/` en
        el mismo buzon.
        """
        if evento.get("event") != "transaction.updated":
            return None
        tx = ((evento.get("data") or {}).get("transaction")) or {}
        referencia = tx.get("reference", "")
        if not referencia.startswith(_PREFIJO_REFERENCIA):
            return None
        intencion_id = referencia[len(_PREFIJO_REFERENCIA):]
        return intencion_id, self._resultado_desde(tx, referencia)
