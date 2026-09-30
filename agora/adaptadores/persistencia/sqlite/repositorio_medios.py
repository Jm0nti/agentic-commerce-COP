"""`RepositorioMedios` contra SQLite. Equivalente a `boveda/secretos/
fuentes.json`, que ya separaba por modo -- aqui el ambiente es parte de la
llave primaria en vez de una clave de nivel superior en el JSON.

Multi-comercio: `comercio_id` viaja en cada fila -- ver el docstring de
`puertos.repositorios.RepositorioMedios` y de `esquema.py` (la migracion
para bases creadas antes de esta version).
"""

from __future__ import annotations

from pathlib import Path

from ....model.pago.modelo import Ambiente, MedioDePagoRef, Proveedor
from .conexion import abrir_conexion


class RepositorioMediosSQLite:
    """Implementa `puertos.repositorios.RepositorioMedios`."""

    def __init__(self, ruta: Path, reloj=None) -> None:
        self._ruta = ruta
        self._reloj = reloj

    def guardar(self, ref: MedioDePagoRef, titular_id: str, comercio_id: str) -> None:
        creado_en = self._reloj.ahora().isoformat() if self._reloj else None
        con = abrir_conexion(self._ruta)
        try:
            con.execute(
                "INSERT OR REPLACE INTO medio_de_pago "
                "(proveedor, ambiente, id_externo, titular_id, comercio_id, estado, creado_en) "
                "VALUES (?, ?, ?, ?, ?, 'AVAILABLE', ?)",
                (
                    ref.proveedor.value, ref.ambiente.value, ref.id_externo,
                    titular_id, comercio_id, creado_en,
                ),
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

    def vinculado_con(
        self, titular_id: str, comercio_id: str, ambiente: Ambiente
    ) -> MedioDePagoRef | None:
        con = abrir_conexion(self._ruta)
        try:
            # El mas reciente: `rowid` sube con cada INSERT (`INSERT OR
            # REPLACE` conserva el rowid de la fila que reemplaza, asi que
            # sigue siendo un orden valido de "mas nuevo primero" entre
            # medios distintos). Mismo criterio que la version en memoria.
            fila = con.execute(
                "SELECT proveedor, ambiente, id_externo FROM medio_de_pago "
                "WHERE titular_id = ? AND comercio_id = ? AND ambiente = ? "
                "AND estado = 'AVAILABLE' ORDER BY rowid DESC LIMIT 1",
                (titular_id, comercio_id, ambiente.value),
            ).fetchone()
        finally:
            con.close()
        if fila is None:
            return None
        proveedor, amb, id_externo = fila
        return MedioDePagoRef(Proveedor(proveedor), Ambiente(amb), id_externo)

    def comercio_de(self, ref: MedioDePagoRef) -> str | None:
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                "SELECT comercio_id FROM medio_de_pago "
                "WHERE proveedor = ? AND ambiente = ? AND id_externo = ?",
                (ref.proveedor.value, ref.ambiente.value, ref.id_externo),
            ).fetchone()
        finally:
            con.close()
        if fila is None or not fila[0]:
            return None
        return fila[0]

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
