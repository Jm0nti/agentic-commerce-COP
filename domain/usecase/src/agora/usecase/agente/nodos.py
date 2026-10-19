"""Que significa cada intencion en terminos de nodos y herramientas.

Migracion a agentes, etapa 1. Todavia no hay grafo: hay un solo loop de
turnos (`usecase/agente/conversacion.py`) que, en cada turno, actua como los nodos
que la RUTA de esa intencion habilita -- con las herramientas de esos nodos
y nada mas, y con una instruccion corta del orquestador para ese turno.

    mensaje -> clasificador -> TipoDeIntencion -> RUTAS -> nodos
                                                         -> herramientas (union de
                                                            sus listas blancas)
                                                         -> instrucciones del turno

LA TABLA `RUTAS` ES TRANSITORIA
--------------------------------
Una ruta puede combinar mas de un nodo. Hoy solo pasa con `carrito_pago`,
que habilita tambien `catalogo`: "quiero comprar los audifonos baratos" en un
solo mensaje necesita buscar el producto Y armar el carrito, y sin grafo no
hay forma de pasar de un nodo a otro dentro del mismo turno. En la etapa 4
esa combinacion deja de ser una fila de esta tabla y pasa a ser una arista
`catalogo -> carrito_pago` de LangGraph. Lo que NO cambia: cada herramienta
sigue teniendo un solo nodo dueño (`herramientas.py:HERRAMIENTAS_POR_NODO`),
y ninguna ruta puede habilitar algo fuera del catalogo autorizado.

Las instrucciones de cada nodo estan aca (no en `politica.py`) porque tienen
que cambiar junto con su lista blanca: si un nodo gana o pierde una
herramienta, lo que se le dice al modelo en ese nodo cambia en el mismo
diff. `politica.py` sigue teniendo el `SYSTEM_PROMPT` general de siempre.
"""

from __future__ import annotations

from dataclasses import dataclass

from .herramientas import HERRAMIENTAS_POR_NODO
from ...model.agente.intencion import ClasificacionDeIntencion, TipoDeIntencion

INSTRUCCIONES_POR_NODO: dict[str, str] = {
    "orquestador": (
        "No tenes herramientas en este turno. Si es un saludo o un "
        "agradecimiento, responde breve y cordial. Si lo que piden no es "
        "comprar, ver el estado de un pago, medios de pago o dudas sobre como "
        "funciona el sistema, decilo con claridad y conta en una frase que si "
        "podes hacer."
    ),
    "catalogo": (
        "Nodo de catalogo: podes navegar comercios y productos. Todo "
        "producto, precio o comercio que menciones tiene que salir de las "
        "herramientas de catalogo, nunca de memoria."
    ),
    "carrito_pago": (
        "Nodo de carrito y pago: armar_carrito deja una propuesta SIN FIRMAR "
        "que la persona autoriza ella misma; pagar exige un mandato_id que la "
        "persona ya firmo y el carrito_id que devolvio armar_carrito. Nunca "
        "inventes ni asumas un mandato_id ni un carrito_id."
    ),
    "medios_de_pago": (
        "Nodo de medios de pago: no tenes herramientas en este turno. Enrolar "
        "o revocar un medio de pago lo hace la persona ella misma desde la "
        "app, nunca vos. No pidas ni repitas numeros de telefono, cuenta o "
        "tarjeta."
    ),
    "estado": (
        "Nodo de estado: antes de contestar cualquier cosa sobre un pago, "
        "llama a consultar_estado con su intencion_id -- aunque ya lo hayas "
        "consultado antes en esta charla. Nunca respondas de memoria."
    ),
    "soporte": (
        "Nodo de soporte: no tenes herramientas en este turno. Explica en "
        "prosa como funciona el sistema (propuesta, firma humana, mandato, "
        "confirmacion). Si abajo hay documentacion recuperada, basate en ella "
        "y deci de que documento sale; si no alcanza, decilo en vez de "
        "suponer. No des cifras de topes, montos maximos ni limites: esas "
        "salen del mandato real de la persona, nunca de una explicacion "
        "general ni de la documentacion."
    ),
}

RUTAS: dict[TipoDeIntencion, tuple[str, ...]] = {
    TipoDeIntencion.CATALOGO: ("catalogo",),
    # Ver "LA TABLA RUTAS ES TRANSITORIA" en el docstring del modulo.
    TipoDeIntencion.CARRITO_PAGO: ("catalogo", "carrito_pago"),
    TipoDeIntencion.MEDIOS_DE_PAGO: ("medios_de_pago",),
    TipoDeIntencion.ESTADO: ("estado",),
    TipoDeIntencion.SOPORTE: ("soporte",),
    TipoDeIntencion.FUERA_DE_ALCANCE: ("orquestador",),
}

# Cuando nadie pudo decidir (sin clasificador, clasificador sin certeza, o
# modelo caido): el agente de antes de esta etapa, con las seis herramientas
# y sin instruccion extra. Expresado como union de nodos -- no como "todo el
# catalogo" a mano -- para que siga pasando por las listas blancas por nodo.
RUTA_DE_RESPALDO: tuple[str, ...] = ("catalogo", "carrito_pago", "estado")


@dataclass(frozen=True)
class Ruta:
    """Lo que el orquestador decidio para UN turno."""

    clasificacion: ClasificacionDeIntencion | None
    nodos: tuple[str, ...]

    @property
    def herramientas(self) -> frozenset[str]:
        return frozenset(n for nodo in self.nodos for n in HERRAMIENTAS_POR_NODO[nodo])

    @property
    def es_respaldo(self) -> bool:
        return self.clasificacion is None or not self.clasificacion.decidida

    def instrucciones(self) -> str | None:
        """El mensaje de sistema de este turno, o `None` en la ruta de
        respaldo (que se comporta exactamente como el agente de antes)."""
        if self.es_respaldo:
            return None
        assert self.clasificacion is not None and self.clasificacion.intencion is not None
        habilitadas = ", ".join(sorted(self.herramientas)) or "ninguna"
        partes = [
            "(orquestador, solo para este turno) Intencion clasificada: "
            f"{self.clasificacion.intencion.value}. Herramientas habilitadas en "
            f"este turno: {habilitadas}. Si para responder te hace falta una "
            "herramienta que no esta habilitada, no inventes el resultado: "
            "decile a la persona que en este paso no podes hacerlo y que te lo "
            "pida de nuevo, con mas detalle."
        ]
        partes.extend(INSTRUCCIONES_POR_NODO[nodo] for nodo in self.nodos)
        return "\n".join(partes)


def ruta_para(clasificacion: ClasificacionDeIntencion | None) -> Ruta:
    if clasificacion is None or clasificacion.intencion is None:
        return Ruta(clasificacion=clasificacion, nodos=RUTA_DE_RESPALDO)
    return Ruta(clasificacion=clasificacion, nodos=RUTAS[clasificacion.intencion])
