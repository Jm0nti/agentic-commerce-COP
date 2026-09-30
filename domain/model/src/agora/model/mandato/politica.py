"""De lista de violaciones a dictamen.

Hoy `evaluar()` devuelve violaciones y la politica real -- "cualquier violacion
bloquea" -- vive implicita en un `if` de `nucleo.py:354`. Con un agente de por
medio hace falta un tercer desenlace.

    PERMITIR   cabe en el mandato. Adelante.
    CONFIRMAR  cabe, pero huele raro. Que lo mire el humano.
    BLOQUEAR   no cabe. Y queda escrito por que.

CONFIRMAR es el interesante y el que no existe hoy. Un agente manipulado que
compra el producto equivocado a un comercio autorizado no produce ninguna
violacion -- tu propio `mandato.py:14-24` ya lo dice. Ese caso no lo atrapa el
mandato ni debe atraparlo: la respuesta correcta no es si ni no, es preguntar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .modelo import Consumo, Intencion, Mandato, Violacion


class Decision(str, Enum):
    PERMITIR = "PERMITIR"
    CONFIRMAR = "CONFIRMAR"
    BLOQUEAR = "BLOQUEAR"


@dataclass(frozen=True)
class Dictamen:
    decision: Decision
    violaciones: list[Violacion] = field(default_factory=list)
    senales: list[str] = field(default_factory=list)

    @property
    def deja_pasar(self) -> bool:
        return self.decision is Decision.PERMITIR

    def to_json(self) -> dict:
        return {
            "decision": self.decision.value,
            "violaciones": [v.to_json() for v in self.violaciones],
            "senales": self.senales,
        }


# --------------------------------------------------------------------------- #
# Senales blandas: no violan el mandato, pero merecen una mirada humana.
# Son heuristicas, no reglas. Por eso van separadas de las violaciones y por eso
# su desenlace es CONFIRMAR y no BLOQUEAR.
# --------------------------------------------------------------------------- #


def _senales_blandas(
    mandato: Mandato, intencion: Intencion, consumo: Consumo
) -> list[str]:
    s: list[str] = []

    # Gastar de una todo lo que queda del mandato.
    restante = mandato.tope_total.centavos - consumo.acumulado.centavos
    if restante and intencion.monto.centavos >= restante * 0.9:
        s.append("agota el mandato de una sola vez")

    # Un mandato emitido para un monto y usado por casi el maximo cada vez.
    if intencion.monto.centavos >= mandato.monto_max.centavos * 0.95:
        s.append("pega contra el tope por transaccion")

    # Ultimo uso disponible.
    if mandato.usos_max - consumo.usos == 1:
        s.append("es el ultimo uso del mandato")

    return s


def evaluar(
    mandato: Mandato,
    intencion: Intencion,
    consumo: Consumo,
    verificador,
    exigir_mandato: bool = True,
    ahora: datetime | None = None,
    carrito_hash: str | None = None,
    llave_publica: bytes = b"",
) -> Dictamen:
    """El dictamen completo.

    `ahora` es un parametro y no una llamada a `datetime.now()` adentro. Sin eso
    esta funcion seria imposible de probar sin mover el reloj del sistema, y el
    dominio dejaria de ser puro: un modulo que consulta la hora ya hace IO.

    `exigir_mandato=False` es el brazo sin control del experimento: se evalua
    igual y se registra igual, pero el desenlace no bloquea. Sigue sujeto a los
    topes duros, que viven en otra capa y no se pueden apagar.
    """
    violaciones = mandato.violaciones_contra(
        intencion,
        consumo,
        verificador,
        ahora=ahora,
        carrito_hash=carrito_hash,
        llave_publica=llave_publica,
    )

    if violaciones and exigir_mandato:
        return Dictamen(Decision.BLOQUEAR, violaciones)

    senales = _senales_blandas(mandato, intencion, consumo)
    if senales and exigir_mandato:
        return Dictamen(Decision.CONFIRMAR, violaciones, senales)

    # Sin control: pasa, pero las violaciones quedan escritas. Que la pasarela
    # apruebe un cobro que el mandato no autorizaba es la metrica central.
    return Dictamen(Decision.PERMITIR, violaciones, senales)
