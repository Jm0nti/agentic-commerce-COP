"""Adaptadores de persistencia en memoria: pruebas, y respaldo de demo hasta
la etapa 3 (SQLite). Ver `libro_consumo.py` para las condiciones bajo las que
NO conviene usar este paquete con dinero real.
"""

from __future__ import annotations

from .libro_consumo import LibroDeConsumoEnMemoria
from .repositorio_mandatos import RepositorioMandatosEnMemoria
from .repositorio_medios import RepositorioMediosEnMemoria

__all__ = [
    "LibroDeConsumoEnMemoria",
    "RepositorioMandatosEnMemoria",
    "RepositorioMediosEnMemoria",
]
