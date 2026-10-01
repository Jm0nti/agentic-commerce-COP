"""agora -- PoC de comercio agentico sobre rieles colombianos.

Este paquete vive en `applications/app-service` (Clean Architecture de
Bancolombia, `evolucion-refactor/roadmap-clean-architecture-bancolombia.md`):
el modulo mas externo, el unico que conoce a todos los demas. Cada modulo del
scaffold (`domain/<modulo>`, `infrastructure/<tipo>/<modulo>`) tiene su codigo
en `src/agora/` y aporta subpaquetes a este mismo paquete `agora`.

Arranque: `python -m agora <perfil>` (ver `app_service/main.py`).
"""

from pathlib import Path as _Path

# Los modulos del scaffold, encontrados como los genera el scaffold
# (`generateDrivenAdapter`, `generateEntryPoint`): no hay lista que mantener.
_PATRONES = ("domain/*/src/agora", "infrastructure/*/*/src/agora", "applications/*/src/agora")

# ponytail: los modulos se enchufan a `agora.__path__` a mano. Techo: solo
# funciona desde el arbol del repo (o una instalacion editable), no desde un
# wheel. Si alguna vez hace falta empaquetar, pasar a paquetes de espacio de
# nombres (PEP 420) con un pyproject por modulo (Fase 8 del roadmap).
_AQUI = _Path(__file__).resolve().parent
_REPO = next(p for p in _AQUI.parents if (p / "pyproject.toml").is_file())
__path__ += [
    str(p) for patron in _PATRONES for p in sorted(_REPO.glob(patron)) if p.resolve() != _AQUI
]
