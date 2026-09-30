"""Los cuatro desenlaces de un cobro, y como se elige uno.

`docs/arquitectura-v2.md` (ADR-2) es explicito: la simulada no es un mock de
pruebas, es un adaptador de produccion para el modo demo, y por eso tiene que
poder reproducir los mismos desenlaces que Wompi real -- aprobado, declinado,
declinado por antifraude y pendiente -- **a voluntad**, sin depender de que
Wompi coopere el dia de una presentacion.

La convencion para elegir uno es la misma que ya usa `wompi_lab/lab.py`: un
valor "magico" en la entrada selecciona el desenlace (alli son numeros de
tarjeta y de Nequi; `OrdenDeCobro` no carga ningun campo libre para eso, asi
que aqui el marcador es el correo del pagador). El desenlace de antifraude por
defecto no es arbitrario: reproduce la corrida real documentada en
`docs/decline-afe.md` (19 de agosto de 2026), donde Wompi declino un cobro de
2.000 COP con `afe_decision: DECLINE` porque el correo del pagador estaba en
`example.com` -- un dominio reservado por la RFC 2606 que nunca entrega
correo, y que un motor antifraude no tiene por que distinguir de uno
desechable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ....model.pago.modelo import EstadoCobro, OrdenDeCobro


@dataclass(frozen=True)
class Desenlace:
    estado: EstadoCobro
    status_message: str = ""
    afe_decision: str = ""


APROBADO = Desenlace(EstadoCobro.APROBADO, "Transaccion aprobada", "ACCEPT")
PENDIENTE = Desenlace(EstadoCobro.PENDIENTE, "En proceso", "")
DECLINADO = Desenlace(EstadoCobro.RECHAZADO, "Fondos insuficientes", "ACCEPT")
DECLINADO_ANTIFRAUDE = Desenlace(
    EstadoCobro.RECHAZADO,
    "Por motivos de seguridad no pudimos procesar tu pago. "
    "Si crees que se trata de un error puedes comunicarte con la entidad.",
    "DECLINE",
)

# RFC 2606: dominios reservados para documentacion y ejemplos. Nunca
# resuelven correo de verdad -- exactamente lo que vio el AFE real.
_DOMINIOS_RESERVADOS = frozenset({"example.com", "example.org", "example.net", "test.com"})

Decisor = Callable[[OrdenDeCobro], Desenlace]


def heuristica_por_defecto(orden: OrdenDeCobro) -> Desenlace:
    """El correo del pagador selecciona el desenlace.

        *@example.com (o cualquier dominio reservado), o que contenga
        "fraude"                                    -> declinado, antifraude
        local-part con "pendiente"                  -> pendiente
        local-part con "declina" o "rechaza"         -> declinado (generico)
        cualquier otro correo                        -> aprobado
    """
    correo = (orden.correo_pagador or "").strip().lower()
    local, _, dominio = correo.partition("@")

    if dominio in _DOMINIOS_RESERVADOS or "fraude" in local:
        return DECLINADO_ANTIFRAUDE
    if "pendiente" in local:
        return PENDIENTE
    if "declina" in local or "rechaza" in local:
        return DECLINADO
    return APROBADO


@dataclass(frozen=True)
class GuionSimulado:
    """Envuelve el decisor para que `AdaptadorSimulado` no dependa de una
    funcion suelta y las pruebas puedan inyectar cualquier logica."""

    decisor: Decisor = heuristica_por_defecto

    def decidir(self, orden: OrdenDeCobro) -> Desenlace:
        return self.decisor(orden)
