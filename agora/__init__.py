"""agora -- PoC de comercio agentico sobre rieles colombianos.

Migracion a la Clean Architecture de Bancolombia
(`evolucion-refactor/roadmap-clean-architecture-bancolombia.md`): cada modulo
del scaffold vive en su propia carpeta (`domain/model`, mas adelante
`domain/usecase`, `infrastructure/...`), con su codigo en `src/agora/`, y todos
aportan subpaquetes a este mismo paquete `agora`. Lo que falta migrar sigue
aca, en `agora/`.
"""

from pathlib import Path as _Path

# Modulos del scaffold ya migrados: cualquier carpeta con `src/agora` en
# `domain/<modulo>` o `infrastructure/<tipo>/<modulo>`, como los genera el
# scaffold (`generateDrivenAdapter`, `generateEntryPoint`).
_PATRONES = ("domain/*/src/agora", "infrastructure/*/*/src/agora")

# ponytail: los modulos se enchufan a `agora.__path__` a mano. Techo: solo
# funciona desde el arbol del repo (o una instalacion editable), no desde un
# wheel. Si alguna vez hace falta empaquetar, pasar a paquetes de espacio de
# nombres (PEP 420) con un pyproject por modulo (Fase 8 del roadmap).
_REPO = _Path(__file__).resolve().parent.parent
__path__ += [str(p) for patron in _PATRONES for p in sorted(_REPO.glob(patron))]
