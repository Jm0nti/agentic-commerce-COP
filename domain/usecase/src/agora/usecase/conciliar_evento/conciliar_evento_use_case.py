"""El otro lado del cobro que no bloquea (`usecase/ejecutar_intencion/ejecutar_intencion_use_case.py`,
paso 4): cuando `_cobrar` devuelve `PENDIENTE`, la reserva queda viva y el
desenlace lo cierra este caso de uso, llamado desde el webhook de la
pasarela (`entry_points/webhook_wompi/wompi.py`, etapa 4).

    webhook -> validar_evento -> resultado_desde_evento -> reserva_pendiente_de
                                                                    |
                                                    confirmar (APROBADO)
                                                    liberar (otro estado final)
                                                    nada (sigue PENDIENTE)

Cada paso puede terminar en "no hay nada que hacer" sin que eso sea un error:
un evento invalido, uno que no es un cobro de esta app, o uno para una
intencion sin reserva pendiente son todos desenlaces normales de un webhook
que -- por diseno -- puede reintentar, llegar duplicado, o llegar para
trafico ajeno. Por eso `__call__` nunca levanta: devuelve un
`ResultadoConciliacion` y quien llame (el receptor HTTP) siempre responde 200.

MULTI-COMERCIO (1 de septiembre de 2026)
-----------------------------------------
Cada comercio real tiene su propio `WOMPI_EVENTS_SECRET`, y validar el
checksum de un evento exige saber CONTRA CUAL. A diferencia de
`EjecutarIntencionUseCase` (que ya tiene `mandato.comercio_id` disponible antes de
cobrar), este caso de uso arranca de un cuerpo HTTP crudo -- no hay mandato
ni intencion todavia, asi que no hay de donde sacar el comercio del
CONTENIDO del evento antes de haberlo validado. La unica fuente confiable es
la URL que lo trajo: `entry_points/webhook_wompi/wompi.py` la lee del path
(`/pagos/wompi/transacciones/{comercio_id}`, un segmento por cada comercio
configurado en su propio dashboard de Wompi) y se la pasa a `__call__` como
parametro nuevo -- por eso, a diferencia de `EjecutarIntencionUseCase`, ac'a el
`comercio_id` no sale de adentro del caso de uso sino de quien lo llama.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...model.commons.errores import ErrorDePasarela
from ...model.pago.modelo import EstadoCobro, ResultadoCobro
from ...model.pago.gateways.pasarela import SelectorDePasarela
from ...model.mandato.gateways.repositorios import LibroDeConsumo
from ...model.pago.gateways.repositorios import RegistroDeEstados
from ...model.commons.gateways.sistema import Bitacora


@dataclass(frozen=True)
class ResultadoConciliacion:
    """Lo que paso al intentar conciliar un evento. `procesado=False` no es
    un fallo -- ver el docstring del modulo."""

    procesado: bool
    motivo: str
    intencion_id: str | None = None
    resultado: ResultadoCobro | None = None


class ConciliarEventoUseCase:
    def __init__(
        self,
        consumo: LibroDeConsumo,
        selector_pasarela: SelectorDePasarela,
        bitacora: Bitacora,
        estados: RegistroDeEstados | None = None,
    ) -> None:
        self._consumo = consumo
        self._selector = selector_pasarela
        self._bitacora = bitacora
        # Igual que en `EjecutarIntencionUseCase`: opcional, `None` por defecto, sin
        # efecto sobre quien ya construye `ConciliarEventoUseCase` sin pasarlo.
        self._estados = estados

    def __call__(
        self, cuerpo: bytes, cabeceras: dict[str, str], comercio_id: str,
    ) -> ResultadoConciliacion:
        try:
            pasarela = self._selector.para(comercio_id)
        except ErrorDePasarela as exc:
            # Un comercio_id en la URL que ya no tiene credenciales
            # configuradas (se desconecto ese comercio, o nunca existio) es
            # el mismo tipo de "no hay nada que hacer" que un checksum
            # invalido -- no un fallo del receptor. Wompi sigue esperando
            # su 200.
            return self._ignorado("comercio_sin_pasarela", str(exc))

        try:
            evento = pasarela.validar_evento(cuerpo, cabeceras)
        except ErrorDePasarela as exc:
            return self._ignorado("evento_invalido", str(exc))

        traduccion = pasarela.resultado_desde_evento(evento)
        if traduccion is None:
            return self._ignorado("evento_no_reconocido", "el evento no es un cobro de esta app")
        intencion_id, resultado = traduccion

        reserva = self._consumo.reserva_pendiente_de(intencion_id)
        if reserva is None:
            return self._ignorado(
                "sin_reserva_pendiente",
                f"no hay una reserva pendiente para '{intencion_id}' -- ya se "
                "resolvio, o el evento no es de esta app",
                intencion_id=intencion_id,
                resultado=resultado,
            )

        if resultado.estado is EstadoCobro.APROBADO:
            self._consumo.confirmar(reserva)
        elif resultado.estado.es_final:
            self._consumo.liberar(reserva)
        else:
            # Sigue PENDIENTE: nada que resolver todavia. No es un error --
            # es exactamente el estado en el que `_cobrar` dejo la reserva.
            return self._ignorado(
                "sigue_pendiente", "el cobro sigue pendiente",
                intencion_id=intencion_id, resultado=resultado,
            )

        conciliado = ResultadoConciliacion(
            procesado=True, motivo=resultado.estado.value,
            intencion_id=intencion_id, resultado=resultado,
        )
        self._bitacora.anotar("conciliado", conciliado)
        if self._estados is not None:
            estado = "aprobado" if resultado.estado is EstadoCobro.APROBADO else "rechazado"
            self._estados.fijar(intencion_id, estado, resultado.estado.value)
        return conciliado

    def _ignorado(
        self, motivo: str, detalle: str,
        intencion_id: str | None = None, resultado: ResultadoCobro | None = None,
    ) -> ResultadoConciliacion:
        cuerpo = {"motivo": motivo, "detalle": detalle, "intencion_id": intencion_id}
        self._bitacora.anotar("evento_ignorado", cuerpo)
        return ResultadoConciliacion(
            procesado=False, motivo=motivo, intencion_id=intencion_id, resultado=resultado,
        )
