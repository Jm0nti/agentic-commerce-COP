"""`model/agente/gateways/orquestacion.py`: la validacion de topologia, regla por regla.

El puerto no corre nada -- compilar y ejecutar son del adaptador. Lo que si
hace, y es lo que justifica que exista en vez de pasarle un `StateGraph` al
agente, es rechazar un grafo incoherente al CONSTRUIR la definicion, con un
mensaje que dice cual es el problema. Cada regla del `__post_init__` tiene su
prueba aca.
"""

from __future__ import annotations

import pytest

from agora.model.agente.gateways.orquestacion import FIN, AristaCondicional, DefinicionDeGrafo


def _nodo(nombre: str):
    """Un nodo que no hace nada: la topologia se valida sin ejecutar."""
    return lambda estado: estado


def _nodos(*nombres: str) -> dict:
    return {nombre: _nodo(nombre) for nombre in nombres}


def test_un_grafo_minimo_valido_se_construye():
    definicion = DefinicionDeGrafo(
        nodos=_nodos("a"), entrada="a", aristas=(("a", FIN),),
    )

    assert definicion.entrada == "a"
    assert set(definicion.nodos) == {"a"}


def test_un_grafo_con_condicional_a_fin_es_valido():
    definicion = DefinicionDeGrafo(
        nodos=_nodos("a", "b"),
        entrada="a",
        aristas=(("b", FIN),),
        condicionales=(
            AristaCondicional(desde="a", decidir=lambda e: "b", destinos=("b", FIN)),
        ),
    )

    assert definicion.condicionales[0].destinos == ("b", FIN)


def test_un_grafo_sin_nodos_se_rechaza():
    with pytest.raises(RuntimeError, match="sin nodos"):
        DefinicionDeGrafo(nodos={}, entrada="a")


def test_la_entrada_tiene_que_ser_un_nodo():
    with pytest.raises(RuntimeError, match="la entrada 'z' no es un nodo"):
        DefinicionDeGrafo(nodos=_nodos("a"), entrada="z", aristas=(("a", FIN),))


def test_una_arista_no_puede_salir_de_un_nodo_inexistente():
    with pytest.raises(RuntimeError, match="sale de un nodo inexistente"):
        DefinicionDeGrafo(
            nodos=_nodos("a"), entrada="a", aristas=(("a", FIN), ("z", FIN)),
        )


def test_una_arista_no_puede_llegar_a_un_nodo_inexistente():
    with pytest.raises(RuntimeError, match="llega a un nodo inexistente"):
        DefinicionDeGrafo(nodos=_nodos("a"), entrada="a", aristas=(("a", "z"),))


def test_una_condicional_no_puede_salir_de_un_nodo_inexistente():
    with pytest.raises(RuntimeError, match="sale de un nodo inexistente"):
        DefinicionDeGrafo(
            nodos=_nodos("a"),
            entrada="a",
            aristas=(("a", FIN),),
            condicionales=(
                AristaCondicional(desde="z", decidir=lambda e: FIN, destinos=(FIN,)),
            ),
        )


def test_una_condicional_sin_destinos_se_rechaza():
    with pytest.raises(RuntimeError, match="no declara ningun destino"):
        DefinicionDeGrafo(
            nodos=_nodos("a"),
            entrada="a",
            condicionales=(
                AristaCondicional(desde="a", decidir=lambda e: FIN, destinos=()),
            ),
        )


def test_una_condicional_no_puede_repetir_un_destino():
    with pytest.raises(RuntimeError, match="repite un destino"):
        DefinicionDeGrafo(
            nodos=_nodos("a", "b"),
            entrada="a",
            aristas=(("b", FIN),),
            condicionales=(
                AristaCondicional(desde="a", decidir=lambda e: "b", destinos=("b", "b")),
            ),
        )


def test_una_condicional_no_puede_declarar_un_destino_inexistente():
    with pytest.raises(RuntimeError, match="declara el destino 'z'"):
        DefinicionDeGrafo(
            nodos=_nodos("a"),
            entrada="a",
            condicionales=(
                AristaCondicional(desde="a", decidir=lambda e: "z", destinos=("z",)),
            ),
        )


def test_un_nodo_sin_salida_se_rechaza():
    """El turno se colgaria ahi: LangGraph terminaria sin pasar por FIN y el
    estado volveria sin respuesta."""
    with pytest.raises(RuntimeError, match="el nodo 'b' no tiene salida"):
        DefinicionDeGrafo(
            nodos=_nodos("a", "b"), entrada="a", aristas=(("a", "b"),),
        )


def test_un_nodo_con_dos_aristas_fijas_se_rechaza():
    with pytest.raises(RuntimeError, match="el nodo 'a' tiene 2 salidas"):
        DefinicionDeGrafo(
            nodos=_nodos("a", "b"),
            entrada="a",
            aristas=(("a", "b"), ("a", FIN), ("b", FIN)),
        )


def test_un_nodo_no_puede_tener_arista_fija_y_condicional_a_la_vez():
    """Cual gana seria cosa del motor, no del diseno: si la salida depende
    del estado, es condicional y punto."""
    with pytest.raises(RuntimeError, match="el nodo 'a' tiene 2 salidas"):
        DefinicionDeGrafo(
            nodos=_nodos("a", "b"),
            entrada="a",
            aristas=(("a", "b"), ("b", FIN)),
            condicionales=(
                AristaCondicional(desde="a", decidir=lambda e: FIN, destinos=(FIN,)),
            ),
        )


def test_un_nodo_inalcanzable_se_rechaza():
    """Codigo muerto que parece vivo, en el grafo que decide que herramientas
    ve el modelo."""
    with pytest.raises(RuntimeError, match="inalcanzables desde 'a': huerfano"):
        DefinicionDeGrafo(
            nodos=_nodos("a", "huerfano"),
            entrada="a",
            aristas=(("a", FIN), ("huerfano", FIN)),
        )


def test_la_alcanzabilidad_atraviesa_las_condicionales():
    """`c` solo se alcanza por una rama de la condicional de `a`: no es
    huerfano, y la validacion no lo puede confundir con uno."""
    definicion = DefinicionDeGrafo(
        nodos=_nodos("a", "b", "c"),
        entrada="a",
        aristas=(("b", FIN), ("c", FIN)),
        condicionales=(
            AristaCondicional(desde="a", decidir=lambda e: "b", destinos=("b", "c")),
        ),
    )

    assert set(definicion.nodos) == {"a", "b", "c"}


def test_un_ciclo_alcanzable_es_valido():
    """La alcanzabilidad no se confunde con un ciclo: `b` vuelve a `a` y la
    validacion termina igual (es lo que la etapa 4 va a necesitar para que un
    worker devuelva el control al orquestador)."""
    definicion = DefinicionDeGrafo(
        nodos=_nodos("a", "b"),
        entrada="a",
        aristas=(("a", "b"),),
        condicionales=(
            AristaCondicional(desde="b", decidir=lambda e: FIN, destinos=("a", FIN)),
        ),
    )

    assert set(definicion.nodos) == {"a", "b"}
