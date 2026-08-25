"""`RepositorioMedios` contra SQLite. Equivalente a `boveda/secretos/
fuentes.json`, que ya separaba por modo -- aqui el ambiente es parte de la
llave primaria en vez de una clave de nivel superior en el JSON.
"""

from __future__ import annotations

from pathlib import Path

from ....dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor
from .conexion import abrir_conexion


class RepositorioMediosSQLite:
    """Implementa `puertos.repositorios.RepositorioMedios`."""

    def __init__(self, ruta: Path, reloj=None) -> None:
        self._ruta = ruta
        self._reloj = reloj

    def guardar(self, ref: MedioDePagoRef, titular_id: str) -> None:
        creado_en = self._reloj.ahora().isoformat() if self._reloj else None
        con = abrir_conexion(self._ruta)
        try:
            con.execute(
                "INSERT OR REPLACE INTO medio_de_pago "
                "(proveedor, ambiente, id_externo, titular_id, estado, creado_en) "
                "VALUES (?, ?, ?, ?, 'AVAILABLE', ?)",
                (ref.proveedor.value, ref.ambiente.value, ref.id_externo, titular_id, creado_en),
            )
        finally:
            con.close()

    def vivos(self, titular_id: str, ambiente: Ambiente) -> list[MedioDePagoRef]:
        con = abrir_conexion(self._ruta)
        try:
            filas = con.execute(
                "SELECT proveedor, ambiente, id_externo FROM medio_de_pago "
                "WHERE titular_id = ? AND ambiente = ? AND estado = 'AVAILABLE'",
                (titular_id, ambiente.value),
            ).fetchall()
        finally:
            con.close()
        return [
            MedioDePagoRef(Proveedor(proveedor), Ambiente(amb), id_externo)
            for proveedor, amb, id_externo in filas
        ]

    def marcar_estado(self, ref: MedioDePagoRef, estado: str) -> None:
        con = abrir_conexion(self._ruta)
        try:
            con.execute(
                "UPDATE medio_de_pago SET estado = ? "
                "WHERE proveedor = ? AND ambiente = ? AND id_externo = ?",
                (estado, ref.proveedor.value, ref.ambiente.value, ref.id_externo),
            )
        finally:
            con.close()
