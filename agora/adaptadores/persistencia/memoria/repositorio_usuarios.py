"""`RepositorioUsuarios` en memoria: pruebas, y `AGORA_PERSISTENCIA=memoria`."""

from __future__ import annotations

import threading

from ....model.usuario.modelo import Usuario


class RepositorioUsuariosEnMemoria:
    """Implementa `puertos.repositorios.RepositorioUsuarios`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._por_titular: dict[str, Usuario] = {}
        self._titular_de_nombre: dict[str, str] = {}

    def guardar(self, usuario: Usuario) -> None:
        with self._lock:
            self._por_titular[usuario.titular_id] = usuario
            self._titular_de_nombre[usuario.nombre_usuario] = usuario.titular_id

    def buscar_por_nombre_usuario(self, nombre_usuario: str) -> Usuario | None:
        with self._lock:
            titular_id = self._titular_de_nombre.get(nombre_usuario)
            return self._por_titular.get(titular_id) if titular_id is not None else None

    def buscar_por_titular(self, titular_id: str) -> Usuario | None:
        with self._lock:
            return self._por_titular.get(titular_id)
