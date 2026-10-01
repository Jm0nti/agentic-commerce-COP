"""`RepositorioLlaves` contra SQLite. Multi-usuario (4 de septiembre de
2026): la tabla `llave_firma`, una fila por titular -- la llave privada y
la publica en crudo (BLOB). Ver el docstring de `puertos.repositorios.
RepositorioLlaves` sobre por que esto vive separado de la tabla `usuario`.
"""

from __future__ import annotations

from pathlib import Path

from .conexion import abrir_conexion


class RepositorioLlavesSQLite:
    """Implementa `puertos.repositorios.RepositorioLlaves`."""

    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta

    def guardar(self, titular_id: str, llave_privada: bytes, llave_publica: bytes) -> None:
        con = abrir_conexion(self._ruta)
        try:
            con.execute(
                "INSERT OR REPLACE INTO llave_firma (titular_id, llave_privada, llave_publica) "
                "VALUES (?, ?, ?)",
                (titular_id, llave_privada, llave_publica),
            )
        finally:
            con.close()

    def llave_privada_de(self, titular_id: str) -> bytes | None:
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                "SELECT llave_privada FROM llave_firma WHERE titular_id = ?",
                (titular_id,),
            ).fetchone()
        finally:
            con.close()
        return fila[0] if fila is not None else None
