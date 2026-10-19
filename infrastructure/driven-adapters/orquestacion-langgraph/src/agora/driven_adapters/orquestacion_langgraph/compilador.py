"""El unico modulo de `agora/` que importa LangGraph.

Traduce una `DefinicionDeGrafo` del puerto a un `StateGraph`, y devuelve algo
que cumple `GrafoCompilado`. Nada de LangGraph sale de aca: ni un tipo, ni
`START`/`END`, ni el diccionario del estado.

EL PUENTE DE UNA SOLA CLAVE
-----------------------------
LangGraph quiere un esquema de estado (un `TypedDict`) y mezcla lo que cada
nodo devuelve en ese diccionario, clave por clave. Este adaptador declara
UNA sola clave, `estado`, y mete adentro el objeto del proyecto tal cual.

Con eso, LangGraph nunca inspecciona ni reconstruye el estado del turno:
lo pasa de un nodo al siguiente como un valor opaco. Verificado (ver
`tests/driven_adapters/test_adaptador_orquestacion_langgraph.py`): el objeto que entra al
grafo es el MISMO objeto que sale -- `is`, no `==` -- y una excepcion de un
nodo se propaga sin envolverse. Es lo que permite que `EstadoDelTurno` sea
un dataclass congelado del proyecto, con una `Conversacion` mutable adentro,
en vez de un diccionario que haya que serializar y volver a armar.

POR QUE EL PAQUETE SE LLAMA `con_langgraph` Y NO `langgraph`
--------------------------------------------------------------
Un paquete `driven_adapters/langgraph/` sombrearia a la
libreria para cualquier import relativo de adentro. Mismo criterio que
`driven_adapters/recuperacion_langchain/` en la etapa 2.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ...model.agente.gateways.orquestacion import (
    FIN,
    AristaCondicional,
    DefinicionDeGrafo,
    GrafoCompilado,
    Nodo,
)


class _EstadoPuente(TypedDict):
    """Una sola clave, a proposito. Ver "EL PUENTE DE UNA SOLA CLAVE"."""

    estado: Any


def _destino(nombre: str) -> str:
    """El FIN del proyecto es el END de LangGraph. La traduccion vive aca y
    en ningun otro lado."""
    return END if nombre == FIN else nombre


def _envolver_nodo(nodo: Nodo[Any]):
    def _correr(puente: _EstadoPuente) -> _EstadoPuente:
        return {"estado": nodo(puente["estado"])}

    return _correr


def _envolver_decision(condicional: AristaCondicional[Any]):
    """Devuelve el nombre del destino tal como lo declara el puerto; el
    `path_map` de LangGraph lo convierte en su propio nombre de nodo."""

    def _decidir(puente: _EstadoPuente) -> str:
        return condicional.decidir(puente["estado"])

    return _decidir


class _GrafoLangGraph:
    def __init__(self, compilado: Any) -> None:
        self._compilado = compilado

    def invocar(self, estado: Any) -> Any:
        return self._compilado.invoke({"estado": estado})["estado"]


class CompiladorLangGraph:
    """`CompiladorDeGrafos` con LangGraph detras.

    Sin checkpointer, a proposito (decision 7 de
    `docs/arquitectura-agentes/arquitectura-agentes-langgraph.md`): la verdad
    de negocio son las tablas de dominio, y el estado conversacional de un
    turno no sobrevive al turno. El checkpointer entra con `interrupt()`, en
    la etapa 5."""

    def compilar(self, definicion: DefinicionDeGrafo[Any]) -> GrafoCompilado[Any]:
        grafo = StateGraph(_EstadoPuente)
        for nombre, nodo in definicion.nodos.items():
            grafo.add_node(nombre, _envolver_nodo(nodo))
        grafo.add_edge(START, definicion.entrada)
        for desde, hasta in definicion.aristas:
            grafo.add_edge(desde, _destino(hasta))
        for condicional in definicion.condicionales:
            grafo.add_conditional_edges(
                condicional.desde,
                _envolver_decision(condicional),
                {destino: _destino(destino) for destino in condicional.destinos},
            )
        return _GrafoLangGraph(grafo.compile())
