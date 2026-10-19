"""Clasificadores de intencion (migracion a agentes, etapa 1).

Tres piezas intercambiables detras de `agente.intencion.
ClasificadorDeIntencion`:

    ClasificadorPorReglas   deterministico, gratis, se abstiene si hay duda
    ClasificadorConModelo   usa `ModeloDeLenguaje.generar`, lee historial
    ClasificadorEnCadena    el primero que decide, gana

Ninguno importa `usecase/`, `driven_adapters/` ni una libreria de LLM: son
parte del agente, y `tests/arquitectura/test_fronteras.py` lo verifica igual que para el
resto de `usecase/agente/`.
"""

from __future__ import annotations

from .cadena import ClasificadorEnCadena
from .modelo import ClasificadorConModelo
from .reglas import ClasificadorPorReglas

__all__ = ["ClasificadorConModelo", "ClasificadorEnCadena", "ClasificadorPorReglas"]
