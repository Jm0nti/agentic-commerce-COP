"""El turno como grafo (migracion a agentes, etapas 3 y 4).

La etapa 3 envolvio el loop de turnos como un nodo de un grafo LangGraph
minimo (orquestador + un solo worker). La etapa 4 parte ese worker unico en
los agentes especializados de la decision 3 del documento, y la arista
condicional que la etapa 3 se nego a poner de utileria pasa a ser real:

    EstadoDelTurno(conversacion, mensaje, historial_previo)
              |
              v
      [orquestador]   decidir la ruta + armar instrucciones y contexto
              |        -> replace(estado, ruta=..., instrucciones=...)
              |
              |  arista CONDICIONAL: nombre_del_agente(ruta)
              |
      +-------+---------+------------------+----------+---------+------------------+
      v                 v                  v          v         v                  v
 [agente_catalogo] [agente_carrito_pago] [agente_estado] ... [agente_soporte] [agente_respaldo]
      |                 |                  |          |         |                  |
      +-------+---------+------------------+----------+---------+------------------+
              |
              v
             FIN

Ningun nodo reimplementa nada: todos llaman a los metodos publicos del
`Agente` de las etapas 1 y 2 (`decidir`, `instrucciones_del_turno`,
`ejecutar_turno`). Por eso la etapa 4 tampoco cambia lo observable de un
turno -- lo que cambia es que ahora hay siete destinos distintos, cada uno
con su lista blanca validada al construirse, y un turno mal enrutado
revienta en vez de correr con las herramientas de otro agente.

LA CONDICIONAL ES REAL, Y ESO SE PRUEBA
-----------------------------------------
La etapa 3 no puso condicional porque con un solo worker habria devuelto
siempre lo mismo. Aca hay siete destinos, todos alcanzables, y cada uno
produce una ejecucion distinta (otra lista blanca, otra instruccion). Hay
una prueba por destino.

LO QUE NO SE IMPLEMENTO, Y POR QUE
------------------------------------
La arista `catalogo -> carrito_pago` que anticiparon las etapas 1 y 3. Ver
el hallazgo en `docs/arquitectura-agentes/etapa-4-agentes-especializados-
retrieval-hibrido.md`: partir la compra en dos nodos secuenciales cambia lo
observable de un turno de compra (dos vueltas al modelo, una respuesta de
texto intermedia) y exige un protocolo de traspaso que no se puede verificar
sin un modelo real. `carrito_pago` sigue siendo un agente con las
herramientas de catalogo ademas de las suyas, como en `RUTAS`.

DONDE VIVE EL ESTADO QUE IMPORTA
----------------------------------
`EstadoDelTurno` es congelado y cada nodo devuelve una copia con `replace`,
pero la `Conversacion` que lleva adentro es la MISMA de punta a punta y se
muta in place, igual que en `Agente.turno`. Es deliberado: el historial, las
clasificaciones y los contextos de la charla son de la conversacion, no del
grafo. Un checkpointer de LangGraph (decision 7 del documento) solo serviria
para el estado conversacional y nunca para dinero; sigue sin haber ninguno,
y recien la etapa 5 (`interrupt()`) lo necesita.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from typing import Any

from ...model.agente.gateways.modelo_lenguaje import Mensaje
from ...model.agente.gateways.orquestacion import (
    FIN,
    AristaCondicional,
    CompiladorDeGrafos,
    DefinicionDeGrafo,
    PausaRequerida,
)
from .agentes import AgenteEspecializado, construir_agentes, nombre_del_agente
from .conversacion import Agente, Conversacion
from .nodos import Ruta
from .pausa import DecisionHumana, PausaDelTurno, detectar_pausa
from .traza import comenzar as comenzar_traza

NODO_ORQUESTADOR = "orquestador"
NODO_ESPERA_HUMANA = "espera_humana"
# Prefijo para no confundir el nodo del GRAFO con el nodo de
# `HERRAMIENTAS_POR_NODO` que lleva el mismo nombre: el agente de
# `fuera_de_alcance` sirve la lista blanca del nodo 'orquestador', que no es
# el nodo de entrada del grafo. Dos espacios de nombres distintos, y el
# prefijo lo dice en voz alta.
PREFIJO_DE_AGENTE = "agente_"


def nodo_del_agente(nombre: str) -> str:
    return f"{PREFIJO_DE_AGENTE}{nombre}"


@dataclass(frozen=True)
class EstadoDelTurno:
    """Lo que viaja por el grafo durante UN turno.

    `conversacion`, `mensaje` e `historial_previo` entran armados; `ruta`,
    `instrucciones` y `respuesta` los va llenando cada nodo con `replace`.
    Un campo todavia en `None` significa "el nodo que lo llena no corrio",
    no "no hay" -- por eso `AgenteEnGrafo.turno` verifica `respuesta` al
    final en vez de devolver `None` en silencio."""

    conversacion: Conversacion
    mensaje: str
    historial_previo: tuple[Mensaje, ...]
    ruta: Ruta | None = None
    instrucciones: str | None = None
    respuesta: str | None = None
    # Etapa 5: lo que quedo esperando a una persona, si quedo algo. Lo llena
    # el nodo del agente al terminar su loop; lo lee la arista condicional
    # que decide si el turno pasa por `espera_humana` o termina.
    pausa: PausaDelTurno | None = None


def definir_grafo_del_turno(agente: Agente) -> DefinicionDeGrafo[EstadoDelTurno]:
    """La definicion de grafo, cerrada sobre `agente`.

    Sin un solo tipo de LangGraph: `DefinicionDeGrafo` es del puerto, y quien
    la compila (`app_service/config/agente.py`) es el unico que conoce el adaptador.

    `construir_agentes` valida aca la lista blanca de cada agente, nodo por
    nodo: armar el grafo con una tabla incoherente falla al construirlo, no
    en la primera charla de una persona.
    """
    especializados = construir_agentes(agente.herramientas)

    def orquestador(estado: EstadoDelTurno) -> EstadoDelTurno:
        ruta = agente.decidir(estado.conversacion, estado.mensaje, estado.historial_previo)
        instrucciones = agente.instrucciones_del_turno(
            estado.conversacion, ruta, estado.mensaje, estado.historial_previo,
        )
        return replace(estado, ruta=ruta, instrucciones=instrucciones)

    def _nodo_de(especializado: AgenteEspecializado):
        def _correr(estado: EstadoDelTurno) -> EstadoDelTurno:
            if estado.ruta is None:
                raise RuntimeError(
                    f"el agente '{especializado.nombre}' corrio sin ruta: el "
                    "orquestador no paso por este turno"
                )
            # La garantia de la etapa 4: este nodo solo atiende SU ruta.
            especializado.ruta_propia(estado.ruta)
            desde = len(estado.conversacion.mensajes)
            respuesta = agente.ejecutar_turno(
                estado.conversacion, estado.ruta, estado.instrucciones,
            )
            # Etapa 5: ¿este turno dejo algo esperando a una persona? Se lee
            # de lo que devolvieron las herramientas de ESTE turno.
            return replace(
                estado,
                respuesta=respuesta,
                pausa=detectar_pausa(estado.conversacion.mensajes[desde:]),
            )

        return _correr

    def decidir_agente(estado: EstadoDelTurno) -> str:
        if estado.ruta is None:
            raise RuntimeError("el orquestador no dejo ruta para enrutar el turno")
        return nodo_del_agente(nombre_del_agente(estado.ruta))

    def espera_humana(estado: EstadoDelTurno) -> EstadoDelTurno:
        """El punto explicito donde el turno se detiene (etapa 5, decision 6).

        NO HACE NADA MAS QUE DETENERSE, y eso es una regla de dinero, no una
        casualidad de este diseño: un motor que reanude re-ejecutando el nodo
        (es lo que hace `interrupt()` de LangGraph -- verificado, ver el
        documento de la etapa 5) vuelve a correr todo lo que hubiera antes
        del corte. Con el nodo vacio, volver a correrlo no repite ningun
        cobro. La topologia paga por la seguridad."""
        if estado.pausa is None:
            raise RuntimeError("se llego a espera_humana sin nada que esperar")
        # Carga el estado entero, no solo la pausa: la respuesta que el
        # modelo ya dio viaja ahi, y la persona tiene que leerla antes de
        # decidir. El puerto no lo mira -- `valor` es opaco para el.
        raise PausaRequerida(estado)

    def hay_que_esperar(estado: EstadoDelTurno) -> str:
        return NODO_ESPERA_HUMANA if estado.pausa is not None else FIN

    nodos: dict[str, Any] = {NODO_ORQUESTADOR: orquestador}
    destinos: list[str] = []
    for nombre, especializado in especializados.items():
        destino = nodo_del_agente(nombre)
        nodos[destino] = _nodo_de(especializado)
        destinos.append(destino)
    nodos[NODO_ESPERA_HUMANA] = espera_humana

    return DefinicionDeGrafo(
        nodos=nodos,
        entrada=NODO_ORQUESTADOR,
        # `espera_humana` no tiene salida hacia otro nodo: la unica forma de
        # salir de el es la excepcion. La arista a FIN existe para que la
        # topologia sea valida (todo nodo tiene exactamente una salida).
        aristas=((NODO_ESPERA_HUMANA, FIN),),
        condicionales=(
            AristaCondicional(
                desde=NODO_ORQUESTADOR,
                decidir=decidir_agente,
                destinos=tuple(destinos),
            ),
            # Cada agente decide, al terminar, si el turno se detiene.
            *(
                AristaCondicional(
                    desde=destino,
                    decidir=hay_que_esperar,
                    destinos=(NODO_ESPERA_HUMANA, FIN),
                )
                for destino in destinos
            ),
        ),
    )


class AgenteEnGrafo:
    """Mismo contrato que `Agente` (`iniciar`/`turno`), pero el turno corre
    por el grafo. `entry_points/api_rest/sesiones.py`, `entry_points/api_rest/app.py` y la CLI
    lo usan por duck typing, sin cambios.

    El grafo se compila UNA vez, al construirse: la topologia no depende del
    mensaje, y compilar en cada turno seria trabajo repetido por nada."""

    def __init__(self, agente: Agente, compilador: CompiladorDeGrafos) -> None:
        self._agente = agente
        self._grafo = compilador.compilar(definir_grafo_del_turno(agente))

    def iniciar(self) -> Conversacion:
        return self._agente.iniciar()

    def turno(self, conversacion: Conversacion, mensaje_usuario: str) -> str:
        """`abrir_turno` corre ANTES de entrar al grafo, no en un nodo: es lo
        que arma el estado inicial (el historial previo es justamente "lo de
        antes de este mensaje"), y un nodo que lo hiciera tendria que recibir
        un estado a medio armar."""
        inicio = comenzar_traza(conversacion)
        historial_previo = self._agente.abrir_turno(conversacion, mensaje_usuario)
        conversacion.pausa = None
        try:
            final = self._grafo.invocar(
                EstadoDelTurno(
                    conversacion=conversacion,
                    mensaje=mensaje_usuario,
                    historial_previo=historial_previo,
                )
            )
        except PausaRequerida as detencion:
            # El turno se detuvo en `espera_humana`. El modelo ya contesto
            # (la pausa se detecta DESPUES de su respuesta), asi que esa
            # respuesta se devuelve igual: la persona tiene que leer que le
            # proponen antes de decidir.
            detenido: EstadoDelTurno = detencion.valor
            conversacion.pausa = detenido.pausa
            respuesta = detenido.respuesta or ""
            self._agente.anotar_traza(
                conversacion, inicio, mensaje_usuario, respuesta, detenido.ruta,
                agente=None if detenido.ruta is None else nombre_del_agente(detenido.ruta),
                pausa=detenido.pausa,
            )
            return respuesta
        if final.respuesta is None:
            raise RuntimeError(
                "el grafo termino sin respuesta: ningun nodo llego a ejecutar el turno"
            )
        # La misma traza que el camino directo, mas el nombre del agente que
        # atendio: por el grafo esa es la decision que explica todo lo demas.
        self._agente.anotar_traza(
            conversacion,
            inicio,
            mensaje_usuario,
            final.respuesta,
            final.ruta,
            agente=None if final.ruta is None else nombre_del_agente(final.ruta),
        )
        return final.respuesta

    def reanudar(self, conversacion: Conversacion, decision: DecisionHumana) -> str:
        """Igual que `Agente.reanudar`, pero el turno que sigue corre por el
        grafo. Ver el docstring de aquel."""
        conversacion.pausa = None
        return self.turno(conversacion, decision.como_aviso())

    @property
    def _herramientas(self):
        """La misma superficie que `Agente` para quien llama a una
        herramienta directo (`tests/app_service/test_composicion_agente.py`): envolver el
        agente en un grafo no tendria que obligar a desenvolverlo para llegar
        a lo que ya era accesible."""
        return self._agente._herramientas
