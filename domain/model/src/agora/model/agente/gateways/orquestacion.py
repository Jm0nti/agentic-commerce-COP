"""El puerto de orquestacion (migracion a agentes, etapa 3).

Un grafo de nodos, dicho sin un solo tipo de LangGraph. Es lo que permite
que `usecase/agente/grafo.py` arme el turno como grafo sin importar la libreria --
la regla de dependencia lo prohibe (`test_fronteras.py`), y con razon: el
dia que LangGraph cambie de API o se reemplace, el que cambia es el
adaptador, no el agente.

    DefinicionDeGrafo      que nodos hay, por cual se entra, como se conectan
    CompiladorDeGrafos     definicion -> GrafoCompilado   (hoy LangGraph,
                           `driven_adapters/orquestacion_langgraph/`)
    GrafoCompilado         invocar(estado) -> estado

POR QUE EL ESTADO ES UN `TypeVar`
-----------------------------------
El estado de un turno (`usecase/agente/grafo.py:EstadoDelTurno`) vive en `usecase/agente/`,
y `model/<agregado>/gateways/` no puede importar `usecase/agente/`. Tampoco tendria que: a este puerto
no le importa QUE viaja por el grafo, solo que cada nodo reciba un estado y
devuelva un estado. Quien usa el puerto fija `E`; el adaptador lo trata como
una caja cerrada y nunca lo toca.

POR QUE LA TOPOLOGIA SE VALIDA ACA Y NO EN EL ADAPTADOR
--------------------------------------------------------
Es lo que hace que el puerto valga la pena, y no sea una capa de traduccion
vacia. Un grafo mal armado -- un nodo inalcanzable, un nodo sin salida, dos
salidas para el mismo nodo -- es un error de diseno del turno, no un detalle
de LangGraph: se tiene que ver igual con cualquier motor detras, y se tiene
que ver al CONSTRUIR la definicion, no en la primera charla de una persona.
Mismo criterio que `usecase/agente/herramientas.py:validar_asignacion_por_nodo`
(y por eso tambien `RuntimeError`): si la estructura declarada en codigo es
incoherente, el proceso no levanta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, Mapping, Protocol, TypeVar

E = TypeVar("E")

# El unico destino que no es un nodo: "aca termina el turno". Es del
# proyecto, no de LangGraph (que usa su propio `END`); el adaptador traduce
# uno en el otro. Asi este puerto no hereda ninguna constante de la libreria.
FIN = "__fin__"

Nodo = Callable[[E], E]


@dataclass(frozen=True)
class AristaCondicional(Generic[E]):
    """La salida de `desde` la elige `decidir`, en tiempo de ejecucion, entre
    `destinos`. Los destinos se declaran de antemano -- y no se deducen de lo
    que `decidir` devuelva -- para que la topologia del grafo se pueda
    validar y dibujar sin correrlo."""

    desde: str
    decidir: Callable[[E], str]
    destinos: tuple[str, ...]


@dataclass(frozen=True)
class DefinicionDeGrafo(Generic[E]):
    """Un grafo listo para compilar. Se valida al construirse."""

    nodos: Mapping[str, Nodo[E]]
    entrada: str
    aristas: tuple[tuple[str, str], ...] = ()
    condicionales: tuple[AristaCondicional[E], ...] = ()

    def __post_init__(self) -> None:
        if not self.nodos:
            raise RuntimeError("un grafo sin nodos no orquesta nada")
        if self.entrada not in self.nodos:
            raise RuntimeError(
                f"la entrada '{self.entrada}' no es un nodo del grafo "
                f"(nodos: {', '.join(sorted(self.nodos))})"
            )

        for desde, hasta in self.aristas:
            if desde not in self.nodos:
                raise RuntimeError(f"la arista '{desde} -> {hasta}' sale de un nodo inexistente")
            if hasta != FIN and hasta not in self.nodos:
                raise RuntimeError(
                    f"la arista '{desde} -> {hasta}' llega a un nodo inexistente "
                    f"(para terminar el turno, use FIN)"
                )

        for condicional in self.condicionales:
            if condicional.desde not in self.nodos:
                raise RuntimeError(
                    f"la condicional de '{condicional.desde}' sale de un nodo inexistente"
                )
            if not condicional.destinos:
                raise RuntimeError(
                    f"la condicional de '{condicional.desde}' no declara ningun destino"
                )
            if len(set(condicional.destinos)) != len(condicional.destinos):
                raise RuntimeError(
                    f"la condicional de '{condicional.desde}' repite un destino: "
                    f"{', '.join(condicional.destinos)}"
                )
            for destino in condicional.destinos:
                if destino != FIN and destino not in self.nodos:
                    raise RuntimeError(
                        f"la condicional de '{condicional.desde}' declara el destino "
                        f"'{destino}', que no es un nodo del grafo"
                    )

        self._validar_una_sola_salida_por_nodo()
        self._validar_alcanzabilidad()

    def _validar_una_sola_salida_por_nodo(self) -> None:
        """Exactamente una: ni cero (el turno se colgaria en ese nodo) ni dos
        (cual gana seria cosa del motor, no del diseno). Una arista fija y una
        condicional desde el mismo nodo tampoco: si la salida depende del
        estado, es condicional y punto."""
        salidas: dict[str, int] = {nombre: 0 for nombre in self.nodos}
        for desde, _ in self.aristas:
            salidas[desde] += 1
        for condicional in self.condicionales:
            salidas[condicional.desde] += 1
        for nombre, cuantas in sorted(salidas.items()):
            if cuantas == 0:
                raise RuntimeError(
                    f"el nodo '{nombre}' no tiene salida: agregue una arista "
                    f"(a otro nodo o a FIN) o una condicional"
                )
            if cuantas > 1:
                raise RuntimeError(
                    f"el nodo '{nombre}' tiene {cuantas} salidas: cada nodo tiene "
                    "exactamente una, fija o condicional, nunca las dos"
                )

    def _validar_alcanzabilidad(self) -> None:
        """Un nodo que no se alcanza desde la entrada es codigo muerto que
        parece vivo -- el peor tipo, en un grafo que decide que herramientas
        ve el modelo."""
        vistos = {self.entrada}
        pendientes = [self.entrada]
        while pendientes:
            actual = pendientes.pop()
            for destino in self._destinos_de(actual):
                if destino != FIN and destino not in vistos:
                    vistos.add(destino)
                    pendientes.append(destino)
        huerfanos = sorted(set(self.nodos) - vistos)
        if huerfanos:
            raise RuntimeError(
                f"nodos inalcanzables desde '{self.entrada}': {', '.join(huerfanos)}"
            )

    def _destinos_de(self, nodo: str) -> tuple[str, ...]:
        fijos = tuple(hasta for desde, hasta in self.aristas if desde == nodo)
        condicionales = tuple(
            destino
            for condicional in self.condicionales
            if condicional.desde == nodo
            for destino in condicional.destinos
        )
        return fijos + condicionales


class PausaRequerida(Exception):
    """Un nodo se detuvo porque hace falta que un humano resuelva algo
    (migracion a agentes, etapa 5).

    El motor no la atrapa: se propaga por `invocar` tal cual -- la misma
    propiedad que `GrafoCompilado.invocar` ya promete para cualquier
    excepcion, y que el adaptador de LangGraph tiene probada desde la etapa
    3. Por eso detener el grafo no necesita nada del motor: ni checkpointer,
    ni estado serializable, ni un `interrupt()` propietario.

    `valor` es lo que hay que resolver, en los tipos de quien armo el grafo
    (`usecase/agente/pausa.py:PausaDelTurno`). Este puerto no lo mira.

    QUIEN LEVANTA ESTO NO PUEDE HABER HECHO NADA ANTES
    ----------------------------------------------------
    Regla de uso, y es de dinero. Un nodo que pausa tiene que ser un nodo
    DEDICADO, sin efectos antes de levantar: asi, si algun dia el motor
    reanuda re-ejecutando el nodo (es lo que hace `interrupt()` de
    LangGraph -- verificado, ver el documento de la etapa 5), volver a
    correrlo no repite ningun cobro. La topologia paga por la seguridad, no
    la buena memoria de quien escriba el nodo."""

    def __init__(self, valor: Any) -> None:
        super().__init__(f"el grafo se detuvo esperando una decision humana: {valor}")
        self.valor = valor


class GrafoCompilado(Protocol[E]):
    def invocar(self, estado: E) -> E:
        """Corre el grafo desde la entrada hasta FIN y devuelve el estado
        final. Una excepcion de un nodo se propaga tal cual: el turno falla
        donde fallo, sin que el motor la envuelva ni la trague. Eso incluye
        `PausaRequerida`, que no es una falla sino una detencion."""
        ...


class CompiladorDeGrafos(Protocol):
    def compilar(self, definicion: DefinicionDeGrafo[E]) -> GrafoCompilado[E]:
        ...
