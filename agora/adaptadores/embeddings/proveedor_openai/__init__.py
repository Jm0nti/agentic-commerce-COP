"""Embeddings de OpenAI detras de `puertos.recuperacion.ProveedorDeEmbeddings`."""

from __future__ import annotations

from .adaptador import AdaptadorEmbeddingsOpenAI
from .config import ConfiguracionEmbeddingsOpenAI, ConfiguracionInvalida

__all__ = [
    "AdaptadorEmbeddingsOpenAI",
    "ConfiguracionEmbeddingsOpenAI",
    "ConfiguracionInvalida",
]
