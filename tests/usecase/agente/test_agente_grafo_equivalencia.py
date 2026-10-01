"""La prueba central de la etapa 3: el grafo no cambia NADA observable.

Cada escenario se corre dos veces -- una por `Agente.turno` (el camino de las
etapas 1 y 2) y otra por `AgenteEnGrafo.turno` con el compilador REAL de
LangGraph -- con dobles identicos pero independientes, y se comparan todas
las salidas que alguien podria mirar:

    respuesta            lo que devuelve el turno
    mensajes             el historial guardado (roles y contenidos)
    clasificaciones      el registro auditable de que decidio el orquestador
    contextos            que documentacion vio el modelo
    herramientas         las que se le ANUNCIARON al modelo en cada ronda
    sistema              el mensaje de sistema de la vista, ronda por ronda

Si esta prueba falla, el grafo dejo de ser un andamio y empezo a ser un
cambio de comportamiento -- que es exactamente lo que esta etapa no quiere.
"""

from __future__ import annotations

import json

import pytest

from agora.driven_adapters.orquestacion_langgraph import CompiladorLangGraph
from agora.model.agente.contexto import ContextoInyectado
from agora.usecase.agente.conversacion import Agente, LimiteDeTurnosExcedido
from agora.usecase.agente.grafo import AgenteEnGrafo
from agora.usecase.agente.herramientas import CATALOGO_DE_HERRAMIENTAS, construir_herramientas
from agora.model.agente.intencion import (
    ClasificacionDeIntencion,
    OrigenDeClasificacion,
    TipoDeIntencion,
)
from agora.model.agente.gateways.modelo_lenguaje import LlamadaHerramienta, Mensaje, RespuestaModelo


class _ModeloGuionado:
    def __init__(self, respuestas):
        self._respuestas = list(respuestas)
        self.llamadas: list[tuple[list[Mensaje], list]] = []

    def generar(self, sistema, instruccion):
        raise AssertionError("el clasificador de estas pruebas es fijo: no usa el modelo")

    def responder(self, mensajes, herramientas):
        self.llamadas.append((list(mensajes), list(herramientas)))
        return self._respuestas.pop(0)


class _ClasificadorFijo:
    def __init__(self, intenciones):
        self._pendientes = list(intenciones)
        self.recibido: list[tuple[str, tuple[Mensaje, ...]]] = []

    def clasificar(self, mensaje, historial=()):
        self.recibido.append((mensaje, tuple(historial)))
        intencion = self._pendientes.pop(0)
        if intencion is None:
            return ClasificacionDeIntencion.respaldo("prueba")
        return ClasificacionDeIntencion(
            intencion=intencion, origen=OrigenDeClasificacion.REGLAS, confianza=1.0,
            motivo="prueba",
        )


class _ContextoEspia:
    def __init__(self):
        self.pedidos: list[tuple[str, tuple]] = []
        self.contexto = ContextoInyectado(
            texto="DOCUMENTACION DE PRUEBA", fuentes=("docs/soporte/a.md",),
        )

    def contexto_para(self, mensaje, historial=()):
        self.pedidos.append((mensaje, tuple(historial)))
        return self.contexto


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


def _armar_agente(respuestas, intenciones, con_contexto):
    """Un `Agente` fresco con sus propios dobles. `intenciones=None` significa
    sin clasificador (el agente pelado de antes de la etapa 1)."""
    espias = _Espias()
    modelo = _ModeloGuionado(respuestas())
    clasificador = None if intenciones is None else _ClasificadorFijo(intenciones)
    contextos = {"soporte": _ContextoEspia()} if con_contexto else {}
    agente = Agente(
        modelo=modelo,
        herramientas=espias.herramientas(),
        clasificador=clasificador,
        contextos=contextos,
    )
    return agente, modelo, espias, contextos


def _observado(conversacion, modelo, espias, contextos, respuestas):
    """Todo lo que alguien de afuera podria mirar despues de un turno."""
    return {
        "respuestas": respuestas,
        "mensajes": [
            (m.rol, m.contenido, m.nombre_herramienta, tuple(m.llamadas or ()))
            for m in conversacion.mensajes
        ],
        "clasificaciones": list(conversacion.clasificaciones),
        "contextos": list(conversacion.contextos),
        "herramientas_anunciadas": [
            sorted(d.nombre for d in definiciones) for _, definiciones in modelo.llamadas
        ],
        "sistema_por_ronda": [vista[0].contenido for vista, _ in modelo.llamadas],
        "roles_por_ronda": [[m.rol for m in vista] for vista, _ in modelo.llamadas],
        "ejecutadas": list(espias.ejecutadas),
        "pedidos_de_contexto": [
            list(proveedor.pedidos) for proveedor in contextos.values()
        ],
    }


def _correr(construir_envoltorio, respuestas, mensajes, intenciones, con_contexto):
    agente, modelo, espias, contextos = _armar_agente(respuestas, intenciones, con_contexto)
    corredor = construir_envoltorio(agente)
    conversacion = corredor.iniciar()
    dichas = [corredor.turno(conversacion, mensaje) for mensaje in mensajes]
    return _observado(conversacion, modelo, espias, contextos, dichas)


def _directo(agente):
    return agente


def _en_grafo(agente):
    """El compilador REAL de LangGraph, no un doble: lo que esta etapa
    promete es que el turno da lo mismo corriendo por LangGraph de verdad."""
    return AgenteEnGrafo(agente, CompiladorLangGraph())


# --------------------------------------------------------------------------- #
# Los escenarios. Cada uno: (respuestas del modelo, mensajes, intenciones,
# si hay proveedor de contexto colgado de soporte).
# --------------------------------------------------------------------------- #

_LLAMADA_ESTADO = LlamadaHerramienta(
    id="c1", nombre="consultar_estado", argumentos={"intencion_id": "int_1"},
)
_PAGAR_ALUCINADO = LlamadaHerramienta(
    id="c9", nombre="pagar", argumentos={"mandato_id": "mnd_x", "carrito_id": "car_x"},
)
_ARMAR = LlamadaHerramienta(
    id="c2", nombre="armar_carrito",
    argumentos={"comercio_id": "com_1", "items": [{"producto_id": "pro_1"}]},
)

ESCENARIOS = {
    "catalogo_una_ronda": (
        lambda: [RespuestaModelo(contenido="hay dos tiendas")],
        ["que tiendas hay"],
        [TipoDeIntencion.CATALOGO],
        False,
    ),
    "estado_con_herramienta": (
        lambda: [
            RespuestaModelo(contenido=None, llamadas=(_LLAMADA_ESTADO,)),
            RespuestaModelo(contenido="tu pago esta aprobado"),
        ],
        ["como va mi pago"],
        [TipoDeIntencion.ESTADO],
        False,
    ),
    "compra_no_recibe_contexto": (
        lambda: [
            RespuestaModelo(contenido=None, llamadas=(_ARMAR,)),
            RespuestaModelo(contenido="te arme el carrito"),
        ],
        ["quiero comprar los audifonos"],
        [TipoDeIntencion.CARRITO_PAGO],
        True,
    ),
    "soporte_con_contexto": (
        lambda: [RespuestaModelo(contenido="un mandato es un permiso firmado")],
        ["que es un mandato?"],
        [TipoDeIntencion.SOPORTE],
        True,
    ),
    "soporte_rechaza_una_herramienta_alucinada": (
        lambda: [
            RespuestaModelo(contenido=None, llamadas=(_PAGAR_ALUCINADO,)),
            RespuestaModelo(contenido="no puedo cobrar desde aca"),
        ],
        ["que es un mandato?"],
        [TipoDeIntencion.SOPORTE],
        True,
    ),
    "respaldo": (
        lambda: [RespuestaModelo(contenido="no entendi, contame mas")],
        ["mmm"],
        [None],
        True,
    ),
    "sin_clasificador": (
        lambda: [RespuestaModelo(contenido="hola")],
        ["hola"],
        None,
        False,
    ),
    "varios_turnos_seguidos": (
        lambda: [
            RespuestaModelo(contenido="hay dos tiendas"),
            RespuestaModelo(contenido=None, llamadas=(_LLAMADA_ESTADO,)),
            RespuestaModelo(contenido="aprobado"),
            RespuestaModelo(contenido="un mandato es un permiso"),
        ],
        ["que tiendas hay", "como va mi pago", "que es un mandato?"],
        [TipoDeIntencion.CATALOGO, TipoDeIntencion.ESTADO, TipoDeIntencion.SOPORTE],
        True,
    ),
    "fuera_de_alcance": (
        lambda: [RespuestaModelo(contenido="de eso no me encargo")],
        ["contame un chiste"],
        [TipoDeIntencion.FUERA_DE_ALCANCE],
        False,
    ),
    "medios_de_pago": (
        lambda: [RespuestaModelo(contenido="lo enrolas vos desde la app")],
        ["como vinculo mi nequi"],
        [TipoDeIntencion.MEDIOS_DE_PAGO],
        False,
    ),
}


@pytest.mark.parametrize("nombre", sorted(ESCENARIOS))
def test_el_grafo_y_el_agente_directo_dan_exactamente_lo_mismo(nombre):
    respuestas, mensajes, intenciones, con_contexto = ESCENARIOS[nombre]

    sin_grafo = _correr(_directo, respuestas, mensajes, intenciones, con_contexto)
    con_grafo = _correr(_en_grafo, respuestas, mensajes, intenciones, con_contexto)

    assert con_grafo == sin_grafo


def test_el_escenario_de_soporte_verifica_de_verdad_lo_que_dice_verificar():
    """Una comparacion de dos diccionarios iguales puede pasar porque los dos
    lados no hicieron nada. Este ancla el escenario mas cargado contra
    valores concretos, para que la parametrizada de arriba no pueda quedar
    vacia en silencio."""
    respuestas, mensajes, intenciones, con_contexto = ESCENARIOS[
        "soporte_rechaza_una_herramienta_alucinada"
    ]

    observado = _correr(_en_grafo, respuestas, mensajes, intenciones, con_contexto)

    assert observado["respuestas"] == ["no puedo cobrar desde aca"]
    # Soporte no anuncia herramientas, en ninguna de las dos rondas...
    assert observado["herramientas_anunciadas"] == [[], []]
    # ...y `pagar` no se ejecuto: la funcion real nunca corrio.
    assert observado["ejecutadas"] == []
    assert all("Intencion clasificada: soporte" in s for s in observado["sistema_por_ronda"])
    assert all("DOCUMENTACION DE PRUEBA" in s for s in observado["sistema_por_ronda"])
    # El contexto se pidio UNA vez, aunque el loop dio dos vueltas.
    assert len(observado["pedidos_de_contexto"][0]) == 1
    roles = [rol for rol, *_ in observado["mensajes"]]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    error = json.loads(observado["mensajes"][3][1])["error"]
    assert "no esta habilitada" in error and "soporte" in error


def test_la_instruccion_del_orquestador_tampoco_se_guarda_corriendo_por_el_grafo():
    agente, modelo, _, _ = _armar_agente(
        lambda: [RespuestaModelo(contenido="ok")], [TipoDeIntencion.ESTADO], False,
    )
    corredor = _en_grafo(agente)
    conversacion = corredor.iniciar()
    prompt_general = conversacion.mensajes[0].contenido

    corredor.turno(conversacion, "como va mi pago")

    assert "Intencion clasificada: estado" in modelo.llamadas[0][0][0].contenido
    assert conversacion.mensajes[0].contenido == prompt_general


def test_el_clasificador_recibe_el_mismo_historial_previo_que_sin_grafo():
    """`abrir_turno` corre antes de entrar al grafo: el historial que ve el
    orquestador sigue siendo el de ANTES del mensaje que se esta
    clasificando."""
    agente, _, _, _ = _armar_agente(
        lambda: [RespuestaModelo(contenido="a"), RespuestaModelo(contenido="b")],
        [TipoDeIntencion.CATALOGO, TipoDeIntencion.CARRITO_PAGO],
        False,
    )
    clasificador = agente._clasificador
    corredor = _en_grafo(agente)
    conversacion = corredor.iniciar()

    corredor.turno(conversacion, "que tiendas hay")
    corredor.turno(conversacion, "si, dale")

    mensaje, historial = clasificador.recibido[1]
    assert mensaje == "si, dale"
    assert [m.contenido for m in historial if m.rol == "user"] == ["que tiendas hay"]


def test_una_excepcion_del_loop_de_herramientas_sale_del_grafo_sin_envolverse():
    """`entradas/api/app.py` atrapa `LimiteDeTurnosExcedido` por su tipo: si
    el grafo la envolviera, ese `except` dejaria de funcionar y el chat
    devolveria un 500 en vez del mensaje que hoy devuelve."""
    ronda = RespuestaModelo(
        contenido=None,
        llamadas=(LlamadaHerramienta(id="c", nombre="ver_producto", argumentos={"producto_id": "p"}),),
    )
    agente, _, _, _ = _armar_agente(
        lambda: [ronda] * 50, [TipoDeIntencion.CATALOGO], False,
    )
    corredor = _en_grafo(agente)

    with pytest.raises(LimiteDeTurnosExcedido):
        corredor.turno(corredor.iniciar(), "mostrame algo")


def test_iniciar_devuelve_la_misma_conversacion_que_el_agente_directo():
    agente, _, _, _ = _armar_agente(lambda: [], [], False)

    conversacion = _en_grafo(agente).iniciar()

    assert [m.rol for m in conversacion.mensajes] == ["system"]
    assert conversacion.mensajes[0].contenido == agente.iniciar().mensajes[0].contenido


def test_el_agente_en_grafo_expone_las_herramientas_del_agente_que_envuelve():
    """`composicion/agente.py` devuelve un `AgenteEnGrafo` por defecto: quien
    llamaba una herramienta directo (la CLI de pruebas,
    `tests/test_composicion_agente.py`) no tendria que desenvolverlo."""
    agente, _, _, _ = _armar_agente(lambda: [], [], False)

    assert _en_grafo(agente)._herramientas is agente._herramientas


def test_la_topologia_es_el_orquestador_y_un_nodo_por_agente():
    """Etapa 4: el worker unico de la etapa 3 se partio en siete destinos, y
    la condicional que la etapa 3 se nego a poner de utileria ahora es real
    -- siete destinos, todos alcanzables (`DefinicionDeGrafo` lo valida)."""
    from agora.usecase.agente.grafo import definir_grafo_del_turno
    from agora.model.agente.gateways.orquestacion import FIN

    agente, _, _, _ = _armar_agente(lambda: [], [], False)

    definicion = definir_grafo_del_turno(agente)

    assert definicion.entrada == "orquestador"
    agentes = {
        "agente_catalogo",
        "agente_carrito_pago",
        "agente_medios_de_pago",
        "agente_estado",
        "agente_soporte",
        "agente_fuera_de_alcance",
        "agente_respaldo",
    }
    assert set(definicion.nodos) == agentes | {"orquestador", "espera_humana"}

    desde_el_orquestador = next(
        c for c in definicion.condicionales if c.desde == "orquestador"
    )
    assert set(desde_el_orquestador.destinos) == agentes

    # Etapa 5: cada agente decide al terminar si el turno se detiene.
    for nombre in agentes:
        condicional = next(c for c in definicion.condicionales if c.desde == nombre)
        assert set(condicional.destinos) == {"espera_humana", FIN}
    assert definicion.aristas == (("espera_humana", FIN),)


def test_un_agente_sin_ruta_falla_fuerte_en_vez_de_inventar_una():
    """Solo puede pasar si alguien arma el grafo mal (un agente que no viene
    del orquestador). Mejor que reviente ahi que que el turno corra con la
    ruta de respaldo sin que nadie lo haya decidido."""
    from agora.usecase.agente.grafo import EstadoDelTurno, definir_grafo_del_turno

    agente, _, _, _ = _armar_agente(lambda: [], [], False)
    nodo = definir_grafo_del_turno(agente).nodos["agente_catalogo"]
    conversacion = agente.iniciar()

    with pytest.raises(RuntimeError, match="sin ruta"):
        nodo(EstadoDelTurno(conversacion=conversacion, mensaje="x", historial_previo=()))
