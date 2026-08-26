"""`RegistroDeEstados` contra SQLite. Ver el comentario de la tabla
`estado_intencion` en `esquema.py` para el porque -- sin esto, `retomar`
corrido en otra terminal (siempre otra terminal: nunca es herramienta del
agente) deja al `chat` sin forma de enterarse de que la intencion ya se
resolvio.
"""

from __future__ import annotations

from pathlib import Path

from .conexion import abrir_conexion


class RegistroDeEstadosSQLite:
    """Implementa `puertos.repositorios.RegistroDeEstados`."""

    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta

    def fijar(self, intencion_id: str, estado: str, detalle: str = "") -> None:
        con = abrir_conexion(self._ruta)
        try:
            con.execute(
                "INSERT OR REPLACE INTO estado_intencion (intencion_id, estado, detalle) "
                "VALUES (?, ?, ?)",
                (intencion_id, estado, detalle),
            )
        finally:
            con.close()

    def obtener(self, intencion_id: str) -> tuple[str, str] | None:
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                "SELECT estado, detalle FROM estado_intencion WHERE intencion_id = ?",
                (intencion_id,),
            ).fetchone()
        finally:
            con.close()
        if fila is None:
            return None
        return (fila[0], fila[1])
