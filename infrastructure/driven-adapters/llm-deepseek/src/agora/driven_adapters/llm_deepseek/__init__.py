"""El adaptador de modelo de lenguaje para fabricar catalogo simulado."""

from __future__ import annotations

from .adaptador import AdaptadorDeepSeek
from .config import ConfiguracionDeepSeek, ConfiguracionInvalida

__all__ = [
    "AdaptadorDeepSeek",
    "ConfiguracionDeepSeek",
    "ConfiguracionInvalida",
]
