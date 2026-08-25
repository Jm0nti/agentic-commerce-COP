"""El otro lado del cobro que no bloquea (`aplicacion/ejecutar_intencion.py`,
paso 4): cuando `_cobrar` devuelve `PENDIENTE`, la reserva queda viva y el
desenlace lo cierra este caso de uso, llamado desde el webhook de la
pasarela (`entradas/webhooks/wompi.py`, etapa 4).

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
`ResultadoConciliacion` y quien llame (el receptor HTTP) siempre responde 200,
igual que `boveda/eventos.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..dominio.comun.errores import ErrorDePasarela
from ..dominio.pago.modelo import EstadoCobro, ResultadoCobro
from ..puertos.pasarela import PasarelaDePagos
from ..puertos.repositorios import LibroDeConsumo
from ..puertos.sistema import Bitacora


@dataclass(frozen=True)
class ResultadoConciliacion:
    """Lo que paso al intentar conciliar un evento. `procesado=False` no es
    un fallo -- ver el docstring del modulo."""

    procesado: bool
    motivo: str
    intencion_id: str | None = None
    resultado: ResultadoCobro | None = None


class ConciliarEvento:
    def __init__(
        self,
        consumo: LibroDeConsumo,
        pasarela: PasarelaDePagos,
        bitacora: Bitacora,
    ) -> None:
        self._consumo = consumo
        self._pasarela = pasarela
        self._bitacora = bitacora

    def __call__(self, cuerpo: bytes, cabeceras: dict[str, str]) -> ResultadoConciliacion:
        try:
            evento = self._pasarela.validar_evento(cuerpo, cabeceras)
        except ErrorDePasarela as exc:
            return self._ignorado("evento_invalido", str(exc))

        traduccion = self._pasarela.resultado_desde_evento(evento)
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
