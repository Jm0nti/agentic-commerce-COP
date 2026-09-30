"""`adaptadores/orquestacion/con_langgraph/`: el compilador real de LangGraph,
con nodos de mentira.

Nada de esto toca el agente ni el dominio -- el punto es exactamente ese: el
adaptador no sabe que viaja por el grafo. Lo que se verifica es lo que
`agente/grafo.py` necesita poder dar por cierto:

  - un camino lineal corre en orden;
  - una condicional elige de verdad (incluida una rama que va a FIN);
  - el objeto de estado que entra es EL MISMO que sale (`is`), porque
    `EstadoDelTurno` lleva adentro una `Conversacion` mutable que se muta
    in place;
  - una excepcion de un nodo se propaga tal cual, sin envolverse.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest

from agora.adaptadores.orquestacion.con_langgraph import CompiladorLangGraph
from agora.model.agente.gateways.orquestacion import FIN, AristaCondicional, DefinicionDeGrafo


@dataclass
class _Caja:
    """Un estado de mentira: mutable, para poder ver la identidad del objeto,
    con un campo que las condicionales pueden mirar."""

    visitados: list[str] = field(default_factory=list)
    rama: str = ""


def _marcador(nombre: str):
    def _nodo(estado: _Caja) -> _Caja:
        estado.visitados.append(nombre)
        return estado

    return _nodo


def _compilar(definicion):
    return CompiladorLangGraph().compilar(definicion)


def test_un_camino_lineal_corre_en_orden():
    grafo = _compilar(
        DefinicionDeGrafo(
            nodos={"a": _marcador("a"), "b": _marcador("b"), "c": _marcador("c")},
            entrada="a",
            aristas=(("a", "b"), ("b", "c"), ("c", FIN)),
        )
    )

    final = grafo.invocar(_Caja())

    assert final.visitados == ["a", "b", "c"]


def test_una_condicional_elige_la_rama_segun_el_estado():
    definicion = DefinicionDeGrafo(
        nodos={"entrada": _marcador("entrada"), "izq": _marcador("izq"), "der": _marcador("der")},
        entrada="entrada",
        aristas=(("izq", FIN), ("der", FIN)),
        condicionales=(
            AristaCondicional(
                desde="entrada", decidir=lambda e: e.rama, destinos=("izq", "der"),
            ),
        ),
    )
    grafo = _compilar(definicion)

    assert grafo.invocar(_Caja(rama="izq")).visitados == ["entrada", "izq"]
    assert grafo.invocar(_Caja(rama="der")).visitados == ["entrada", "der"]


def test_una_condicional_puede_terminar_el_turno_sin_pasar_por_otro_nodo():
    """La rama que va a FIN: es la forma que va a tener "no hace falta otro
    agente" en la etapa 4. FIN es del proyecto -- el adaptador lo traduce al
    END de LangGraph."""
    grafo = _compilar(
        DefinicionDeGrafo(
            nodos={"entrada": _marcador("entrada"), "sigue": _marcador("sigue")},
            entrada="entrada",
            aristas=(("sigue", FIN),),
            condicionales=(
                AristaCondicional(
                    desde="entrada",
                    decidir=lambda e: "sigue" if e.rama == "sigue" else FIN,
                    destinos=("sigue", FIN),
                ),
            ),
        )
    )

    assert grafo.invocar(_Caja(rama="sigue")).visitados == ["entrada", "sigue"]
    assert grafo.invocar(_Caja(rama="corta")).visitados == ["entrada"]


def test_el_objeto_de_estado_conserva_su_identidad():
    """El puente de una sola clave (`{"estado": ...}`) hace que LangGraph
    trate el estado como un valor opaco: no lo copia, no lo mezcla campo por
    campo, no lo serializa. Es lo que permite que `EstadoDelTurno` lleve una
    `Conversacion` mutable adentro."""
    grafo = _compilar(
        DefinicionDeGrafo(
            nodos={"a": _marcador("a")}, entrada="a", aristas=(("a", FIN),),
        )
    )
    caja = _Caja()

    assert grafo.invocar(caja) is caja


def test_un_nodo_que_devuelve_un_estado_nuevo_es_el_que_sigue_viaje():
    """El otro caso: nodos que no mutan sino que devuelven una copia (es lo
    que hace `agente/grafo.py` con `replace`). Lo que sale del grafo es lo
    que devolvio el ultimo nodo, no lo que entro."""
    inicial = _Caja(rama="original")
    grafo = _compilar(
        DefinicionDeGrafo(
            nodos={"a": lambda e: replace(e, rama="cambiada")},
            entrada="a",
            aristas=(("a", FIN),),
        )
    )

    final = grafo.invocar(inicial)

    assert final is not inicial
    assert final.rama == "cambiada"
    assert inicial.rama == "original"


def test_una_excepcion_de_un_nodo_se_propaga_tal_cual():
    """Sin envolver: si `ejecutar_turno` levanta `LimiteDeTurnosExcedido`,
    `entradas/api/app.py` lo tiene que seguir viendo como esa excepcion y no
    como un error del motor de grafos."""

    class _ErrorDelNodo(Exception):
        pass

    def _revienta(estado):
        raise _ErrorDelNodo("el nodo fallo")

    grafo = _compilar(
        DefinicionDeGrafo(nodos={"a": _revienta}, entrada="a", aristas=(("a", FIN),))
    )

    with pytest.raises(_ErrorDelNodo, match="el nodo fallo"):
        grafo.invocar(_Caja())


def test_compilar_dos_veces_da_grafos_independientes():
    """`AgenteEnGrafo` compila una vez al construirse; dos agentes distintos
    no pueden compartir estado del motor."""
    definicion = DefinicionDeGrafo(
        nodos={"a": _marcador("a")}, entrada="a", aristas=(("a", FIN),),
    )
    compilador = CompiladorLangGraph()

    uno, otro = compilador.compilar(definicion), compilador.compilar(definicion)

    assert uno is not otro
    assert uno.invocar(_Caja()).visitados == ["a"]
    assert otro.invocar(_Caja()).visitados == ["a"]
