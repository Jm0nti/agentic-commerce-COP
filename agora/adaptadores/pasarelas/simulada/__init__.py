"""La pasarela simulada: adaptador de produccion para el modo demo (ADR-2)."""

from __future__ import annotations

from .adaptador import AdaptadorSimulado
from .guion import (
    APROBADO,
    DECLINADO,
    DECLINADO_ANTIFRAUDE,
    PENDIENTE,
    Desenlace,
    GuionSimulado,
    heuristica_por_defecto,
)

__all__ = [
    "AdaptadorSimulado",
    "GuionSimulado",
    "Desenlace",
    "heuristica_por_defecto",
    "APROBADO",
    "DECLINADO",
    "DECLINADO_ANTIFRAUDE",
    "PENDIENTE",
]
