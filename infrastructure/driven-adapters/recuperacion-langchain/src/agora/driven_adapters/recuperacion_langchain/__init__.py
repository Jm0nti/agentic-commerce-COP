"""Buscador documental con LangChain en memoria (migracion a agentes, etapa 2).

Unico lugar de `agora/` que importa LangChain -- `tests/test_fronteras.py`
falla si aparece en cualquier capa que no sea `adaptadores/`.
"""

from __future__ import annotations

from .buscador import BuscadorDocumentalLangChain
from .documentos import cargar_markdown

__all__ = ["BuscadorDocumentalLangChain", "cargar_markdown"]
