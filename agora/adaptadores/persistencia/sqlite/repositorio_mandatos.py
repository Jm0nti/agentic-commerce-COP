"""`RepositorioMandatos` contra SQLite.

Misma guarda de ambiente que `RepositorioMandatosEnMemoria` (etapa 2) y que
`nucleo.py:319-330` en la v1 -- aqui sobrevive un reinicio, que es
precisamente lo que la version en memoria no puede ofrecer.
"""

from __future__ import annotations

from pathlib import Path

from ....dominio.comun.errores import MandatoDesconocido, MandatoDeOtroAmbiente
from ....dominio.mandato.modelo import Mandato
from ....dominio.pago.modelo import Ambiente
from .conexion import abrir_conexion
from .serializacion import COLUMNAS, fila_a_mandato, mandato_a_fila

_PLACEHOLDERS = ", ".join("?" * len(COLUMNAS))
_COLUMNAS_SQL = ", ".join(COLUMNAS)


class RepositorioMandatosSQLite:
    """Implementa `puertos.repositorios.RepositorioMandatos`."""

    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta

    def guardar(self, mandato: Mandato, ambiente: Ambiente) -> None:
        con = abrir_conexion(self._ruta)
        try:
            con.execute(
                f"INSERT OR REPLACE INTO mandato ({_COLUMNAS_SQL}) VALUES ({_PLACEHOLDERS})",
                mandato_a_fila(mandato, ambiente),
            )
        finally:
            con.close()

    def obtener(self, mandato_id: str, ambiente: Ambiente) -> Mandato:
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                f"SELECT {_COLUMNAS_SQL} FROM mandato WHERE mandato_id = ?", (mandato_id,)
            ).fetchone()
        finally:
            con.close()

        if fila is None:
            raise MandatoDesconocido(f"mandato desconocido: {mandato_id}")

        guardado_en = fila[1]  # columna "ambiente"
        mandato = fila_a_mandato(fila)
        if guardado_en != ambiente.value:
            raise MandatoDeOtroAmbiente(
                f"el mandato {mandato_id} se guardo en '{guardado_en}' y se esta "
                f"pidiendo desde '{ambiente.value}'. Su medio de pago "
                f"({mandato.medio.id_externo}) pertenece al otro ambiente."
            )
        return mandato

    def listar(self, ambiente: Ambiente) -> list[Mandato]:
        con = abrir_conexion(self._ruta)
        try:
            filas = con.execute(
                f"SELECT {_COLUMNAS_SQL} FROM mandato WHERE ambiente = ?", (ambiente.value,)
            ).fetchall()
        finally:
            con.close()
        return [fila_a_mandato(f) for f in filas]
