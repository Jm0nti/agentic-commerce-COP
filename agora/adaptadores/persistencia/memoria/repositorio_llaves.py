"""`RepositorioLlaves` en memoria: pruebas, y `AGORA_PERSISTENCIA=memoria`."""

from __future__ import annotations

import threading


class RepositorioLlavesEnMemoria:
    """Implementa `puertos.repositorios.RepositorioLlaves`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._privadas: dict[str, bytes] = {}
        self._publicas: dict[str, bytes] = {}

    def guardar(self, titular_id: str, llave_privada: bytes, llave_publica: bytes) -> None:
        with self._lock:
            self._privadas[titular_id] = llave_privada
            self._publicas[titular_id] = llave_publica

    def llave_privada_de(self, titular_id: str) -> bytes | None:
        with self._lock:
            return self._privadas.get(titular_id)
