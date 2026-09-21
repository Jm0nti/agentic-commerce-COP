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
    # etapa 3
    "agente/grafo.py",
    "puertos/orquestacion.py",
    "adaptadores/orquestacion/__init__.py",
    "adaptadores/orquestacion/con_langgraph/__init__.py",
    "adaptadores/orquestacion/con_langgraph/compilador.py",
    # etapa 4
    "agente/agentes.py",
    "puertos/busqueda_productos.py",
    "adaptadores/busqueda_productos/__init__.py",
    "adaptadores/busqueda_productos/semantico_en_memoria/__init__.py",
    "adaptadores/busqueda_productos/semantico_en_memoria/buscador.py",
    # trazabilidad del agente
    "agente/traza.py",
    # etapa 5
    "agente/pausa.py",
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


# -- etapa 3: el grafo de orquestacion ---------------------------------------- #


def test_langgraph_vive_en_un_solo_modulo_de_agora() -> None:
    """La promesa de la etapa 3, medida sobre el codigo real: cambiar de
    motor de grafos toca UN archivo. `test_librerias_de_llm_solo_detras_de_un
    _adaptador` ya prohibe langgraph fuera de `adaptadores/`; esto ademas
    exige que dentro de `adaptadores/` tampoco se desparrame."""
    con_langgraph = sorted(
        archivo.relative_to(RAIZ).as_posix()
        for archivo in _modulos()
        if any(i.split(".")[0] == "langgraph" for i in _imports(archivo))
    )

    assert con_langgraph == ["adaptadores/orquestacion/con_langgraph/compilador.py"]


def test_el_puerto_de_orquestacion_no_conoce_ninguna_libreria_de_grafos() -> None:
    """Si el puerto importara langgraph, no seria un puerto: seria un alias.
    Lo unico que puede importar es la biblioteca estandar."""
    ofensas = [
        i
        for i in _imports(RAIZ / "puertos" / "orquestacion.py")
        if i.split(".")[0] not in ("dataclasses", "typing", "__future__")
    ]

    assert not ofensas, "puertos/orquestacion.py importa de mas:\n  " + "\n  ".join(ofensas)


def test_el_grafo_del_agente_solo_conoce_el_puerto() -> None:
    """`agente/grafo.py` arma la topologia del turno sin saber quien la
    compila: recibe el `CompiladorDeGrafos` por constructor."""
    importados = _imports(RAIZ / "agente" / "grafo.py")

    assert any(_es_modulo(i, "puertos.orquestacion") for i in importados)
    assert not [i for i in importados if i.split(".")[0] == "langgraph"]
    assert not [i for i in importados if _es_modulo(i, "adaptadores")]


# -- etapa 4: agentes especializados y retrieval hibrido ---------------------- #


def test_el_indice_de_productos_no_alcanza_el_repositorio_del_catalogo() -> None:
    """Decision 1: el buscador semantico ordena candidatos, no los busca. Si
    importara `RepositorioCatalogo` o su adaptador podria ir a buscar
    productos por su cuenta -- y entonces una regla dura (disponibilidad,
    precio) dejaria de ser el unico camino hacia un producto."""
    ofensas = []
    for archivo in _modulos_bajo("adaptadores/busqueda_productos/"):
        ofensas += [
            f"{archivo.name}: {i}"
            for i in _imports(archivo)
            if _es_modulo(i, "adaptadores.catalogo") or _es_modulo(i, "puertos.catalogo")
        ]
    assert not ofensas, (
        "el buscador semantico de productos alcanza el catalogo:\n  " + "\n  ".join(ofensas)
    )


def test_el_indice_de_productos_y_el_documental_no_se_conocen() -> None:
    """Dos indices que nunca se mezclan (decision 1). Lo unico que comparten
    es `puertos/recuperacion.py:ProveedorDeEmbeddings`, que es el puerto de
    "texto -> vector" de la decision 2 y no sabe que se esta indexando."""
    ofensas = []
    for archivo in _modulos_bajo("adaptadores/busqueda_productos/"):
        ofensas += [
            f"{archivo.name}: {i}"
            for i in _imports(archivo)
            if _es_modulo(i, "adaptadores.recuperacion") or _es_modulo(i, "adaptadores.embeddings")
        ]
    for archivo in _modulos_bajo("adaptadores/recuperacion/"):
        ofensas += [
            f"{archivo.name}: {i}"
            for i in _imports(archivo)
            if _es_modulo(i, "adaptadores.busqueda_productos")
            or _es_modulo(i, "puertos.busqueda_productos")
        ]
    assert not ofensas, "los dos indices se cruzan:\n  " + "\n  ".join(ofensas)


def test_el_puerto_de_busqueda_de_productos_no_conoce_ninguna_libreria() -> None:
    """Las reglas duras (`FiltrosDeProducto`) viven de este lado de la
    frontera, sobre objetos de dominio: nada de numpy ni de vector stores."""
    ofensas = [
        i
        for i in _imports(RAIZ / "puertos" / "busqueda_productos.py")
        if i.split(".")[0] not in ("dataclasses", "typing", "__future__")
        and not _es_modulo(i, "dominio.catalogo.modelo")
    ]

    assert not ofensas, (
        "puertos/busqueda_productos.py importa de mas:\n  " + "\n  ".join(ofensas)
    )


def test_los_agentes_especializados_no_alcanzan_ninguna_pasarela() -> None:
    """`agente/agentes.py` decide que herramientas ve cada agente: es
    exactamente el modulo donde un import de mas seria peor."""
    ofensas = [
        i for i in _imports(RAIZ / "agente" / "agentes.py")
        if "pasarela" in i or _es_modulo(i, "aplicacion") or _es_modulo(i, "adaptadores")
    ]

    assert not ofensas, "agente/agentes.py cruza una frontera:\n  " + "\n  ".join(ofensas)


# -- trazabilidad ------------------------------------------------------------- #


def test_la_traza_no_conoce_ningun_adaptador_de_bitacora() -> None:
    """`agente/traza.py` arma el cuerpo; quien lo escribe es un `Bitacora`
    que llega por constructor. Si conociera el adaptador de .jsonl, cambiar
    el destino de las trazas (a stdout, a otro formato) obligaria a tocar el
    agente."""
    ofensas = [
        i for i in _imports(RAIZ / "agente" / "traza.py")
        if _es_modulo(i, "adaptadores") or _es_modulo(i, "composicion")
    ]

    assert not ofensas, "agente/traza.py conoce un adaptador:\n  " + "\n  ".join(ofensas)


# -- etapa 5: la pausa humana -------------------------------------------------- #


def test_la_pausa_no_alcanza_ningun_caso_de_uso_ni_pasarela() -> None:
    """`agente/pausa.py` describe QUE hay que decidir y arma el texto que lee
    el modelo. Quien firma y quien cobra siguen siendo `aplicacion/`, por
    pedido de una persona desde `entradas/`. Si este modulo pudiera importar
    `EmitirMandato`, el agente estaria a un import de firmar solo."""
    ofensas = [
        i for i in _imports(RAIZ / "agente" / "pausa.py")
        if _es_modulo(i, "aplicacion") or _es_modulo(i, "adaptadores") or "pasarela" in i
    ]

    assert not ofensas, "agente/pausa.py cruza una frontera:\n  " + "\n  ".join(ofensas)


def test_el_puerto_de_orquestacion_define_la_pausa_sin_conocer_el_motor() -> None:
    """Detener el grafo no necesita nada del motor: `PausaRequerida` es una
    excepcion del puerto, no el `interrupt()` de ninguna libreria."""
    fuente = (RAIZ / "puertos" / "orquestacion.py").read_text(encoding="utf-8")

    assert "class PausaRequerida" in fuente
    assert "interrupt" not in fuente.replace("`interrupt()`", "")


def test_solo_agente_pausa_arma_el_aviso_que_lee_el_modelo() -> None:
    """La queja concreta de la decision 6: antes habia cuatro sitios
    escribiendo ese texto a mano. Las frases que el modelo distingue viven
    ahora en un solo archivo."""
    marcas = ("Continua el flujo de compra llamando a", "no hay mandato ni pago")
    culpables = [
        p.relative_to(RAIZ).as_posix()
        for p in _modulos()
        for marca in marcas
        if marca in p.read_text(encoding="utf-8")
    ]

    assert set(culpables) == {"agente/pausa.py"}, (
        "el aviso se arma en mas de un lugar:\n  " + "\n  ".join(sorted(set(culpables)))
    )


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


def test_el_detector_atrapa_al_puerto_de_orquestacion_importando_langgraph(
    tmp_path: Path,
) -> None:
    """El acople de la etapa 3, puesto a proposito: el puerto que existe
    para aislar LangGraph, importando LangGraph."""
    raiz, archivo = _agora_de_mentira(
        tmp_path, "puertos/orquestacion.py", "from langgraph.graph import StateGraph\n",
    )
    assert _violaciones_de_libreria_de_llm(archivo, raiz)


def test_el_detector_atrapa_al_grafo_del_agente_importando_su_adaptador(
    tmp_path: Path,
) -> None:
    """El otro acople de la etapa 3: `agente/grafo.py` importando el
    compilador concreto en vez de recibirlo por constructor. No lo atrapa la
    regla de librerias (el import no nombra a langgraph), lo atrapa la regla
    de dependencia."""
    raiz, archivo = _agora_de_mentira(
        tmp_path,
        "agente/grafo.py",
        "from ..adaptadores.orquestacion.con_langgraph import CompiladorLangGraph\n",
    )
    ofensas = _violaciones_de_dependencia(archivo, raiz)
    assert ofensas and "adaptadores" in ofensas[0]


def test_el_detector_atrapa_al_buscador_de_productos_yendo_al_catalogo(
    tmp_path: Path,
) -> None:
    """El acople de la etapa 4: el buscador semantico importando el
    repositorio del catalogo para ir a buscar productos por su cuenta, en vez
    de recibir los candidatos ya filtrados."""
    raiz, _ = _agora_de_mentira(
        tmp_path,
        "adaptadores/busqueda_productos/semantico_en_memoria/intruso.py",
        "from ....puertos.catalogo import RepositorioCatalogo\n",
    )
    archivo = raiz / "adaptadores/busqueda_productos/semantico_en_memoria/intruso.py"
    ofensas = [
        i for i in _imports(archivo, raiz)
        if _es_modulo(i, "adaptadores.catalogo") or _es_modulo(i, "puertos.catalogo")
    ]
    assert ofensas


def test_el_detector_atrapa_al_puerto_de_productos_importando_numpy(
    tmp_path: Path,
) -> None:
    raiz, _ = _agora_de_mentira(
        tmp_path, "puertos/busqueda_productos.py", "import numpy as np\n",
    )
    archivo = raiz / "puertos/busqueda_productos.py"
    ofensas = [
        i for i in _imports(archivo, raiz)
        if i.split(".")[0] not in ("dataclasses", "typing", "__future__")
        and not _es_modulo(i, "dominio.catalogo.modelo")
    ]
    assert ofensas


def test_el_detector_atrapa_a_los_agentes_importando_un_caso_de_uso(
    tmp_path: Path,
) -> None:
    raiz, archivo = _agora_de_mentira(
        tmp_path,
        "agente/agentes.py",
        "from ..aplicacion.navegar_catalogo import NavegarCatalogo\n",
    )
    ofensas = _violaciones_de_dependencia(archivo, raiz)
    assert ofensas and "aplicacion" in ofensas[0]


def test_el_detector_atrapa_importaciones_dinamicas(tmp_path: Path) -> None:
    _, archivo = _agora_de_mentira(
        tmp_path, "agente/intruso.py", 'p = __import__("agora.adaptadores.pasarelas.wompi")\n',
    )
    assert _importaciones_dinamicas(archivo)
