"""`AdaptadorWompi`: el `PasarelaDePagos` que mueve dinero real.

Junto con `EjecutarIntencionUseCase` (`usecase/ejecutar_intencion/ejecutar_intencion_use_case.py`), forma el
motor de pagos contra Wompi. Este archivo es la traduccion: recibe tipos del dominio (`OrdenDeCobro`, `MedioDePagoRef`),
llama al `ClienteWompi` HTTP puro (`cliente.py`), y devuelve `ResultadoCobro`.

Nunca bloquea esperando un estado final. `cobrar()` devuelve lo que Wompi contesto al crear la
transaccion (tipicamente `PENDING`); el desenlace lo resuelve
`consultar_cobro()` o -- el camino principal -- el webhook.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from ...model.commons.errores import ErrorDePasarela
from ...model.pago.modelo import (
    EstadoCobro,
    MedioDePagoRef,
    OrdenDeCobro,
    Proveedor,
    ResultadoCobro,
)
from ...model.pago.gateways.pasarela import EstadoMedio, MedioEnProceso, SolicitudEnrolamiento
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
# adaptador, asi que tambien es lo que separa un evento de `agora` de uno de
# cualquier otro sistema que comparta el mismo webhook de Wompi.
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
        """Solo el paso 1 del enrolamiento (crear el token). El sondeo hasta que el titular acepta el push (paso 2, hasta
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
        """Wompi documenta `PUT /payment_sources/{id}/void` solo para
        DaviPlata y Bancolombia (`docs.wompi.co/.../fuentes-de-pago/`) --
        Nequi, el unico riel que usa esta app (`docs/utils/informe-viabilidad-
        pagos-agenticos-co.md`), no aparece ahi. Contra produccion real (7 sept 2026,
        Juan) Wompi lo confirma en runtime: 422, `"Unicamente se pueden
        anular fuentes de pago con el tipo de operacion financiera
        'PREAUTHORIZATION'"` -- una fuente Nequi no nace con ese tipo de
        operacion, asi que el void nunca va a funcionar para ella, no es un
        error transitorio.

        No hay ningun endpoint documentado para cancelar una fuente Nequi
        por API (se reviso `fuentes-de-pago`, `metodos-de-pago` y el centro
        de soporte de Wompi) -- la unica cancelacion real posible es que el
        titular la baje el mismo desde "Cobro Automatico" en su app Nequi.
        Por eso, cuando Wompi rechaza especificamente por este motivo, esto
        NO se trata como una falla: se desactiva el medio solo del lado de
        esta app (`estado="VOIDED_LOCAL"`, que `RevocarMedioUseCase` va a guardar
        igual que cualquier otro estado no-`AVAILABLE`) y se devuelve un
        aviso explicito en `detalle["aviso"]` para que quien llame (CLI o
        UI) le explique al titular que todavia tiene que cancelarlo del
        lado de Nequi si quiere anular el permiso de verdad. Cualquier OTRO
        error de Wompi (red, 500, credenciales, etc.) sigue levantando --
        esto es una traduccion de un rechazo puntual y documentado, no un
        "tragar cualquier error"."""
        try:
            data = self._cliente.revocar_fuente_de_pago(ref.id_externo)
        except ErrorDePasarela as exc:
            if not self._es_rechazo_por_tipo_no_anulable(exc):
                raise
            return EstadoMedio(
                estado="VOIDED_LOCAL",
                ref=ref,
                detalle={
                    "aviso": (
                        "Wompi no permite cancelar esta fuente de pago por API "
                        "-- el void solo esta documentado para DaviPlata y "
                        "Bancolombia, no para Nequi. Se desactivo unicamente en "
                        "esta app; para anular el permiso de verdad hay que "
                        "cancelarlo tambien desde \"Cobro Automatico\" en la "
                        "app Nequi del titular."
                    ),
                    "motivo_wompi": exc.mensaje,
                },
            )
        return EstadoMedio(estado=data.get("status", "VOIDED"), ref=ref, detalle=data)

    @staticmethod
    def _es_rechazo_por_tipo_no_anulable(exc: ErrorDePasarela) -> bool:
        """`True` solo para el rechazo puntual de Wompi por tipo de
        operacion financiera (ver el docstring de `revocar_medio` arriba) --
        nunca para un rechazo generico, para no esconder un error real
        detras de un "listo" falso."""
        razon = ((exc.detalle_proveedor or {}).get("error") or {}).get("reason", "")
        return "preauthorization" in razon.lower()

    # -- cobro ----------------------------------------------------------- #

    def cobrar(self, orden: OrdenDeCobro) -> ResultadoCobro:
        if orden.medio.proveedor is not Proveedor.WOMPI:
            raise ErrorDePasarela(
                f"el adaptador Wompi no puede cobrar un medio de "
                f"'{orden.medio.proveedor.value}'"
            )
        # ADR-6: la referencia sale de `intencion_id`, no de un uuid nuevo en
        # cada intento. Reintentar
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
            # El dato mas valioso de toda la corrida real (docs/utils/decline-afe.md):
            # el motor antifraude de Wompi es el unico control del flujo que
            # el comercio no puede ver, configurar ni explicarle al titular.
            afe_decision=metodo.get("afe_decision") or "",
            detalle=data,
        )

    # -- eventos ----------------------------------------------------------- #

    def validar_evento(self, cuerpo: bytes, cabeceras: dict[str, str]) -> dict[str, Any]:
        """Como funcion pura:
        sin FastAPI, sin `os.environ` (el secreto ya viene en `config`), y
        devolviendo el evento en vez de escribirlo a un `.jsonl` -- eso lo
        decide quien llame.

        Validar el checksum no es opcional: sin esto, cualquiera que sepa la
        URL puede inventarle al motor de pagos un
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
        (otro tipo de evento, o una referencia sin ese prefijo) no es un cobro
        de esta app: `None`, no un error. Wompi manda todos los eventos de un
        comercio al mismo webhook, asi que puede llegar trafico ajeno.
        """
        if evento.get("event") != "transaction.updated":
            return None
        tx = ((evento.get("data") or {}).get("transaction")) or {}
        referencia = tx.get("reference", "")
        if not referencia.startswith(_PREFIJO_REFERENCIA):
            return None
        intencion_id = referencia[len(_PREFIJO_REFERENCIA):]
        return intencion_id, self._resultado_desde(tx, referencia)
