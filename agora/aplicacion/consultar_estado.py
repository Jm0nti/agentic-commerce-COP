"""`ConsultarEstado`: la herramienta que le deja al agente preguntar que paso
con una intencion sin bloquear -- `pagar()` (etapa 4 en adelante) devuelve de
inmediato con el cobro en `PENDIENTE`, y el desenlace real llega despues por
webhook (`aplicacion/conciliar_evento.py`). Sin esta pregunta, el agente no
tendria como contarle al usuario si la compra se aprobo o no salvo esperando
a que alguien mas se lo diga.

Envoltorio delgado sobre `RegistroDeEstados` (ver su docstring en
`puertos/repositorios.py` para el porque no alcanza con `LibroDeConsumo` ni
con `Bitacora`).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..dominio.comun.errores import EstadoDesconocido
from ..puertos.repositorios import RegistroDeEstados


@dataclass(frozen=True)
class EstadoIntencion:
    intencion_id: str
    estado: str
    detalle: str = ""


class ConsultarEstado:
    def __init__(self, estados: RegistroDeEstados) -> None:
        self._estados = estados

    def __call__(self, intencion_id: str) -> EstadoIntencion:
        entrada = self._estados.obtener(intencion_id)
        if entrada is None:
            raise EstadoDesconocido(
                f"no hay ningun estado registrado para '{intencion_id}' -- nunca "
                "se ejecuto, o el registro se reinicio"
            )
        estado, detalle = entrada
        return EstadoIntencion(intencion_id=intencion_id, estado=estado, detalle=detalle)
