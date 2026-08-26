"""`RegistroDeEstados` en memoria. Ver el docstring del puerto
(`puertos/repositorios.py`) para el porque existe: sin esto, no hay forma de
que `consultar_estado` distinga una intencion nunca ejecutada de una que ya
se resolvio en `RECHAZADO`.

`fijar` sobreescribe -- una intencion pasa de "pendiente" a "aprobado" (o a
"rechazado") a lo largo de su vida, y solo el ultimo estado importa para
quien pregunta.
"""

from __future__ import annotations

import threading


class RegistroDeEstadosEnMemoria:
    """Implementa `puertos.repositorios.RegistroDeEstados`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._estados: dict[str, tuple[str, str]] = {}

    def fijar(self, intencion_id: str, estado: str, detalle: str = "") -> None:
        with self._lock:
            self._estados[intencion_id] = (estado, detalle)

    def obtener(self, intencion_id: str) -> tuple[str, str] | None:
        with self._lock:
            return self._estados.get(intencion_id)
