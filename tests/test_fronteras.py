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
    #
    # `aplicacion` y `entradas` se agregaron en la etapa 1 de la migracion a
    # agentes (16 sep 2026). Hallazgo: el principio documentado ("falla el
    # build si agente/ importa aplicacion/", `herramientas.py:
    # construir_herramientas`) NO estaba en esta tabla -- un modulo de
    # `agente/` con `from ..aplicacion.ejecutar_intencion import
    # EjecutarIntencion` pasaba la suite en verde. Ver
    # `test_el_detector_atrapa_al_agente_importando_un_caso_de_uso`.
    "agente": ("aplicacion", "adaptadores", "entradas", "composicion"),
    # Las entradas reciben los adaptadores ya armados desde composicion.
    "entradas": ("adaptadores",),
}

# Modulos de terceros que tampoco deberian aparecer segun la capa.
PROHIBIDOS_POR_CAPA: dict[str, tuple[str, ...]] = {
    "dominio": ("httpx", "requests", "fastapi", "sqlite3", "os"),
    "puertos": ("httpx", "requests", "fastapi", "sqlite3"),
    # `importlib`: con el se puede importar un adaptador por nombre, en un
    # string, sin que aparezca ningun `import` que este archivo pueda leer.
    "agente": ("httpx", "sqlite3", "importlib"),
}

# Migracion a agentes (docs/arquitectura-agentes-langgraph.md, decision 8):
# LangChain, LangGraph y cualquier SDK de LLM entran SOLO detras de un
# puerto, con su adaptador en `adaptadores/` -- mismo patron que `openai`
# detras de `ModeloDeLenguaje`/`AdaptadorDeepSeek`. Se compara por familia
# (`langchain_core`, `langchain_community`, `langgraph_checkpoint`...), no
# por nombre exacto: el ecosistema reparte cada libreria en muchos paquetes.
LIBRERIAS_DE_LLM = ("langchain", "langgraph", "openai", "anthropic", "llama_index")
CAPAS_QUE_PUEDEN_IMPORTAR_LLM = ("adaptadores",)

# Los archivos que agrego la etapa 1 de la migracion. `_modulos()` ya los
# recorre solo (rglob); esta lista existe para que, si un refactor mueve o
# excluye alguno sin querer, la prueba lo diga en vez de dejar de mirarlo.
MODULOS_DE_LA_MIGRACION_A_AGENTES = (
    # etapa 1
    "agente/intencion.py",
    "agente/nodos.py",
    "agente/clasificacion/__init__.py",
    "agente/clasificacion/cadena.py",
    "agente/clasificacion/modelo.py",
    "agente/clasificacion/reglas.py",
    # etapa 2
    "agente/contexto.py",
    "agente/contexto_documental.py",
    "puertos/recuperacion.py",
    "adaptadores/embeddings/__init__.py",
    "adaptadores/embeddings/proveedor_openai/__init__.py",
    "adaptadores/embeddings/proveedor_openai/adaptador.py",
    "adaptadores/embeddings/proveedor_openai/config.py",
    "adaptadores/recuperacion/__init__.py",
    "adaptadores/recuperacion/langchain_en_memoria/__init__.py",
    "adaptadores/recuperacion/langchain_en_memoria/buscador.py",
    "adaptadores/recuperacion/langchain_en_memoria/documentos.py",
)


def _modulos() -> list[Path]:
    return [p for p in RAIZ.rglob("*.py") if "__pycache__" not in str(p)]


def _imports(archivo: Path, raiz: Path = RAIZ) -> list[str]:
    """Todo lo importado, normalizado. Resuelve los relativos a absolutos.

    `raiz` es parametro solo para que las pruebas del detector (al final
    del archivo) puedan armar un `agora/` de mentira en `tmp_path`."""
    arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
    partes_actuales = archivo.relative_to(raiz).parts[:-1]
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


def _capa(archivo: Path, raiz: Path = RAIZ) -> str:
    return archivo.relative_to(raiz).parts[0]


def _violaciones_de_dependencia(archivo: Path, raiz: Path = RAIZ) -> list[str]:
    capa = _capa(archivo, raiz)
    prohibidas = REGLAS.get(capa, ())
    ofensas = []
    for imp in _imports(archivo, raiz):
        primero = imp.split(".")[0]
        # tanto `agora.adaptadores...` como el relativo ya normalizado
        objetivo = imp.split(".")[1] if primero == "agora" else primero
        if objetivo in prohibidas:
            ofensas.append(
                f"{archivo.relative_to(raiz.parent)} (capa '{capa}') importa "
                f"'{imp}'.\nLa capa '{capa}' no puede depender de '{objetivo}'."
            )
    return ofensas


def _violaciones_de_libreria_de_llm(archivo: Path, raiz: Path = RAIZ) -> list[str]:
    capa = _capa(archivo, raiz)
    if capa in CAPAS_QUE_PUEDEN_IMPORTAR_LLM:
        return []
    ofensas = []
    for imp in _imports(archivo, raiz):
        primero = imp.split(".")[0]
        if any(primero == lib or primero.startswith(f"{lib}_") for lib in LIBRERIAS_DE_LLM):
            ofensas.append(
                f"{archivo.relative_to(raiz.parent)} (capa '{capa}') importa '{imp}'. "
                "Una libreria de LLM/orquestacion entra detras de un puerto, con su "
                "adaptador en adaptadores/ -- nunca directo en esta capa."
            )
    return ofensas


def _importaciones_dinamicas(archivo: Path) -> list[str]:
    """`__import__("agora.adaptadores...")` no deja ningun `import` en el
    AST: es la unica forma de cruzar una frontera que las otras pruebas no
    ven. `importlib` ya esta en `PROHIBIDOS_POR_CAPA`; esto cubre el
    builtin."""
    arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
    return [
        f"{archivo.name}:{nodo.lineno}"
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call)
        and isinstance(nodo.func, ast.Name)
        and nodo.func.id == "__import__"
    ]


@pytest.mark.parametrize("archivo", _modulos(), ids=lambda p: str(p.name))
def test_regla_de_dependencia(archivo: Path) -> None:
    ofensas = _violaciones_de_dependencia(archivo)
    if ofensas:
        pytest.fail("\n".join(ofensas))


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


# --------------------------------------------------------------------------- #
# Migracion a agentes, etapa 1
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("archivo", _modulos(), ids=lambda p: str(p.name))
def test_librerias_de_llm_solo_detras_de_un_adaptador(archivo: Path) -> None:
    ofensas = _violaciones_de_libreria_de_llm(archivo)
    if ofensas:
        pytest.fail("\n".join(ofensas))


def test_el_agente_no_importa_nada_por_nombre_en_un_string() -> None:
    ofensas = [
        ofensa
        for archivo in _modulos()
        if _capa(archivo) == "agente"
        for ofensa in _importaciones_dinamicas(archivo)
    ]
    assert not ofensas, "El agente usa __import__ dinamico:\n  " + "\n  ".join(ofensas)


@pytest.mark.parametrize("relativo", MODULOS_DE_LA_MIGRACION_A_AGENTES)
def test_los_modulos_de_la_migracion_estan_bajo_las_reglas_de_su_capa(relativo: str) -> None:
    archivo = RAIZ / relativo
    assert archivo in _modulos(), f"{relativo} no existe o quedo fuera de _modulos()"
    assert _capa(archivo) == relativo.split("/")[0]


# -- etapa 2: recuperacion documental ----------------------------------------- #


def _es_modulo(importado: str, prefijo: str) -> bool:
    """`adaptadores.x...` o `agora.adaptadores.x...` -- no `langchain_core.x`."""
    sin_raiz = importado[len("agora."):] if importado.startswith("agora.") else importado
    return sin_raiz == prefijo or sin_raiz.startswith(prefijo + ".")


def _modulos_bajo(prefijo: str) -> list[Path]:
    return [p for p in _modulos() if p.relative_to(RAIZ).as_posix().startswith(prefijo)]


def test_el_indice_documental_nunca_se_mezcla_con_el_catalogo() -> None:
    """Decision 1 del documento: el indice de soporte es "un indice separado
    (nunca mezclado con el catalogo)". Dicho en imports: la recuperacion
    documental no alcanza nada del catalogo, y el catalogo no alcanza nada
    de la recuperacion documental."""
    ofensas = []
    for archivo in _modulos_bajo("adaptadores/recuperacion/") + _modulos_bajo("adaptadores/embeddings/"):
        ofensas += [f"{archivo.name}: {i}" for i in _imports(archivo) if "catalogo" in i.split(".")]
    for archivo in _modulos_bajo("adaptadores/catalogo/") + [RAIZ / "puertos" / "catalogo.py"]:
        ofensas += [
            f"{archivo.name}: {i}"
            for i in _imports(archivo)
            if {"recuperacion", "embeddings"} & set(i.split("."))
        ]
    assert not ofensas, "Catalogo y documentacion se cruzan:\n  " + "\n  ".join(ofensas)


def test_embeddings_y_vector_store_solo_se_conocen_por_el_puerto() -> None:
    """El adaptador de OpenAI no sabe que existe LangChain, y el buscador de
    LangChain no sabe que existe OpenAI: cambiar uno no toca al otro
    (decision 2 del documento, "embeddings detras de su propio puerto")."""
    ofensas = []
    for archivo in _modulos_bajo("adaptadores/embeddings/"):
        ofensas += [
            f"{archivo.name}: {i}" for i in _imports(archivo)
            if i.split(".")[0].startswith("langchain") or _es_modulo(i, "adaptadores.recuperacion")
        ]
    for archivo in _modulos_bajo("adaptadores/recuperacion/"):
        ofensas += [
            f"{archivo.name}: {i}" for i in _imports(archivo)
            if i.split(".")[0] == "openai" or _es_modulo(i, "adaptadores.embeddings")
        ]
    assert not ofensas, "Adaptadores de la etapa 2 acoplados:\n  " + "\n  ".join(ofensas)


# -- el detector, probado ---------------------------------------------------- #
# Una prueba de fronteras que nunca falla puede estar bien... o no estar
# mirando nada. Estas arman un `agora/` de mentira con violaciones conocidas
# y exigen que el detector las encuentre.


def _agora_de_mentira(tmp_path: Path, relativo: str, contenido: str) -> tuple[Path, Path]:
    raiz = tmp_path / "agora"
    archivo = raiz / relativo
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(contenido, encoding="utf-8")
    return raiz, archivo


def test_el_detector_atrapa_al_agente_importando_un_caso_de_uso(tmp_path: Path) -> None:
    raiz, archivo = _agora_de_mentira(
        tmp_path,
        "agente/clasificacion/intruso.py",
        "from ...aplicacion.ejecutar_intencion import EjecutarIntencion\n",
    )
    ofensas = _violaciones_de_dependencia(archivo, raiz)
    assert ofensas and "aplicacion" in ofensas[0]


def test_el_detector_atrapa_al_agente_importando_entradas(tmp_path: Path) -> None:
    raiz, archivo = _agora_de_mentira(
        tmp_path, "agente/intruso.py", "from agora.entradas.api.app import crear_app\n",
    )
    assert _violaciones_de_dependencia(archivo, raiz)


@pytest.mark.parametrize(
    "linea",
    [
        "from langgraph.graph import StateGraph",
        "from langchain_core.messages import HumanMessage",
        "import langchain_community.vectorstores",
        "from openai import OpenAI",
    ],
)
@pytest.mark.parametrize("capa", ["dominio", "puertos", "aplicacion", "agente", "entradas"])
def test_el_detector_atrapa_librerias_de_llm_fuera_de_adaptadores(
    tmp_path: Path, capa: str, linea: str
) -> None:
    raiz, archivo = _agora_de_mentira(tmp_path, f"{capa}/intruso.py", linea + "\n")
    assert _violaciones_de_libreria_de_llm(archivo, raiz)


def test_el_detector_deja_pasar_librerias_de_llm_en_adaptadores(tmp_path: Path) -> None:
    raiz, archivo = _agora_de_mentira(
        tmp_path, "adaptadores/orquestacion/grafo.py", "from langgraph.graph import StateGraph\n",
    )
    assert _violaciones_de_libreria_de_llm(archivo, raiz) == []


def test_el_detector_atrapa_importaciones_dinamicas(tmp_path: Path) -> None:
    _, archivo = _agora_de_mentira(
        tmp_path, "agente/intruso.py", 'p = __import__("agora.adaptadores.pasarelas.wompi")\n',
    )
    assert _importaciones_dinamicas(archivo)
