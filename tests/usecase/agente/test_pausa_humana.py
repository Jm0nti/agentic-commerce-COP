"""El turno se detiene en un punto explicito hasta que una persona lo
resuelve (migracion a agentes, etapa 5, decision 6).

Las dos propiedades que este archivo protege:

1. **`espera_humana` no hace nada mas que detenerse.** Es una regla de
   dinero, no un detalle: un motor que reanude re-ejecutando el nodo --
   es lo que hace `interrupt()` de LangGraph, verificado -- volveria a
   correr todo lo que hubiera antes del corte. Con el nodo vacio, volver a
   correrlo no repite ningun cobro.
2. **El aviso que lee el modelo se arma en un solo lugar.** Antes habia
   cuatro sitios escribiendolo a mano; cada uno tenia que acordarse del
   formato porque del otro lado el modelo lee los ids del texto.
"""

from __future__ import annotations

import json

import pytest

from agora.driven_adapters.orquestacion_langgraph import CompiladorLangGraph
from agora.usecase.agente.conversacion import Agente
from agora.usecase.agente.grafo import (
    NODO_ESPERA_HUMANA,
    AgenteEnGrafo,
    EstadoDelTurno,
    definir_grafo_del_turno,
)
from agora.usecase.agente.herramientas import CATALOGO_DE_HERRAMIENTAS, construir_herramientas
from agora.model.agente.intencion import (
    ClasificacionDeIntencion,
    OrigenDeClasificacion,
    TipoDeIntencion,
)
from agora.usecase.agente.pausa import DecisionHumana, PausaDelTurno, TipoDePausa, detectar_pausa
from agora.model.agente.gateways.modelo_lenguaje import LlamadaHerramienta, Mensaje, RespuestaModelo
from agora.model.agente.gateways.orquestacion import PausaRequerida

PROPUESTA = {
    "carrito_id": "car_1",
    "total_cop": 18_000,
    "propuesta": {
        "propuesta_id": "prp_1",
        "carrito_id": "car_1",
        "comercio_id": "com_1",
        "monto_max_cop": 18_000,
        "usos_max": 1,
        "vigencia_minutos": 30,
        "justificacion": "compra de prueba",
    },
}
COBRO_ESPERANDO = {
    "intencion_id": "int_1",
    "mandato_id": "mnd_1",
    "carrito_id": "car_1",
    "ejecutado": False,
    "motivo": "esperando_confirmacion_humana",
    "esperando_confirmacion": True,
}


def _tool(nombre: str, cuerpo: dict) -> Mensaje:
    return Mensaje(
        rol="tool", contenido=json.dumps(cuerpo), id_llamada="c1", nombre_herramienta=nombre,
    )


# --------------------------------------------------------------------------- #
# detectar_pausa: de lo que devolvieron las herramientas, no de una bandera
# --------------------------------------------------------------------------- #


def test_un_armar_carrito_deja_una_pausa_de_firma():
    pausa = detectar_pausa([_tool("armar_carrito", PROPUESTA)])

    assert pausa == PausaDelTurno(
        tipo=TipoDePausa.FIRMA_DE_PROPUESTA,
        propuesta_id="prp_1", carrito_id="car_1", comercio_id="com_1",
        monto_cop=18_000, justificacion="compra de prueba",
    )


def test_un_pagar_que_espera_confirmacion_deja_una_pausa_de_cobro():
    pausa = detectar_pausa([_tool("pagar", COBRO_ESPERANDO)])

    assert pausa is not None
    assert pausa.tipo is TipoDePausa.CONFIRMACION_DE_COBRO
    assert pausa.intencion_id == "int_1"
    assert pausa.mandato_id == "mnd_1"


def test_un_pagar_ya_resuelto_no_deja_pausa():
    """Un cobro aprobado no necesita que nadie decida nada."""
    resuelto = {**COBRO_ESPERANDO, "ejecutado": True, "esperando_confirmacion": False}

    assert detectar_pausa([_tool("pagar", resuelto)]) is None


def test_un_pagar_pendiente_de_la_pasarela_no_deja_pausa():
    """'PENDING' lo resuelve la pasarela sola (el sondeo), no una persona:
    no hay popup que mostrar."""
    pendiente = {**COBRO_ESPERANDO, "motivo": "PENDING", "esperando_confirmacion": False}

    assert detectar_pausa([_tool("pagar", pendiente)]) is None


def test_un_armar_carrito_que_fallo_no_deja_pausa():
    """`Agente._ejecutar` traduce un `ErrorDeDominio` a `{"tipo", "mensaje"}`
    -- no hay propuesta que firmar."""
    error = {"tipo": "ProductoNoDisponible", "mensaje": "esta agotado"}

    assert detectar_pausa([_tool("armar_carrito", error)]) is None


def test_un_turno_sin_herramientas_de_dinero_no_deja_pausa():
    assert detectar_pausa([]) is None
    assert detectar_pausa([Mensaje(rol="assistant", contenido="hola")]) is None


# --------------------------------------------------------------------------- #
# El aviso, en un solo lugar
# --------------------------------------------------------------------------- #


def test_el_aviso_de_firma_lleva_los_ids_que_el_modelo_necesita():
    aviso = DecisionHumana(
        tipo=TipoDePausa.FIRMA_DE_PROPUESTA, aprobada=True,
        propuesta_id="prp_1", carrito_id="car_1", mandato_id="mnd_1",
    ).como_aviso()

    assert "mandato_id=mnd_1" in aviso
    assert "carrito_id=car_1" in aviso
    assert "pagar()" in aviso


def test_el_aviso_de_rechazo_dice_que_no_hay_mandato_ni_pago():
    aviso = DecisionHumana(
        tipo=TipoDePausa.FIRMA_DE_PROPUESTA, aprobada=False, propuesta_id="prp_1",
    ).como_aviso()

    assert "rechazo la propuesta prp_1" in aviso
    assert "no hay mandato ni pago" in aviso
    assert "mandato_id=" not in aviso


@pytest.mark.parametrize(
    "aprobada,veredicto", [(True, "aprobo"), (False, "rechazo")],
)
def test_el_aviso_de_confirmacion_dice_el_veredicto_y_el_desenlace(aprobada, veredicto):
    aviso = DecisionHumana(
        tipo=TipoDePausa.CONFIRMACION_DE_COBRO, aprobada=aprobada,
        intencion_id="int_1", estado="APPROVED", ejecutado=True,
    ).como_aviso()

    assert veredicto in aviso
    assert "int_1" in aviso
    assert "consultar_estado" in aviso


def test_el_aviso_automatico_dice_que_fue_el_webhook():
    """La cuarta decision externa: nadie hizo click."""
    aviso = DecisionHumana(
        tipo=TipoDePausa.CONFIRMACION_DE_COBRO, aprobada=True,
        intencion_id="int_1", estado="aprobado", automatica=True,
    ).como_aviso()

    assert "webhook" in aviso
    assert "int_1" in aviso


# --------------------------------------------------------------------------- #
# El grafo: el nodo dedicado, y que no hace nada
# --------------------------------------------------------------------------- #


class _ModeloGuionado:
    def __init__(self, respuestas):
        self._respuestas = list(respuestas)
        self.vueltas = 0

    def generar(self, sistema, instruccion):
        raise AssertionError("no se usa")

    def responder(self, mensajes, herramientas):
        self.vueltas += 1
        return self._respuestas.pop(0)


class _ClasificadorFijo:
    def __init__(self, *intenciones):
        self._pendientes = list(intenciones)

    def clasificar(self, mensaje, historial=()):
        return ClasificacionDeIntencion(
            intencion=self._pendientes.pop(0), origen=OrigenDeClasificacion.REGLAS,
            confianza=1.0, motivo="prueba",
        )


class _Efectos:
    """Cuenta cuantas veces se ejecuto de verdad cada herramienta."""

    def __init__(self):
        self.corridas: list[str] = []

    def herramientas(self):
        def funcion(nombre):
            def _f(**_):
                self.corridas.append(nombre)
                return dict(PROPUESTA) if nombre == "armar_carrito" else {"ok": True}
            return _f
        return construir_herramientas(**{n: funcion(n) for n in CATALOGO_DE_HERRAMIENTAS})


def _compra(respuestas, intenciones, en_grafo=True):
    efectos = _Efectos()
    base = Agente(
        modelo=_ModeloGuionado(respuestas),
        herramientas=efectos.herramientas(),
        clasificador=_ClasificadorFijo(*intenciones),
    )
    agente = AgenteEnGrafo(base, CompiladorLangGraph()) if en_grafo else base
    return agente, efectos


_LLAMA_ARMAR = RespuestaModelo(
    contenido=None,
    llamadas=(
        LlamadaHerramienta(
            id="c1", nombre="armar_carrito",
            argumentos={"comercio_id": "com_1", "items": [{"producto_id": "prd_1"}]},
        ),
    ),
)


def test_el_nodo_de_espera_esta_en_el_grafo_y_no_tiene_salida_a_otro_nodo():
    agente = Agente(modelo=_ModeloGuionado([]), herramientas=_Efectos().herramientas())

    definicion = definir_grafo_del_turno(agente)

    assert NODO_ESPERA_HUMANA in definicion.nodos
    # La unica arista fija del grafo: no se sale de la espera hacia otro
    # nodo, se sale levantando.
    assert definicion.aristas == ((NODO_ESPERA_HUMANA, "__fin__"),)


def test_el_nodo_de_espera_solo_levanta_y_no_toca_la_conversacion():
    """LA prueba de seguridad de esta etapa. Si algun dia el motor reanuda
    re-ejecutando el nodo, esto es lo que garantiza que no se repita nada."""
    agente = Agente(modelo=_ModeloGuionado([]), herramientas=_Efectos().herramientas())
    nodo = definir_grafo_del_turno(agente).nodos[NODO_ESPERA_HUMANA]
    conversacion = agente.iniciar()
    antes = list(conversacion.mensajes)
    pausa = PausaDelTurno(tipo=TipoDePausa.FIRMA_DE_PROPUESTA, propuesta_id="prp_1")
    estado = EstadoDelTurno(
        conversacion=conversacion, mensaje="x", historial_previo=(), pausa=pausa,
    )

    for _ in range(3):  # re-ejecutarlo es inofensivo, esa es la propiedad
        with pytest.raises(PausaRequerida):
            nodo(estado)

    assert conversacion.mensajes == antes


def test_el_nodo_de_espera_sin_pausa_es_un_bug_del_grafo():
    agente = Agente(modelo=_ModeloGuionado([]), herramientas=_Efectos().herramientas())
    nodo = definir_grafo_del_turno(agente).nodos[NODO_ESPERA_HUMANA]

    with pytest.raises(RuntimeError, match="sin nada que esperar"):
        nodo(EstadoDelTurno(conversacion=agente.iniciar(), mensaje="x", historial_previo=()))


# --------------------------------------------------------------------------- #
# El turno completo: detenerse y seguir
# --------------------------------------------------------------------------- #


EN_LOS_DOS_CAMINOS = pytest.mark.parametrize(
    "en_grafo", [False, True], ids=["directo", "grafo"],
)


@EN_LOS_DOS_CAMINOS
def test_un_turno_que_arma_una_propuesta_queda_en_pausa(en_grafo):
    agente, efectos = _compra(
        [_LLAMA_ARMAR, RespuestaModelo(contenido="te arme la propuesta, firmala")],
        [TipoDeIntencion.CARRITO_PAGO], en_grafo=en_grafo,
    )
    conversacion = agente.iniciar()

    respuesta = agente.turno(conversacion, "quiero comprar")

    # La persona ve la respuesta ANTES de decidir: tiene que poder leer que
    # le proponen.
    assert respuesta == "te arme la propuesta, firmala"
    assert conversacion.pausa is not None
    assert conversacion.pausa.tipo is TipoDePausa.FIRMA_DE_PROPUESTA
    assert conversacion.pausa.propuesta_id == "prp_1"
    assert efectos.corridas == ["armar_carrito"]


@EN_LOS_DOS_CAMINOS
def test_un_turno_sin_dinero_no_queda_en_pausa(en_grafo):
    agente, _ = _compra(
        [RespuestaModelo(contenido="hay dos tiendas")], [TipoDeIntencion.CATALOGO],
        en_grafo=en_grafo,
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "que tiendas hay")

    assert conversacion.pausa is None


@EN_LOS_DOS_CAMINOS
def test_reanudar_limpia_la_pausa_y_no_repite_el_efecto(en_grafo):
    """La propiedad de dinero, de punta a punta: reanudar no vuelve a armar
    el carrito."""
    agente, efectos = _compra(
        [
            _LLAMA_ARMAR,
            RespuestaModelo(contenido="te arme la propuesta, firmala"),
            RespuestaModelo(contenido="listo, ya cobre"),
        ],
        [TipoDeIntencion.CARRITO_PAGO, TipoDeIntencion.CARRITO_PAGO], en_grafo=en_grafo,
    )
    conversacion = agente.iniciar()
    agente.turno(conversacion, "quiero comprar")

    respuesta = agente.reanudar(
        conversacion,
        DecisionHumana(
            tipo=TipoDePausa.FIRMA_DE_PROPUESTA, aprobada=True,
            propuesta_id="prp_1", carrito_id="car_1", mandato_id="mnd_1",
        ),
    )

    assert respuesta == "listo, ya cobre"
    assert conversacion.pausa is None
    assert efectos.corridas == ["armar_carrito"]  # UNA sola vez


@EN_LOS_DOS_CAMINOS
def test_el_aviso_de_la_decision_entra_a_la_conversacion(en_grafo):
    agente, _ = _compra(
        [
            _LLAMA_ARMAR,
            RespuestaModelo(contenido="firmala"),
            RespuestaModelo(contenido="listo"),
        ],
        [TipoDeIntencion.CARRITO_PAGO, TipoDeIntencion.CARRITO_PAGO], en_grafo=en_grafo,
    )
    conversacion = agente.iniciar()
    agente.turno(conversacion, "quiero comprar")

    agente.reanudar(
        conversacion,
        DecisionHumana(
            tipo=TipoDePausa.FIRMA_DE_PROPUESTA, aprobada=True,
            propuesta_id="prp_1", carrito_id="car_1", mandato_id="mnd_1",
        ),
    )

    usuarios = [m.contenido for m in conversacion.mensajes if m.rol == "user"]
    assert "mandato_id=mnd_1" in usuarios[-1]


@EN_LOS_DOS_CAMINOS
def test_un_segundo_turno_comun_limpia_la_pausa_vieja(en_grafo):
    """Si la persona ignora el popup y sigue escribiendo, la pausa del turno
    anterior no puede quedar colgada: dispararia el popup de nuevo."""
    agente, _ = _compra(
        [
            _LLAMA_ARMAR,
            RespuestaModelo(contenido="firmala"),
            RespuestaModelo(contenido="hay dos tiendas"),
        ],
        [TipoDeIntencion.CARRITO_PAGO, TipoDeIntencion.CATALOGO], en_grafo=en_grafo,
    )
    conversacion = agente.iniciar()
    agente.turno(conversacion, "quiero comprar")
    assert conversacion.pausa is not None

    agente.turno(conversacion, "mejor mostrame las tiendas")

    assert conversacion.pausa is None


def test_la_pausa_queda_en_la_traza():
    """El momento exacto en que el agente deja de decidir merece quedar
    escrito, no solo dispararle un popup a alguien."""

    class _Bitacora:
        def __init__(self):
            self.cuerpos = []

        def anotar(self, evento, cuerpo):
            self.cuerpos.append(cuerpo)

    bitacora = _Bitacora()
    efectos = _Efectos()
    base = Agente(
        modelo=_ModeloGuionado([_LLAMA_ARMAR, RespuestaModelo(contenido="firmala")]),
        herramientas=efectos.herramientas(),
        clasificador=_ClasificadorFijo(TipoDeIntencion.CARRITO_PAGO),
        bitacora=bitacora,
    )
    agente = AgenteEnGrafo(base, CompiladorLangGraph())

    agente.turno(agente.iniciar(), "quiero comprar")

    pausa = bitacora.cuerpos[-1]["pausa"]
    assert pausa["tipo"] == "firma_de_propuesta"
    assert pausa["propuesta_id"] == "prp_1"
