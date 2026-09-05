"""Adaptadores de persistencia en memoria: pruebas, y respaldo de demo hasta
la etapa 3 (SQLite). Ver `libro_consumo.py` para las condiciones bajo las que
NO conviene usar este paquete con dinero real.
"""

from __future__ import annotations

from .libro_consumo import LibroDeConsumoEnMemoria
from .registro_estados import RegistroDeEstadosEnMemoria
from .repositorio_carritos import RepositorioCarritosEnMemoria
from .repositorio_llaves import RepositorioLlavesEnMemoria
from .repositorio_mandatos import RepositorioMandatosEnMemoria
from .repositorio_medios import RepositorioMediosEnMemoria
from .repositorio_propuestas import RepositorioPropuestasEnMemoria
from .repositorio_usuarios import RepositorioUsuariosEnMemoria

__all__ = [
    "LibroDeConsumoEnMemoria",
    "RegistroDeEstadosEnMemoria",
    "RepositorioCarritosEnMemoria",
    "RepositorioLlavesEnMemoria",
    "RepositorioMandatosEnMemoria",
    "RepositorioMediosEnMemoria",
    "RepositorioPropuestasEnMemoria",
    "RepositorioUsuariosEnMemoria",
]
