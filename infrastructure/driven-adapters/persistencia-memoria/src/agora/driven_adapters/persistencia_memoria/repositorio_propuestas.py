"""`RepositorioPropuestas` en memoria.

Simetrico a `repositorio_carritos.py` (etapa 5) y por el mismo motivo: un
`dict` protegido por un lock, sin persistencia entre procesos. Alcanza para
pruebas y para `AGORA_PERSISTENCIA=memoria` -- ver `repositorio_propuestas.py`
del paquete `sqlite/` para el caso que si necesita sobrevivir entre procesos
(`entry_points/cli/firmar`, corrido en otra terminal que la que armo el chat).
"""

from __future__ import annotations

import threading

from ...model.commons.errores import PropuestaDesconocida
from ...model.mandato.modelo import PropuestaDeMandato


class RepositorioPropuestasEnMemoria:
    """Implementa `puertos.repositorios.RepositorioPropuestas`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._propuestas: dict[str, PropuestaDeMandato] = {}

    def guardar(self, propuesta: PropuestaDeMandato) -> None:
        with self._lock:
            self._propuestas[propuesta.propuesta_id] = propuesta

    def obtener(self, propuesta_id: str) -> PropuestaDeMandato:
        with self._lock:
            propuesta = self._propuestas.get(propuesta_id)
        if propuesta is None:
            raise PropuestaDesconocida(f"propuesta desconocida: {propuesta_id}")
        return propuesta
