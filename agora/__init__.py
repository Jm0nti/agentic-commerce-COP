"""agora -- PoC de comercio agentico sobre rieles colombianos.

Migracion a la Clean Architecture de Bancolombia
(`evolucion-refactor/roadmap-clean-architecture-bancolombia.md`): cada modulo
del scaffold vive en su propia carpeta (`domain/model`, mas adelante
`domain/usecase`, `infrastructure/...`), con su codigo en `src/agora/`, y todos
aportan subpaquetes a este mismo paquete `agora`. Lo que falta migrar sigue
aca, en `agora/`.
"""

from pathlib import Path as _Path

# Modulos del scaffold ya migrados. Cada fase agrega el suyo.
_MODULOS = ("domain/model", "domain/usecase")

# ponytail: los modulos se enchufan a `agora.__path__` a mano. Techo: solo
# funciona desde el arbol del repo (o una instalacion editable), no desde un
# wheel. Si alguna vez hace falta empaquetar, pasar a paquetes de espacio de
# nombres (PEP 420) con un pyproject por modulo (Fase 8 del roadmap).
_REPO = _Path(__file__).resolve().parent.parent
__path__ += [str(_REPO / m / "src" / "agora") for m in _MODULOS]
