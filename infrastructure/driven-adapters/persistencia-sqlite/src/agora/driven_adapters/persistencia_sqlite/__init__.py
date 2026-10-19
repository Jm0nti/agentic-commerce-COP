"""Adaptadores de persistencia contra SQLite (etapa 3): la reserva atomica de
verdad, que sobrevive un reinicio. Ver `libro_consumo.py` para la razon por
la que `driven_adapters/persistencia_memoria/` no basta contra dinero real.
"""

from __future__ import annotations

from .libro_consumo import LibroDeConsumoSQLite
from .registro_estados import RegistroDeEstadosSQLite
from .repositorio_carritos import RepositorioCarritosSQLite
from .repositorio_llaves import RepositorioLlavesSQLite
from .repositorio_mandatos import RepositorioMandatosSQLite
from .repositorio_medios import RepositorioMediosSQLite
from .repositorio_propuestas import RepositorioPropuestasSQLite
from .repositorio_usuarios import RepositorioUsuariosSQLite

__all__ = [
    "LibroDeConsumoSQLite",
    "RegistroDeEstadosSQLite",
    "RepositorioCarritosSQLite",
    "RepositorioLlavesSQLite",
    "RepositorioMandatosSQLite",
    "RepositorioMediosSQLite",
    "RepositorioPropuestasSQLite",
    "RepositorioUsuariosSQLite",
]
