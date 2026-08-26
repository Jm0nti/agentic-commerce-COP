"""Carga simple de variables desde un archivo .env.

No pisa variables ya exportadas por la sesion actual, salvo que se pida
explicitamente con `override=True`.
"""

from __future__ import annotations

import os
from pathlib import Path


def cargar_env_desde_archivo(ruta: Path, override: bool = False) -> int:
    """Carga un archivo tipo .env y devuelve cuantas variables agrego/actualizo."""
    if not ruta.exists():
        return 0

    cargadas = 0
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue

        clave, _, valor = linea.partition("=")
        clave = clave.strip()
        valor = valor.split(" #")[0].strip().strip("\"'")
        if not clave:
            continue

        if override or clave not in os.environ:
            os.environ[clave] = valor
            cargadas += 1

    return cargadas
