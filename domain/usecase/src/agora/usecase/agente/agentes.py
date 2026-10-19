"""Los agentes especializados (migracion a agentes, etapa 4).

Hasta la etapa 3 habia UN worker que recibia una `Ruta` y servia las
herramientas de esa ruta. Esta etapa convierte cada destino posible del
orquestador en un agente con nombre propio, que valida su lista blanca al
CONSTRUIRSE y rechaza una ruta que no sea la suya al correr.

    TipoDeIntencion.CATALOGO      -> agente 'catalogo'        nodos: catalogo
    TipoDeIntencion.CARRITO_PAGO  -> agente 'carrito_pago'     nodos: catalogo, carrito_pago
    TipoDeIntencion.MEDIOS_DE_PAGO-> agente 'medios_de_pago'   nodos: medios_de_pago
    TipoDeIntencion.ESTADO        -> agente 'estado'           nodos: estado
    TipoDeIntencion.SOPORTE       -> agente 'soporte'          nodos: soporte
    TipoDeIntencion.FUERA_DE_ALCANCE -> agente 'fuera_de_alcance'  nodos: orquestador
    (sin decision)                -> agente 'respaldo'         nodos: RUTA_DE_RESPALDO

LA TABLA NO SE DUPLICA
------------------------
Los nodos de cada agente salen de `nodos.py:RUTAS` y `RUTA_DE_RESPALDO`, no
de una tabla nueva: una segunda copia de la misma decision es una copia que
algun dia va a divergir. Lo que esta etapa agrega no es una tabla, es un
objeto con identidad -- y con eso, dos garantias que antes no existian:

1. **Cada agente valida su lista blanca al construirse**, nodo por nodo
   (`herramientas_para_nodo`). Antes eso se validaba una vez para el agente
   entero; ahora, si alguien le asigna `pagar` al agente de soporte, el
   proceso no levanta. Es el item que la etapa 3 dejo pendiente.
2. **Un agente rechaza una ruta que no es la suya.** Si el enrutador del
   grafo se equivoca y manda la ruta de compra al nodo de soporte, revienta
   ahi -- en vez de correr el turno con las herramientas del otro. Es la
   clase de bug que un grafo hace posible y que antes, con un solo worker,
   no podia existir.

POR QUE 'carrito_pago' SIGUE TENIENDO LAS HERRAMIENTAS DE CATALOGO
--------------------------------------------------------------------
Porque `RUTAS` lo dice, y `RUTAS` lo dice por la decision 5 del documento.
Ver el hallazgo del documento de esta etapa: la arista `catalogo ->
carrito_pago` que anticipaban las etapas 1 y 3 NO se implemento, y la razon
esta ahi. Lo que no cambia: cada herramienta sigue teniendo un solo nodo
dueño (`HERRAMIENTAS_POR_NODO`), y ninguna ruta habilita nada fuera del
catalogo autorizado.
"""

from __future__ import annotations

from dataclasses import dataclass

from .herramientas import Herramienta, herramientas_para_nodo
from ...model.agente.intencion import TipoDeIntencion
from .nodos import RUTA_DE_RESPALDO, RUTAS, Ruta

NOMBRE_DEL_RESPALDO = "respaldo"


def nodos_por_agente() -> dict[str, tuple[str, ...]]:
    """Nombre de agente -> sus nodos. Derivado de `RUTAS`, nunca a mano."""
    tabla = {intencion.value: nodos for intencion, nodos in RUTAS.items()}
    tabla[NOMBRE_DEL_RESPALDO] = RUTA_DE_RESPALDO
    return tabla


def nombre_del_agente(ruta: Ruta) -> str:
    """A que agente le toca ESTA ruta. Es la funcion que decide la arista
    condicional del grafo (`usecase/agente/grafo.py`)."""
    if ruta.es_respaldo:
        return NOMBRE_DEL_RESPALDO
    assert ruta.clasificacion is not None and ruta.clasificacion.intencion is not None
    return ruta.clasificacion.intencion.value


class RutaDeOtroAgente(RuntimeError):
    """El enrutador mando una ruta que no le corresponde a este agente. No
    es un error de la persona ni del modelo: es un bug del grafo, y por eso
    corta el turno en vez de seguir con las herramientas equivocadas."""


@dataclass(frozen=True)
class AgenteEspecializado:
    """Un destino del orquestador, con su lista blanca propia."""

    nombre: str
    nodos: tuple[str, ...]

    @property
    def herramientas(self) -> frozenset[str]:
        return Ruta(clasificacion=None, nodos=self.nodos).herramientas

    def verificar(self, herramientas: list[Herramienta]) -> None:
        """Nodo por nodo, con la validacion por nodo de la etapa 1. Se corre
        al construir el grafo, no en una prueba lejana."""
        if not self.nodos:
            raise RuntimeError(f"el agente '{self.nombre}' no declara ningun nodo")
        for nodo in self.nodos:
            herramientas_para_nodo(herramientas, nodo)

    def ruta_propia(self, ruta: Ruta) -> None:
        """Levanta si `ruta` no es de este agente."""
        if nombre_del_agente(ruta) != self.nombre:
            raise RutaDeOtroAgente(
                f"el agente '{self.nombre}' recibio la ruta de "
                f"'{nombre_del_agente(ruta)}' (nodos: {', '.join(ruta.nodos)})"
            )


def construir_agentes(herramientas: list[Herramienta]) -> dict[str, AgenteEspecializado]:
    """Los siete agentes, cada uno ya validado contra `herramientas`."""
    agentes = {
        nombre: AgenteEspecializado(nombre=nombre, nodos=nodos)
        for nombre, nodos in nodos_por_agente().items()
    }
    for agente in agentes.values():
        agente.verificar(herramientas)
    return agentes


def toda_intencion_tiene_agente() -> bool:
    tabla = nodos_por_agente()
    return all(intencion.value in tabla for intencion in TipoDeIntencion)
