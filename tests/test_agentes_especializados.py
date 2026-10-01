"""Los agentes especializados y la arista condicional del grafo (migracion a
agentes, etapa 4).

Dos garantias nuevas, y una prueba por cada una:

1. cada agente valida su lista blanca AL CONSTRUIRSE, nodo por nodo;
2. un agente rechaza una ruta que no es la suya -- un bug de enrutamiento
   revienta en vez de correr el turno con las herramientas de otro.

Y la tercera, que es la que hace que la condicional valga: **los siete
destinos son alcanzables y cada uno ejecuta un nodo distinto**.
"""

from __future__ import annotations

import pytest

from agora.driven_adapters.orquestacion_langgraph import CompiladorLangGraph
from agora.usecase.agente.agentes import (
    NOMBRE_DEL_RESPALDO,
    AgenteEspecializado,
    RutaDeOtroAgente,
    construir_agentes,
    nodos_por_agente,
    nombre_del_agente,
    toda_intencion_tiene_agente,
)
from agora.usecase.agente.conversacion import Agente
from agora.usecase.agente.grafo import AgenteEnGrafo, definir_grafo_del_turno, nodo_del_agente
from agora.usecase.agente.herramientas import (
    CATALOGO_DE_HERRAMIENTAS,
    HERRAMIENTAS_POR_NODO,
    construir_herramientas,
)
from agora.model.agente.intencion import (
    ClasificacionDeIntencion,
    OrigenDeClasificacion,
    TipoDeIntencion,
)
from agora.usecase.agente.nodos import RUTA_DE_RESPALDO, RUTAS, Ruta, ruta_para
from agora.model.agente.gateways.modelo_lenguaje import Mensaje, RespuestaModelo


def _funcion(*_a, **_k):
    return {"ok": True}


def _todas():
    return construir_herramientas(**{n: _funcion for n in CATALOGO_DE_HERRAMIENTAS})


def _decidida(intencion: TipoDeIntencion) -> ClasificacionDeIntencion:
    return ClasificacionDeIntencion(
        intencion=intencion, origen=OrigenDeClasificacion.REGLAS, confianza=1.0, motivo="prueba",
    )


class _ModeloQueContesta:
    def __init__(self) -> None:
        self.definiciones: list[set[str]] = []

    def generar(self, sistema, instruccion):
        raise AssertionError("el clasificador de estas pruebas es fijo")

    def responder(self, mensajes, herramientas):
        self.definiciones.append({d.nombre for d in herramientas})
        return RespuestaModelo(contenido="ok")


class _ClasificadorFijo:
    def __init__(self, *intenciones) -> None:
        self._pendientes = list(intenciones)

    def clasificar(self, mensaje, historial=()):
        intencion = self._pendientes.pop(0)
        if intencion is None:
            return ClasificacionDeIntencion.respaldo("prueba")
        return _decidida(intencion)


def _agente_en_grafo(*intenciones):
    modelo = _ModeloQueContesta()
    agente = Agente(
        modelo=modelo, herramientas=_todas(), clasificador=_ClasificadorFijo(*intenciones),
    )
    return AgenteEnGrafo(agente, CompiladorLangGraph()), modelo


# -- la tabla de agentes sale de RUTAS, no de una copia ---------------------- #


def test_hay_un_agente_por_intencion_mas_el_respaldo():
    tabla = nodos_por_agente()

    assert set(tabla) == {i.value for i in TipoDeIntencion} | {NOMBRE_DEL_RESPALDO}
    assert toda_intencion_tiene_agente()


def test_los_nodos_de_cada_agente_son_los_de_su_ruta():
    """Si algun dia alguien agrega una tabla paralela, esto falla."""
    tabla = nodos_por_agente()

    for intencion, nodos in RUTAS.items():
        assert tabla[intencion.value] == nodos
    assert tabla[NOMBRE_DEL_RESPALDO] == RUTA_DE_RESPALDO


def test_el_agente_de_compra_conserva_las_herramientas_de_catalogo():
    """Decision 5 y el hallazgo de esta etapa: la arista `catalogo ->
    carrito_pago` no se implemento, asi que el agente de compra sigue
    teniendo las dos listas blancas."""
    agentes = construir_agentes(_todas())

    assert agentes["carrito_pago"].herramientas == set(
        HERRAMIENTAS_POR_NODO["catalogo"]
    ) | set(HERRAMIENTAS_POR_NODO["carrito_pago"])


def test_el_agente_de_soporte_no_tiene_ninguna_herramienta():
    assert construir_agentes(_todas())["soporte"].herramientas == frozenset()


def test_el_agente_de_respaldo_es_el_agente_de_antes():
    assert construir_agentes(_todas())[NOMBRE_DEL_RESPALDO].herramientas == set(
        CATALOGO_DE_HERRAMIENTAS
    )


# -- garantia 1: cada agente valida su lista blanca al construirse ----------- #


def test_construir_agentes_valida_los_siete():
    agentes = construir_agentes(_todas())

    assert set(agentes) == set(nodos_por_agente())


def test_un_agente_con_un_nodo_inexistente_no_se_puede_construir():
    with pytest.raises(RuntimeError, match="nodo desconocido"):
        AgenteEspecializado(nombre="tesoreria", nodos=("tesoreria",)).verificar(_todas())


def test_un_agente_sin_nodos_no_se_puede_construir():
    with pytest.raises(RuntimeError, match="no declara ningun nodo"):
        AgenteEspecializado(nombre="fantasma", nodos=()).verificar(_todas())


def test_armar_el_grafo_valida_las_listas_blancas():
    """La validacion corre al DEFINIR el grafo, no en la primera charla."""
    agente = Agente(modelo=_ModeloQueContesta(), herramientas=_todas())

    definicion = definir_grafo_del_turno(agente)

    # un nodo por agente, mas el orquestador y el de espera humana (etapa 5)
    assert len(definicion.nodos) == len(nodos_por_agente()) + 2


# -- garantia 2: un agente rechaza la ruta de otro --------------------------- #


def test_un_agente_rechaza_la_ruta_de_otro():
    soporte = construir_agentes(_todas())["soporte"]
    ruta_de_compra = ruta_para(_decidida(TipoDeIntencion.CARRITO_PAGO))

    with pytest.raises(RutaDeOtroAgente, match="soporte"):
        soporte.ruta_propia(ruta_de_compra)


def test_un_agente_acepta_la_suya():
    agentes = construir_agentes(_todas())

    for intencion in TipoDeIntencion:
        agentes[intencion.value].ruta_propia(ruta_para(_decidida(intencion)))
    agentes[NOMBRE_DEL_RESPALDO].ruta_propia(ruta_para(None))


def test_el_nodo_del_grafo_rechaza_una_ruta_ajena():
    """El bug que un grafo hace posible y que con un solo worker no existia:
    enrutar mal. Mejor que reviente que que soporte corra con `pagar`."""
    from agora.usecase.agente.grafo import EstadoDelTurno

    agente = Agente(modelo=_ModeloQueContesta(), herramientas=_todas())
    nodo = definir_grafo_del_turno(agente).nodos["agente_soporte"]
    conversacion = agente.iniciar()

    with pytest.raises(RutaDeOtroAgente):
        nodo(
            EstadoDelTurno(
                conversacion=conversacion,
                mensaje="x",
                historial_previo=(),
                ruta=ruta_para(_decidida(TipoDeIntencion.CARRITO_PAGO)),
            )
        )


# -- garantia 3: los siete destinos son reales ------------------------------- #


def test_nombre_del_agente_por_intencion():
    for intencion in TipoDeIntencion:
        assert nombre_del_agente(ruta_para(_decidida(intencion))) == intencion.value


def test_nombre_del_agente_sin_decision_es_respaldo():
    assert nombre_del_agente(ruta_para(None)) == NOMBRE_DEL_RESPALDO
    assert nombre_del_agente(ruta_para(ClasificacionDeIntencion.respaldo("x"))) == (
        NOMBRE_DEL_RESPALDO
    )


def test_la_condicional_declara_exactamente_los_siete_destinos():
    agente = Agente(modelo=_ModeloQueContesta(), herramientas=_todas())

    condicional = definir_grafo_del_turno(agente).condicionales[0]

    assert set(condicional.destinos) == {
        nodo_del_agente(nombre) for nombre in nodos_por_agente()
    }


@pytest.mark.parametrize("intencion", list(TipoDeIntencion))
def test_cada_intencion_llega_a_su_agente_y_recibe_su_lista_blanca(intencion):
    """La condicional no es utileria: cada destino sirve herramientas
    distintas. Esta prueba falla si el enrutador manda todo al mismo lado."""
    corredor, modelo = _agente_en_grafo(intencion)

    corredor.turno(corredor.iniciar(), "un mensaje")

    assert modelo.definiciones[-1] == set(ruta_para(_decidida(intencion)).herramientas)


def test_el_respaldo_tambien_es_un_destino_alcanzable():
    corredor, modelo = _agente_en_grafo(None)

    corredor.turno(corredor.iniciar(), "mmm")

    assert modelo.definiciones[-1] == set(CATALOGO_DE_HERRAMIENTAS)


def test_turnos_seguidos_van_a_agentes_distintos():
    """Un grafo compilado una sola vez tiene que poder enrutar cada turno a
    un destino diferente."""
    corredor, modelo = _agente_en_grafo(
        TipoDeIntencion.CATALOGO, TipoDeIntencion.ESTADO, TipoDeIntencion.SOPORTE,
    )
    conversacion = corredor.iniciar()

    corredor.turno(conversacion, "que tiendas hay")
    corredor.turno(conversacion, "como va mi pago")
    corredor.turno(conversacion, "que es un mandato")

    assert modelo.definiciones == [
        {"buscar_comercios", "buscar_productos", "ver_producto"},
        {"consultar_estado"},
        set(),
    ]
