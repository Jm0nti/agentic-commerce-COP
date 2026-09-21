"""La trazabilidad del agente: una linea por turno, con la cadena de
decisiones que explica la respuesta.

Lo que mas importa de este archivo: **una herramienta rechazada por estar
fuera de ruta queda marcada como tal**. Es la evidencia observable de que
el enrutamiento hizo su trabajo -- la version "despues del hecho" de lo que
`test_fronteras.py` verifica estructuralmente y `test_agente_enrutado.py`
verifica en ejecucion.
"""

from __future__ import annotations

import json

import pytest

from agora.adaptadores.orquestacion.con_langgraph import CompiladorLangGraph
from agora.agente.contexto import ContextoInyectado
from agora.agente.conversacion import Agente
from agora.agente.grafo import AgenteEnGrafo
from agora.agente.herramientas import CATALOGO_DE_HERRAMIENTAS, construir_herramientas
from agora.agente.intencion import ClasificacionDeIntencion, OrigenDeClasificacion, TipoDeIntencion
from agora.agente.traza import EVENTO, MARCA_DE_RECORTE, MAX_CARACTERES_POR_CAMPO
from agora.puertos.modelo_lenguaje import LlamadaHerramienta, RespuestaModelo


class _BitacoraEspia:
    def __init__(self) -> None:
        self.anotaciones: list[tuple[str, dict]] = []

    def anotar(self, evento, cuerpo):
        # Se serializa de verdad: una traza que no es JSON no sirve de nada
        # en un .jsonl, y el adaptador real fallaria recien en produccion.
        json.dumps(cuerpo, ensure_ascii=False)
        self.anotaciones.append((evento, cuerpo))

    @property
    def ultima(self) -> dict:
        return self.anotaciones[-1][1]


class _BitacoraRota:
    def anotar(self, evento, cuerpo):
        raise OSError("disco lleno")


class _ModeloGuionado:
    def __init__(self, respuestas):
        self._respuestas = list(respuestas)

    def generar(self, sistema, instruccion):
        raise AssertionError("no se usa")

    def responder(self, mensajes, herramientas):
        return self._respuestas.pop(0)


class _ClasificadorFijo:
    def __init__(self, *intenciones):
        self._pendientes = list(intenciones)

    def clasificar(self, mensaje, historial=()):
        intencion = self._pendientes.pop(0)
        if intencion is None:
            return ClasificacionDeIntencion.respaldo("ambiguo")
        return ClasificacionDeIntencion(
            intencion=intencion, origen=OrigenDeClasificacion.REGLAS,
            confianza=1.0, motivo="prueba",
        )


class _Espias:
    def __init__(self):
        self.ejecutadas: list[str] = []

    def herramientas(self):
        def funcion(nombre):
            def _f(**_):
                self.ejecutadas.append(nombre)
                return {"herramienta": nombre, "ok": True}
            return _f
        return construir_herramientas(**{n: funcion(n) for n in CATALOGO_DE_HERRAMIENTAS})


def _agente(respuestas, intenciones, bitacora, contextos=None, en_grafo=False):
    base = Agente(
        modelo=_ModeloGuionado(respuestas),
        herramientas=_Espias().herramientas(),
        clasificador=None if intenciones is None else _ClasificadorFijo(*intenciones),
        contextos=contextos or {},
        bitacora=bitacora,
    )
    return AgenteEnGrafo(base, CompiladorLangGraph()) if en_grafo else base


EN_LOS_DOS_CAMINOS = pytest.mark.parametrize(
    "en_grafo", [False, True], ids=["directo", "grafo"],
)


# -- que se anota, y cuando -------------------------------------------------- #


@EN_LOS_DOS_CAMINOS
def test_cada_turno_deja_exactamente_una_linea(en_grafo):
    espia = _BitacoraEspia()
    agente = _agente(
        [RespuestaModelo(contenido="hay dos tiendas"), RespuestaModelo(contenido="aprobado")],
        [TipoDeIntencion.CATALOGO, TipoDeIntencion.ESTADO],
        espia, en_grafo=en_grafo,
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "que tiendas hay")
    agente.turno(conversacion, "como va mi pago")

    assert [evento for evento, _ in espia.anotaciones] == [EVENTO, EVENTO]


@EN_LOS_DOS_CAMINOS
def test_la_traza_lleva_el_mensaje_y_la_respuesta(en_grafo):
    espia = _BitacoraEspia()
    agente = _agente(
        [RespuestaModelo(contenido="hay dos tiendas")], [TipoDeIntencion.CATALOGO],
        espia, en_grafo=en_grafo,
    )

    agente.turno(agente.iniciar(), "que tiendas hay")

    assert espia.ultima["mensaje"] == "que tiendas hay"
    assert espia.ultima["respuesta"] == "hay dos tiendas"
    assert espia.ultima["duracion_ms"] >= 0


@EN_LOS_DOS_CAMINOS
def test_la_traza_explica_la_decision_del_orquestador(en_grafo):
    """Paso 1: por que este turno fue a donde fue."""
    espia = _BitacoraEspia()
    agente = _agente(
        [RespuestaModelo(contenido="ok")], [TipoDeIntencion.ESTADO], espia, en_grafo=en_grafo,
    )

    agente.turno(agente.iniciar(), "como va mi pago")

    assert espia.ultima["clasificacion"] == {
        "intencion": "estado", "origen": "reglas", "confianza": 1.0, "motivo": "prueba",
    }
    assert espia.ultima["nodos"] == ["estado"]
    assert espia.ultima["herramientas_habilitadas"] == ["consultar_estado"]
    assert espia.ultima["es_respaldo"] is False


@EN_LOS_DOS_CAMINOS
def test_los_turnos_de_una_charla_comparten_conversacion_id(en_grafo):
    """Sin esto, dos personas chateando a la vez dejan lineas intercaladas
    que no se pueden separar despues."""
    espia = _BitacoraEspia()
    agente = _agente(
        [RespuestaModelo(contenido="a"), RespuestaModelo(contenido="b")],
        [TipoDeIntencion.CATALOGO, TipoDeIntencion.SOPORTE],
        espia, en_grafo=en_grafo,
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "uno")
    agente.turno(conversacion, "dos")

    ids = {cuerpo["conversacion_id"] for _, cuerpo in espia.anotaciones}
    assert ids == {conversacion.conversacion_id}
    assert [c["turno"] for _, c in espia.anotaciones] == [1, 2]


def test_dos_conversaciones_tienen_ids_distintos():
    espia = _BitacoraEspia()
    agente = _agente(
        [RespuestaModelo(contenido="a"), RespuestaModelo(contenido="b")],
        [TipoDeIntencion.CATALOGO, TipoDeIntencion.CATALOGO], espia,
    )

    agente.turno(agente.iniciar(), "uno")
    agente.turno(agente.iniciar(), "dos")

    ids = {cuerpo["conversacion_id"] for _, cuerpo in espia.anotaciones}
    assert len(ids) == 2


# -- la evidencia del enrutamiento ------------------------------------------- #


@EN_LOS_DOS_CAMINOS
def test_una_herramienta_rechazada_por_ruta_queda_marcada(en_grafo):
    """LA prueba de este archivo. El modelo alucino `pagar` en un turno de
    soporte; la traza tiene que decir que se le negó, no solo que hubo un
    error."""
    alucinada = LlamadaHerramienta(
        id="c1", nombre="pagar", argumentos={"mandato_id": "m", "carrito_id": "c"},
    )
    espia = _BitacoraEspia()
    agente = _agente(
        [
            RespuestaModelo(contenido=None, llamadas=(alucinada,)),
            RespuestaModelo(contenido="un mandato es un permiso"),
        ],
        [TipoDeIntencion.SOPORTE], espia, en_grafo=en_grafo,
    )

    agente.turno(agente.iniciar(), "que es un mandato?")

    llamada = espia.ultima["llamadas"][0]
    assert llamada["herramienta"] == "pagar"
    assert llamada["fuera_de_ruta"] is True
    assert "no esta habilitada" in llamada["error"]
    assert espia.ultima["herramientas_habilitadas"] == []


@EN_LOS_DOS_CAMINOS
def test_una_herramienta_de_la_ruta_no_queda_marcada_como_rechazada(en_grafo):
    llamada = LlamadaHerramienta(
        id="c1", nombre="consultar_estado", argumentos={"intencion_id": "int_1"},
    )
    espia = _BitacoraEspia()
    agente = _agente(
        [
            RespuestaModelo(contenido=None, llamadas=(llamada,)),
            RespuestaModelo(contenido="aprobado"),
        ],
        [TipoDeIntencion.ESTADO], espia, en_grafo=en_grafo,
    )

    agente.turno(agente.iniciar(), "como va mi pago")

    anotada = espia.ultima["llamadas"][0]
    assert anotada["herramienta"] == "consultar_estado"
    assert "fuera_de_ruta" not in anotada
    assert "error" not in anotada
    assert espia.ultima["rondas"] == 2


def test_la_traza_del_grafo_dice_que_agente_atendio():
    espia = _BitacoraEspia()
    agente = _agente(
        [RespuestaModelo(contenido="ok")], [TipoDeIntencion.CARRITO_PAGO],
        espia, en_grafo=True,
    )

    agente.turno(agente.iniciar(), "quiero comprar")

    assert espia.ultima["agente"] == "carrito_pago"
    assert espia.ultima["nodos"] == ["catalogo", "carrito_pago"]


def test_en_el_camino_directo_no_hay_agente_porque_no_corrio_ninguno():
    """`agente` en `None` es honesto: sin grafo no hay nodo de agente. Los
    `nodos` siguen diciendo lo mismo."""
    espia = _BitacoraEspia()
    agente = _agente(
        [RespuestaModelo(contenido="ok")], [TipoDeIntencion.CARRITO_PAGO], espia,
    )

    agente.turno(agente.iniciar(), "quiero comprar")

    assert espia.ultima["agente"] is None
    assert espia.ultima["nodos"] == ["catalogo", "carrito_pago"]


# -- contexto y respaldo ------------------------------------------------------ #


@EN_LOS_DOS_CAMINOS
def test_la_traza_dice_de_que_documentos_salio_el_contexto(en_grafo):
    class _Contexto:
        def contexto_para(self, mensaje, historial=()):
            return ContextoInyectado(
                texto="DOCUMENTACION", fuentes=("docs/soporte/a.md", "docs/soporte/b.md"),
            )

    espia = _BitacoraEspia()
    agente = _agente(
        [RespuestaModelo(contenido="un mandato es un permiso")], [TipoDeIntencion.SOPORTE],
        espia, contextos={"soporte": _Contexto()}, en_grafo=en_grafo,
    )

    agente.turno(agente.iniciar(), "que es un mandato?")

    assert espia.ultima["contexto"] == [
        {
            "nodo": "soporte",
            "fuentes": ["docs/soporte/a.md", "docs/soporte/b.md"],
            "caracteres": len("DOCUMENTACION"),
        }
    ]


@EN_LOS_DOS_CAMINOS
def test_el_respaldo_queda_registrado_como_tal(en_grafo):
    espia = _BitacoraEspia()
    agente = _agente(
        [RespuestaModelo(contenido="no entendi")], [None], espia, en_grafo=en_grafo,
    )

    agente.turno(agente.iniciar(), "mmm")

    assert espia.ultima["es_respaldo"] is True
    assert espia.ultima["clasificacion"]["origen"] == "respaldo"
    assert espia.ultima["clasificacion"]["intencion"] is None
    assert set(espia.ultima["herramientas_habilitadas"]) == set(CATALOGO_DE_HERRAMIENTAS)


def test_sin_clasificador_igual_se_traza():
    """`AGORA_CLASIFICADOR=apagado` no deberia apagar la trazabilidad."""
    espia = _BitacoraEspia()
    agente = _agente([RespuestaModelo(contenido="hola")], None, espia)

    agente.turno(agente.iniciar(), "hola")

    assert espia.ultima["clasificacion"] is None
    assert espia.ultima["mensaje"] == "hola"
    assert set(espia.ultima["herramientas_habilitadas"]) == set(CATALOGO_DE_HERRAMIENTAS)


# -- lo que no puede pasar ---------------------------------------------------- #


@EN_LOS_DOS_CAMINOS
def test_sin_bitacora_el_turno_funciona_igual(en_grafo):
    agente = _agente(
        [RespuestaModelo(contenido="hola")], [TipoDeIntencion.CATALOGO], None,
        en_grafo=en_grafo,
    )

    assert agente.turno(agente.iniciar(), "hola") == "hola"


@EN_LOS_DOS_CAMINOS
def test_una_bitacora_rota_no_tumba_el_turno(en_grafo):
    """La respuesta que la persona ya tiene en pantalla no se pierde porque
    el disco este lleno."""
    agente = _agente(
        [RespuestaModelo(contenido="hola")], [TipoDeIntencion.CATALOGO],
        _BitacoraRota(), en_grafo=en_grafo,
    )

    assert agente.turno(agente.iniciar(), "hola") == "hola"


def test_los_campos_largos_se_recortan_con_marca():
    """Una traza que nadie puede leer no sirve de evidencia -- pero el
    recorte nunca es silencioso."""
    largo = "x" * (MAX_CARACTERES_POR_CAMPO * 3)
    espia = _BitacoraEspia()
    agente = _agente(
        [RespuestaModelo(contenido=largo)], [TipoDeIntencion.CATALOGO], espia,
    )

    agente.turno(agente.iniciar(), largo)

    assert espia.ultima["mensaje"].endswith(MARCA_DE_RECORTE)
    assert espia.ultima["respuesta"].endswith(MARCA_DE_RECORTE)
    assert len(espia.ultima["mensaje"]) < len(largo)
