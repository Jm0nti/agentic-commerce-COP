"""Adaptadores de persistencia contra SQLite (etapa 3): la reserva atomica de
verdad, que sobrevive un reinicio. Ver `libro_consumo.py` para la razon por
la que `adaptadores/persistencia/memoria/` no basta contra dinero real.
"""

from __future__ import annotations

from .libro_consumo import LibroDeConsumoSQLite
from .repositorio_mandatos import RepositorioMandatosSQLite
from .repositorio_medios import RepositorioMediosSQLite

__all__ = [
    "LibroDeConsumoSQLite",
    "RepositorioMandatosSQLite",
    "RepositorioMediosSQLite",
]
