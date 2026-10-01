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
import functools
import sys
from pathlib import Path

import pytest

import agora

# Las raices de `agora` en disco: `agora/` y cada modulo del scaffold ya
# migrado (`domain/model/src/agora`, ...) -- ver `agora/__init__.py`. Las
# rutas de esta prueba son relativas a su raiz ("model/pago/modelo.py"), asi
# que no importa en que carpeta del scaffold viva cada modulo.
RAICES: tuple[Path, ...] = tuple(Path(p).resolve() for p in agora.__path__)

# Ruta (posix, relativa a agora/) -> capa. La capa de un archivo, y la de un
# import, sale de esta tabla por el prefijo MAS LARGO que coincida -- no del
# primer segmento de la ruta. Cuando el refactor a la Clean Architecture de
# Bancolombia mueva carpetas (evolucion-refactor/, Fase 2 en adelante), lo
# que cambia es esta tabla; y un archivo que no aparezca aca hace fallar
# `test_todo_modulo_tiene_capa` en vez de quedar sin reglas.
CAPAS: dict[str, str] = {
    "__init__.py": "raiz",
    # Fase 2: `dominio/` y `puertos/` se fusionaron en `domain/model`.
    "model": "model",
    # Fase 3: los casos de uso viven en `domain/usecase`. El agente tambien,
    # pero con capa propia: su regla es mas estricta (no importa ningun otro
    # caso de uso), asi que gana el prefijo mas largo.
    "usecase": "usecase",
    "usecase/agente": "agente",
    "adaptadores": "adaptadores",
    "entradas": "entradas",
    "composicion": "composicion",
}

# Contra el falso verde: si un movimiento deja una capa vacia, todas sus
# reglas pasan sin mirar nada. Minimos = conteo del 30 sep 2026. Bajar uno
# tiene que ser una decision, no un accidente.
MINIMO_DE_MODULOS_POR_CAPA: dict[str, int] = {
    "model": 26,
    "usecase": 18,
    "agente": 14,
    "adaptadores": 61,
    "entradas": 10,
    "composicion": 4,
}

# quien -> lo que NO puede importar
REGLAS: dict[str, tuple[str, ...]] = {
    # El nucleo no sabe que existe el mundo exterior.
    # Entidades y gateways juntos, como en el scaffold de Bancolombia.
    "model": ("usecase", "adaptadores", "agente", "entradas", "composicion"),
    # Los casos de uso hablan con interfaces, nunca con implementaciones.
    # `agente` se agrego en la Fase 3: un caso de uso no depende del agente.
    "usecase": ("adaptadores", "entradas", "composicion", "agente"),
    # Un adaptador no orquesta.
    "adaptadores": ("usecase", "entradas", "composicion"),
    # LA FRONTERA. El agente no puede alcanzar una credencial de pago
    # ni aunque quiera.
    #
    # `aplicacion` y `entradas` se agregaron en la etapa 1 de la migracion a
    # agentes (16 sep 2026). Hallazgo: el principio documentado ("falla el
    # build si agente/ importa aplicacion/", `herramientas.py:
    # construir_herramientas`) NO estaba en esta tabla -- un modulo de
    # `agente/` con `from ..aplicacion.ejecutar_intencion import
    # EjecutarIntencionUseCase` pasaba la suite en verde. Ver
    # `test_el_detector_atrapa_al_agente_importando_un_caso_de_uso`.
    "agente": ("usecase", "adaptadores", "entradas", "composicion"),
    # Las entradas reciben los adaptadores ya armados desde composicion.
    # `composicion` se agrego en la Fase 1 del refactor a la Clean
    # Architecture de Bancolombia: un entry point recibe casos de uso, no
    # sabe quien los arma.
    "entradas": ("adaptadores", "composicion"),
}

# Archivo -> capas que TODAVIA puede importar aunque REGLAS lo prohiba. Cada
# entrada es deuda con fecha de vencimiento, no una excepcion de diseno.
EXCEPCIONES_PROVISORIAS: dict[str, tuple[str, ...]] = {
    # La CLI arma su propio contenedor (es composition root) hasta que la
    # Fase 5 mueva el arranque a `app-service`.
    "entradas/cli/__main__.py": ("composicion",),
}

# Atributos del `Contenedor` que son repositorios o adaptadores crudos. Un
# entry point no los toca (Fase 1): lo que necesite leer, lo pide a un caso de
# uso. Se mira el AST, no los imports: el `Contenedor` llega por parametro y
# `contenedor.carritos.obtener(...)` no deja ningun import que revisar.
REPOSITORIOS_DEL_CONTENEDOR = frozenset({
    "mandatos", "medios", "consumo", "carritos", "propuestas", "estados",
    "usuarios", "llaves", "ids", "catalogo", "selector_pasarela",
    "selector_firmante", "verificador", "bitacora", "bitacora_trazas",
})

# Modulos de terceros que tampoco deberian aparecer segun la capa.
PROHIBIDOS_POR_CAPA: dict[str, tuple[str, ...]] = {
    "model": ("httpx", "requests", "fastapi", "sqlite3", "os"),
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
    "model/agente/intencion.py",
    "usecase/agente/nodos.py",
    "usecase/agente/clasificacion/__init__.py",
    "usecase/agente/clasificacion/cadena.py",
    "usecase/agente/clasificacion/modelo.py",
    "usecase/agente/clasificacion/reglas.py",
    # etapa 2
    "model/agente/contexto.py",
    "usecase/agente/contexto_documental.py",
    "model/agente/gateways/recuperacion.py",
    "adaptadores/embeddings/__init__.py",
    "adaptadores/embeddings/proveedor_openai/__init__.py",
    "adaptadores/embeddings/proveedor_openai/adaptador.py",
    "adaptadores/embeddings/proveedor_openai/config.py",
    "adaptadores/recuperacion/__init__.py",
    "adaptadores/recuperacion/langchain_en_memoria/__init__.py",
    "adaptadores/recuperacion/langchain_en_memoria/buscador.py",
    "adaptadores/recuperacion/langchain_en_memoria/documentos.py",
    # etapa 3
    "usecase/agente/grafo.py",
    "model/agente/gateways/orquestacion.py",
    "adaptadores/orquestacion/__init__.py",
    "adaptadores/orquestacion/con_langgraph/__init__.py",
    "adaptadores/orquestacion/con_langgraph/compilador.py",
    # etapa 4
    "usecase/agente/agentes.py",
    "model/catalogo/gateways/busqueda_productos.py",
    "adaptadores/busqueda_productos/__init__.py",
    "adaptadores/busqueda_productos/semantico_en_memoria/__init__.py",
    "adaptadores/busqueda_productos/semantico_en_memoria/buscador.py",
    # trazabilidad del agente
    "usecase/agente/traza.py",
    # etapa 5
    "usecase/agente/pausa.py",
)


def _raiz_de(archivo: Path) -> Path:
    return next(r for r in RAICES if archivo.is_relative_to(r))


def _rel(archivo: Path, raiz: Path | None = None) -> str:
    """'model/pago/modelo.py': relativo a la raiz de `agora` que lo contiene."""
    return archivo.relative_to(raiz or _raiz_de(archivo)).as_posix()


def _archivo(relativo: str) -> Path:
    candidatos = [r / relativo for r in RAICES if (r / relativo).is_file()]
    assert candidatos, f"{relativo} no existe en ninguna raiz de agora: si se movio, actualizar la regla"
    return candidatos[0]


@functools.cache
def _modulos() -> tuple[Path, ...]:
    return tuple(p for r in RAICES for p in r.rglob("*.py") if "__pycache__" not in p.parts)


@functools.cache
def _imports(archivo: Path, raiz: Path | None = None) -> list[str]:
    """Todo lo importado, normalizado. Resuelve los relativos a absolutos.

    `raiz` es parametro solo para que las pruebas del detector (al final
    del archivo) puedan armar un `agora/` de mentira en `tmp_path`."""
    arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
    partes_actuales = tuple(_rel(archivo, raiz).split("/"))[:-1]
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


def _capa_de(ruta: str) -> str | None:
    """Capa de un archivo ('agente/grafo.py') o de un modulo importado
    ('agora.agente.grafo' o el relativo ya normalizado 'agente.grafo').
    `None` para lo que no es de agora/ (terceros, stdlib)."""
    if not ruta.endswith(".py"):
        ruta = ruta.removeprefix("agora.").replace(".", "/")
    coinciden = [p for p in CAPAS if ruta == p or ruta.startswith(p + "/")]
    return CAPAS[max(coinciden, key=len)] if coinciden else None


def _capa(archivo: Path, raiz: Path | None = None) -> str | None:
    return _capa_de(_rel(archivo, raiz))


def _violaciones_de_dependencia(archivo: Path, raiz: Path | None = None) -> list[str]:
    capa = _capa(archivo, raiz)
    permitidas = EXCEPCIONES_PROVISORIAS.get(_rel(archivo, raiz), ())
    prohibidas = tuple(c for c in REGLAS.get(capa, ()) if c not in permitidas)
    ofensas = []
    for imp in _imports(archivo, raiz):
        objetivo = _capa_de(imp)
        if objetivo in prohibidas:
            ofensas.append(
                f"{_rel(archivo, raiz)} (capa '{capa}') importa "
                f"'{imp}'.\nLa capa '{capa}' no puede depender de '{objetivo}'."
            )
    return ofensas


def _violaciones_de_libreria_de_llm(archivo: Path, raiz: Path | None = None) -> list[str]:
    capa = _capa(archivo, raiz)
    if capa in CAPAS_QUE_PUEDEN_IMPORTAR_LLM:
        return []
    ofensas = []
    for imp in _imports(archivo, raiz):
        primero = imp.split(".")[0]
        if any(primero == lib or primero.startswith(f"{lib}_") for lib in LIBRERIAS_DE_LLM):
            ofensas.append(
                f"{_rel(archivo, raiz)} (capa '{capa}') importa '{imp}'. "
                "Una libreria de LLM/orquestacion entra detras de un puerto, con su "
                "adaptador en adaptadores/ -- nunca directo en esta capa."
            )
    return ofensas


def _accesos_a_repositorios(archivo: Path) -> list[str]:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
    return [
        f"{archivo.name}:{nodo.lineno} .{nodo.attr}"
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Attribute) and nodo.attr in REPOSITORIOS_DEL_CONTENEDOR
    ]


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
                f"{_rel(archivo)} (capa '{capa}') importa "
                f"'{imp}'. Esa capa tiene que poder correr sin red, sin disco y "
                "sin variables de entorno."
            )


# Lo que el agente no puede tocar ni como interfaz: los casos de uso, los
# adaptadores, y los puertos de pasarela, firma, repositorios (llaves, medios
# de pago) y autenticacion. Antes se miraba si el import contenia la palabra
# "pasarela" y no "puertos" -- una regla que un renombre de carpeta apaga sin
# que ninguna prueba se entere.
REPOSITORIOS_DEL_MODELO = (
    "model.mandato.gateways.repositorios",
    "model.pago.gateways.repositorios",
    "model.catalogo.gateways.repositorios",
    "model.usuario.gateways.repositorios",
)
PUERTOS_VEDADOS_AL_AGENTE = (
    "model.pago.gateways.pasarela",
    "model.mandato.gateways.firma",
    "model.usuario.gateways.autenticacion",
    *REPOSITORIOS_DEL_MODELO,
)


def _alcanza_pagos(importado: str) -> bool:
    return _capa_de(importado) in ("usecase", "adaptadores") or any(
        _es_modulo(importado, p) for p in PUERTOS_VEDADOS_AL_AGENTE
    )


def test_todo_modulo_tiene_capa() -> None:
    sin_capa = [_rel(p) for p in _modulos() if _capa(p) is None]
    assert not sin_capa, "archivos fuera de CAPAS, sin ninguna regla:\n  " + "\n  ".join(sin_capa)


@pytest.mark.parametrize("capa", sorted(MINIMO_DE_MODULOS_POR_CAPA))
def test_ninguna_capa_queda_vacia(capa: str) -> None:
    n = sum(1 for p in _modulos() if _capa(p) == capa)
    assert n >= MINIMO_DE_MODULOS_POR_CAPA[capa], (
        f"la capa '{capa}' tiene {n} modulos (minimo {MINIMO_DE_MODULOS_POR_CAPA[capa]}): "
        "si se movieron, actualizar CAPAS; si no, sus reglas no estan mirando nada"
    )


def test_las_entradas_solo_hablan_con_casos_de_uso() -> None:
    """Fase 1: ni un repositorio por atributo del contenedor, ni el modulo de
    repositorios por import."""
    ofensas = []
    for archivo in _modulos():
        if _capa(archivo) != "entradas":
            continue
        ofensas += _accesos_a_repositorios(archivo)
        ofensas += [
            f"{archivo.name}: {i}" for i in _imports(archivo) if any(_es_modulo(i, m) for m in REPOSITORIOS_DEL_MODELO)
        ]
    assert not ofensas, "un entry point toca un repositorio:\n  " + "\n  ".join(ofensas)


def test_las_excepciones_provisorias_siguen_haciendo_falta() -> None:
    """Si la CLI deja de importar `composicion`, la excepcion sobra: borrarla,
    para que no quede una puerta abierta que nadie usa."""
    for relativo, capas in EXCEPCIONES_PROVISORIAS.items():
        importadas = {_capa_de(i) for i in _imports(_archivo(relativo))}
        assert set(capas) <= importadas, f"{relativo} ya no necesita {capas}"


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
            if _alcanza_pagos(imp):
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
    archivo = _archivo(relativo)
    assert archivo in _modulos(), f"{relativo} no existe o quedo fuera de _modulos()"
    esperada = "agente" if relativo.startswith("usecase/agente/") else relativo.split("/")[0]
    assert _capa(archivo) == esperada


# -- etapa 2: recuperacion documental ----------------------------------------- #


def _es_modulo(importado: str, prefijo: str) -> bool:
    """`adaptadores.x...` o `agora.adaptadores.x...` -- no `langchain_core.x`."""
    ruta = prefijo.replace(".", "/")
    assert any((r / ruta).is_dir() or (r / f"{ruta}.py").is_file() for r in RAICES), (
        f"una regla apunta a '{prefijo}', que ya no existe en agora/: si se "
        "movio, actualizar la regla -- si no, compara contra nada y pasa siempre"
    )
    sin_raiz = importado[len("agora."):] if importado.startswith("agora.") else importado
    return sin_raiz == prefijo or sin_raiz.startswith(prefijo + ".")


def _modulos_bajo(prefijo: str) -> list[Path]:
    encontrados = [p for p in _modulos() if _rel(p).startswith(prefijo)]
    assert encontrados, f"ningun modulo bajo '{prefijo}': si se movio, actualizar la regla"
    return encontrados


def test_el_indice_documental_nunca_se_mezcla_con_el_catalogo() -> None:
    """Decision 1 del documento: el indice de soporte es "un indice separado
    (nunca mezclado con el catalogo)". Dicho en imports: la recuperacion
    documental no alcanza nada del catalogo, y el catalogo no alcanza nada
    de la recuperacion documental."""
    ofensas = []
    for archivo in _modulos_bajo("adaptadores/recuperacion/") + _modulos_bajo("adaptadores/embeddings/"):
        ofensas += [f"{archivo.name}: {i}" for i in _imports(archivo) if "catalogo" in i.split(".")]
    for archivo in _modulos_bajo("adaptadores/catalogo/") + [_archivo("model/catalogo/gateways/catalogo.py")]:
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
        _rel(archivo)
        for archivo in _modulos()
        if any(i.split(".")[0] == "langgraph" for i in _imports(archivo))
    )

    assert con_langgraph == ["adaptadores/orquestacion/con_langgraph/compilador.py"]


def test_el_puerto_de_orquestacion_no_conoce_ninguna_libreria_de_grafos() -> None:
    """Si el puerto importara langgraph, no seria un puerto: seria un alias.
    Lo unico que puede importar es la biblioteca estandar."""
    ofensas = [
        i
        for i in _imports(_archivo("model/agente/gateways/orquestacion.py"))
        if i.split(".")[0] not in ("dataclasses", "typing", "__future__")
    ]

    assert not ofensas, "model/agente/gateways/orquestacion.py importa de mas:\n  " + "\n  ".join(ofensas)


def test_el_grafo_del_agente_solo_conoce_el_puerto() -> None:
    """`agente/grafo.py` arma la topologia del turno sin saber quien la
    compila: recibe el `CompiladorDeGrafos` por constructor."""
    importados = _imports(_archivo("usecase/agente/grafo.py"))

    assert any(_es_modulo(i, "model.agente.gateways.orquestacion") for i in importados)
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
            if _es_modulo(i, "adaptadores.catalogo") or _es_modulo(i, "model.catalogo.gateways.catalogo")
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
            or _es_modulo(i, "model.catalogo.gateways.busqueda_productos")
        ]
    assert not ofensas, "los dos indices se cruzan:\n  " + "\n  ".join(ofensas)


def test_el_puerto_de_busqueda_de_productos_no_conoce_ninguna_libreria() -> None:
    """Las reglas duras (`FiltrosDeProducto`) viven de este lado de la
    frontera, sobre objetos de dominio: nada de numpy ni de vector stores."""
    ofensas = [
        i
        for i in _imports(_archivo("model/catalogo/gateways/busqueda_productos.py"))
        if i.split(".")[0] not in ("dataclasses", "typing", "__future__")
        and not _es_modulo(i, "model.catalogo.modelo")
    ]

    assert not ofensas, (
        "model/catalogo/gateways/busqueda_productos.py importa de mas:\n  " + "\n  ".join(ofensas)
    )


def test_los_agentes_especializados_no_alcanzan_ninguna_pasarela() -> None:
    """`agente/agentes.py` decide que herramientas ve cada agente: es
    exactamente el modulo donde un import de mas seria peor."""
    ofensas = [
        i for i in _imports(_archivo("usecase/agente/agentes.py"))
        if _alcanza_pagos(i)
    ]

    assert not ofensas, "usecase/agente/agentes.py cruza una frontera:\n  " + "\n  ".join(ofensas)


# -- trazabilidad ------------------------------------------------------------- #


def test_la_traza_no_conoce_ningun_adaptador_de_bitacora() -> None:
    """`agente/traza.py` arma el cuerpo; quien lo escribe es un `Bitacora`
    que llega por constructor. Si conociera el adaptador de .jsonl, cambiar
    el destino de las trazas (a stdout, a otro formato) obligaria a tocar el
    agente."""
    ofensas = [
        i for i in _imports(_archivo("usecase/agente/traza.py"))
        if _es_modulo(i, "adaptadores") or _es_modulo(i, "composicion")
    ]

    assert not ofensas, "usecase/agente/traza.py conoce un adaptador:\n  " + "\n  ".join(ofensas)


# -- etapa 5: la pausa humana -------------------------------------------------- #


def test_la_pausa_no_alcanza_ningun_caso_de_uso_ni_pasarela() -> None:
    """`agente/pausa.py` describe QUE hay que decidir y arma el texto que lee
    el modelo. Quien firma y quien cobra siguen siendo `aplicacion/`, por
    pedido de una persona desde `entradas/`. Si este modulo pudiera importar
    `EmitirMandatoUseCase`, el agente estaria a un import de firmar solo."""
    ofensas = [
        i for i in _imports(_archivo("usecase/agente/pausa.py"))
        if _alcanza_pagos(i)
    ]

    assert not ofensas, "usecase/agente/pausa.py cruza una frontera:\n  " + "\n  ".join(ofensas)


def test_el_puerto_de_orquestacion_define_la_pausa_sin_conocer_el_motor() -> None:
    """Detener el grafo no necesita nada del motor: `PausaRequerida` es una
    excepcion del puerto, no el `interrupt()` de ninguna libreria."""
    fuente = (_archivo("model/agente/gateways/orquestacion.py")).read_text(encoding="utf-8")

    assert "class PausaRequerida" in fuente
    assert "interrupt" not in fuente.replace("`interrupt()`", "")


def test_solo_agente_pausa_arma_el_aviso_que_lee_el_modelo() -> None:
    """La queja concreta de la decision 6: antes habia cuatro sitios
    escribiendo ese texto a mano. Las frases que el modelo distingue viven
    ahora en un solo archivo."""
    marcas = ("Continua el flujo de compra llamando a", "no hay mandato ni pago")
    culpables = [
        _rel(p)
        for p in _modulos()
        for marca in marcas
        if marca in p.read_text(encoding="utf-8")
    ]

    assert set(culpables) == {"usecase/agente/pausa.py"}, (
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
        "usecase/agente/clasificacion/intruso.py",
        "from ...ejecutar_intencion.ejecutar_intencion_use_case import EjecutarIntencionUseCase\n",
    )
    ofensas = _violaciones_de_dependencia(archivo, raiz)
    assert ofensas and "usecase" in ofensas[0]


def test_el_detector_atrapa_al_agente_importando_entradas(tmp_path: Path) -> None:
    raiz, archivo = _agora_de_mentira(
        tmp_path, "usecase/agente/intruso.py", "from agora.entradas.api.app import crear_app\n",
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
@pytest.mark.parametrize("capa", ["model", "usecase", "usecase/agente", "entradas", "composicion"])
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
        tmp_path, "model/agente/gateways/orquestacion.py", "from langgraph.graph import StateGraph\n",
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
        "usecase/agente/grafo.py",
        "from ...adaptadores.orquestacion.con_langgraph import CompiladorLangGraph\n",
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
        "from ....model.catalogo.gateways.catalogo import RepositorioCatalogo\n",
    )
    archivo = raiz / "adaptadores/busqueda_productos/semantico_en_memoria/intruso.py"
    ofensas = [
        i for i in _imports(archivo, raiz)
        if _es_modulo(i, "adaptadores.catalogo") or _es_modulo(i, "model.catalogo.gateways.catalogo")
    ]
    assert ofensas


def test_el_detector_atrapa_al_puerto_de_productos_importando_numpy(
    tmp_path: Path,
) -> None:
    raiz, _ = _agora_de_mentira(
        tmp_path, "model/catalogo/gateways/busqueda_productos.py", "import numpy as np\n",
    )
    archivo = raiz / "model/catalogo/gateways/busqueda_productos.py"
    ofensas = [
        i for i in _imports(archivo, raiz)
        if i.split(".")[0] not in ("dataclasses", "typing", "__future__")
        and not _es_modulo(i, "model.catalogo.modelo")
    ]
    assert ofensas


def test_el_detector_atrapa_a_los_agentes_importando_un_caso_de_uso(
    tmp_path: Path,
) -> None:
    raiz, archivo = _agora_de_mentira(
        tmp_path,
        "usecase/agente/agentes.py",
        "from ..navegar_catalogo.navegar_catalogo_use_case import NavegarCatalogoUseCase\n",
    )
    ofensas = _violaciones_de_dependencia(archivo, raiz)
    assert ofensas and "usecase" in ofensas[0]


def test_el_detector_atrapa_importaciones_dinamicas(tmp_path: Path) -> None:
    _, archivo = _agora_de_mentira(
        tmp_path, "usecase/agente/intruso.py", 'p = __import__("agora.adaptadores.pasarelas.wompi")\n',
    )
    assert _importaciones_dinamicas(archivo)


@pytest.mark.parametrize(
    "importado",
    [
        "model.pago.gateways.pasarela",
        "agora.model.mandato.gateways.firma",
        "model.pago.gateways.repositorios",
        "agora.model.usuario.gateways.autenticacion",
        "adaptadores.pasarelas.wompi",
        "agora.usecase.ejecutar_intencion.ejecutar_intencion_use_case",
    ],
)
def test_el_detector_atrapa_al_agente_alcanzando_pagos(importado: str) -> None:
    """Incluye lo que la regla vieja ("pasarela" en el nombre y no "puertos")
    dejaba pasar: el puerto de la pasarela y el de firma."""
    assert _alcanza_pagos(importado)


@pytest.mark.parametrize("importado", ["model.agente.gateways.modelo_lenguaje", "agora.model.commons.gateways.sistema", "json"])
def test_el_detector_deja_al_agente_usar_sus_puertos(importado: str) -> None:
    assert not _alcanza_pagos(importado)


def test_el_detector_atrapa_un_archivo_sin_capa(tmp_path: Path) -> None:
    raiz, archivo = _agora_de_mentira(tmp_path, "capa_nueva/intruso.py", "import os\n")
    assert _capa(archivo, raiz) is None


def test_el_detector_atrapa_una_regla_que_apunta_a_un_modulo_que_no_existe() -> None:
    with pytest.raises(AssertionError, match="ya no existe"):
        _es_modulo("agora.model.x", "model.carpeta_que_se_movio")


def test_el_detector_atrapa_una_entrada_importando_composicion(tmp_path: Path) -> None:
    raiz, archivo = _agora_de_mentira(
        tmp_path, "entradas/api/intruso.py", "from ...composicion.contenedor import Contenedor\n",
    )
    ofensas = _violaciones_de_dependencia(archivo, raiz)
    assert ofensas and "composicion" in ofensas[0]


def test_el_detector_atrapa_una_entrada_leyendo_un_repositorio(tmp_path: Path) -> None:
    _, archivo = _agora_de_mentira(
        tmp_path, "entradas/api/intruso.py", "def f(d):\n    return d.carritos.obtener('x')\n",
    )
    assert _accesos_a_repositorios(archivo)


# -- Fase 2: domain/model ------------------------------------------------------ #


def _ajenos_al_modelo(archivo: Path, raiz: Path | None = None) -> list[str]:
    return [
        i for i in _imports(archivo, raiz)
        if _capa_de(i) != "model" and i.split(".")[0] not in sys.stdlib_module_names | {"__future__"}
    ]


@pytest.mark.parametrize("archivo", [p for p in _modulos() if _capa(p) == "model"], ids=_rel)
def test_el_modelo_solo_conoce_el_modelo_y_la_biblioteca_estandar(archivo: Path) -> None:
    """El `whitelistedDependencies` del `validateStructure` de Bancolombia,
    en su version mas estricta: la lista blanca esta vacia."""
    assert not _ajenos_al_modelo(archivo)


def test_el_detector_atrapa_al_modelo_importando_una_libreria(tmp_path: Path) -> None:
    raiz, archivo = _agora_de_mentira(tmp_path, "model/pago/intruso.py", "from pydantic import BaseModel\n")
    assert _ajenos_al_modelo(archivo, raiz) == ["pydantic"]


# -- Fase 3: domain/usecase ---------------------------------------------------- #


def test_el_detector_atrapa_un_caso_de_uso_importando_al_agente(tmp_path: Path) -> None:
    """La otra mitad de la frontera: los casos de uso no saben que existe un
    agente. Si `PagarCarritoUseCase` importara la conversacion, el agente
    dejaria de ser un cliente mas de los casos de uso."""
    raiz, archivo = _agora_de_mentira(
        tmp_path,
        "usecase/pagar_carrito/intruso.py",
        "from ..agente.conversacion import Agente\n",
    )
    ofensas = _violaciones_de_dependencia(archivo, raiz)
    assert ofensas and "agente" in ofensas[0]


def test_cada_caso_de_uso_vive_en_su_carpeta_y_termina_en_usecase() -> None:
    """La convencion del scaffold: `usecase/<caso>/<caso>_use_case.py` con
    una sola clase `<Caso>UseCase` (mas los tipos que devuelve)."""
    ofensas = []
    for archivo in _modulos():
        partes = _rel(archivo).split("/")
        if _capa(archivo) != "usecase" or partes[-1] == "__init__.py":
            continue
        if len(partes) != 3 or partes[2] != f"{partes[1]}_use_case.py":
            ofensas.append(f"{_rel(archivo)}: no es usecase/<caso>/<caso>_use_case.py")
            continue
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        casos = [n.name for n in arbol.body if isinstance(n, ast.ClassDef) and n.name.endswith("UseCase")]
        if len(casos) != 1:
            ofensas.append(f"{_rel(archivo)}: {len(casos)} clases *UseCase (tiene que haber 1)")
    assert not ofensas, "\n  ".join(["casos de uso fuera de la convencion:", *ofensas])
