"""`RepositorioUsuarios` contra SQLite. Multi-usuario (4 de septiembre de
2026): la tabla `usuario`, uno a uno con `dominio.usuario.modelo.Usuario`.

`nombre_usuario` es UNIQUE en el esquema (`esquema.py`) -- en la practica
nunca deberia chocar: `RegistrarUsuarioUseCase` (`usecase/{registrar_usuario,iniciar_sesion}/`) ya
verifica `buscar_por_nombre_usuario` antes de llamar a `guardar`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ...model.usuario.modelo import Usuario
from .conexion import abrir_conexion


class RepositorioUsuariosSQLite:
    """Implementa `puertos.repositorios.RepositorioUsuarios`."""

    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta

    def guardar(self, usuario: Usuario) -> None:
        con = abrir_conexion(self._ruta)
        try:
            con.execute(
                "INSERT OR REPLACE INTO usuario "
                "(titular_id, nombre_usuario, contrasena_hash, creado_en) "
                "VALUES (?, ?, ?, ?)",
                (
                    usuario.titular_id, usuario.nombre_usuario,
                    usuario.contrasena_hash, usuario.creado_en.isoformat(),
                ),
            )
        finally:
            con.close()

    def buscar_por_nombre_usuario(self, nombre_usuario: str) -> Usuario | None:
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                "SELECT titular_id, nombre_usuario, contrasena_hash, creado_en "
                "FROM usuario WHERE nombre_usuario = ?",
                (nombre_usuario,),
            ).fetchone()
        finally:
            con.close()
        return self._desde_fila(fila)

    def buscar_por_titular(self, titular_id: str) -> Usuario | None:
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                "SELECT titular_id, nombre_usuario, contrasena_hash, creado_en "
                "FROM usuario WHERE titular_id = ?",
                (titular_id,),
            ).fetchone()
        finally:
            con.close()
        return self._desde_fila(fila)

    @staticmethod
    def _desde_fila(fila) -> Usuario | None:
        if fila is None:
            return None
        titular_id, nombre_usuario, contrasena_hash, creado_en = fila
        return Usuario(
            titular_id=titular_id,
            nombre_usuario=nombre_usuario,
            contrasena_hash=contrasena_hash,
            creado_en=datetime.fromisoformat(creado_en),
        )
