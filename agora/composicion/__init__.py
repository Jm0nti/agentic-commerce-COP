"""El composition root. Ver `contenedor.py` y `configuracion.py`."""

from __future__ import annotations

from .configuracion import ConfiguracionAgora, ConfiguracionInvalida, leer_configuracion
from .contenedor import Contenedor, construir

__all__ = [
    "ConfiguracionAgora",
    "ConfiguracionInvalida",
    "leer_configuracion",
    "Contenedor",
    "construir",
]
