"""La regla de dependencia, verificada. No documentada: verificada.

El argumento central de la PoC es que el agente no puede tocar las credenciales
de pago. Si esa separacion depende de que nadie se equivoque escribiendo un
`import`, no es un argumento -- es una promesa.

Esta prueba lee el AST de cada modulo y falla el build cuando alguien cruza una
frontera. Es barata, es exacta, y es lo que convierte una decision de diseno en
una propiedad del sistema.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent / "agora"

# quien -> lo que NO puede importar
REGLAS: dict[str, tuple[str, ...]] = {
    # El nucleo no sabe que existe el mundo exterior.
    "dominio": ("puertos", "aplicacion", "adaptadores", "agente", "entradas", "composicion"),
    "puertos": ("aplicacion", "adaptadores", "agente", "entradas", "composicion"),
    # Los casos de uso hablan con interfaces, nunca con implementaciones.
    "aplicacion": ("adaptadores", "entradas", "composicion"),
    # Un adaptador no orquesta.
    "adaptadores": ("aplicacion", "entradas", "composicion"),
    # LA FRONTERA. El agente no puede alcanzar una credencial de pago
    # ni aunque quiera.
    "agente": ("adaptadores", "composicion"),
    # Las entradas reciben los adaptadores ya armados desde composicion.
    "entradas": ("adaptadores",),
}

# Modulos de terceros que tampoco deberian aparecer segun la capa.
PROHIBIDOS_POR_CAPA: dict[str, tuple[str, ...]] = {
    "dominio": ("httpx", "requests", "fastapi", "sqlite3", "os"),
    "puertos": ("httpx", "requests", "fastapi", "sqlite3"),
    "agente": ("httpx", "sqlite3"),
}


def _modulos() -> list[Path]:
    return [p for p in RAIZ.rglob("*.py") if "__pycache__" not in str(p)]


def _imports(archivo: Path) -> list[str]:
    """Todo lo importado, normalizado. Resuelve los relativos a absolutos."""
    arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
    partes_actuales = archivo.relative_to(RAIZ).parts[:-1]
    fuera: list[str] = []

    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            fuera.extend(a.name for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level:  # relativo: ..puertos.pasarela
                subida = partes_actuales[: len(partes_actuales) - (nodo.level - 1)]
                base = ".".join(subida)
                # Sin base, el `from ..x import y` apunta a la raiz del paquete
                # y el modulo ya es absoluto dentro de agora/. Concatenar un
                # punto delante dejaria el primer segmento vacio y la regla no
                # se aplicaria a nadie.
                if base and nodo.module:
                    fuera.append(f"{base}.{nodo.module}")
                elif nodo.module:
                    fuera.append(nodo.module)
                elif base:
                    fuera.append(base)
            elif nodo.module:
                fuera.append(nodo.module)
    return fuera


def _capa(archivo: Path) -> str:
    return archivo.relative_to(RAIZ).parts[0]


@pytest.mark.parametrize("archivo", _modulos(), ids=lambda p: str(p.name))
def test_regla_de_dependencia(archivo: Path) -> None:
    capa = _capa(archivo)
    prohibidas = REGLAS.get(capa, ())
    for imp in _imports(archivo):
        raiz = imp.split(".")[0]
        # tanto `agora.adaptadores...` como el relativo ya normalizado
        objetivo = imp.split(".")[1] if raiz == "agora" else raiz
        if objetivo in prohibidas:
            pytest.fail(
                f"{archivo.relative_to(RAIZ.parent)} (capa '{capa}') importa "
                f"'{imp}'.\nLa capa '{capa}' no puede depender de '{objetivo}'."
            )


@pytest.mark.parametrize("archivo", _modulos(), ids=lambda p: str(p.name))
def test_capas_puras_sin_infraestructura(archivo: Path) -> None:
    capa = _capa(archivo)
    prohibidos = PROHIBIDOS_POR_CAPA.get(capa, ())
    for imp in _imports(archivo):
        if imp.split(".")[0] in prohibidos:
            pytest.fail(
                f"{archivo.relative_to(RAIZ.parent)} (capa '{capa}') importa "
                f"'{imp}'. Esa capa tiene que poder correr sin red, sin disco y "
                "sin variables de entorno."
            )


def test_el_agente_no_alcanza_ninguna_pasarela() -> None:
    """La frontera de la PoC, dicha una vez mas y sin parametrizar.

    Si esta prueba falla, el experimento deja de medir lo que dice medir: no se
    puede afirmar que el agente opera bajo un mandato si el agente podia cobrar
    por su cuenta.
    """
    ofensas = []
    for archivo in _modulos():
        if _capa(archivo) != "agente":
            continue
        for imp in _imports(archivo):
            if "pasarela" in imp and "puertos" not in imp:
                ofensas.append(f"{archivo.name}: {imp}")
    assert not ofensas, (
        "El agente alcanza una pasarela de pagos:\n  " + "\n  ".join(ofensas)
    )
