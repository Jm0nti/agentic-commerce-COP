"""Errores con tipo, no cadenas formateadas.

Hoy todo es `BovedaError` con un mensaje, y algunos casos vuelven dentro de un
recibo como `motivo="error_pasarela: Wompi 422: {...}"` (`nucleo.py:377`). En
`recibos.jsonl` hay una fila exactamente asi.

El problema no es estetico. Un agente que recibe eso no puede decidir que hacer
sin parsear texto, y "fondos insuficientes" (reintentar mas tarde) y "mandato
vencido" (pedir uno nuevo) son respuestas opuestas que hoy son la misma cadena.

Cada error lleva `reintentable` porque esa es la pregunta que el agente hace
primero, y `detalle_proveedor` para no perder el diagnostico crudo -- que fue lo
que se estaba tirando cuando `afe_decision` no llegaba al recibo.
"""

from __future__ import annotations

from typing import Any


class ErrorDeDominio(Exception):
    """Raiz. Nada del dominio levanta algo que no herede de aqui."""

    reintentable: bool = False

    def __init__(self, mensaje: str, detalle_proveedor: dict[str, Any] | None = None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle_proveedor = detalle_proveedor or {}

    def to_json(self) -> dict[str, Any]:
        return {
            "tipo": type(self).__name__,
            "mensaje": self.mensaje,
            "reintentable": self.reintentable,
            "detalle_proveedor": self.detalle_proveedor,
        }


# -- mandato ---------------------------------------------------------------- #


class ErrorDeMandato(ErrorDeDominio):
    pass


class MandatoDesconocido(ErrorDeMandato):
    pass


class MandatoVencido(ErrorDeMandato):
    """Pedir uno nuevo. No es reintentable: el tiempo no vuelve."""


class FirmaInvalida(ErrorDeMandato):
    """Nunca reintentable, y siempre digno de una anotacion en la bitacora."""


class MandatoDeOtroAmbiente(ErrorDeMandato):
    """Un mandato de sandbox presentado en produccion, o al reves."""


# -- limites ---------------------------------------------------------------- #


class LimiteExcedido(ErrorDeDominio):
    pass


class TopeDuroExcedido(LimiteExcedido):
    """El guardarrail. Nunca se apaga y nunca es reintentable."""


class TopeDiarioAgotado(LimiteExcedido):
    """Manana si. Por eso es el unico limite reintentable."""

    reintentable = True


class MandatoAgotado(LimiteExcedido):
    """Se acabaron los usos o el tope acumulado."""


# -- pasarela --------------------------------------------------------------- #


class ErrorDePasarela(ErrorDeDominio):
    pass


class PasarelaNoDisponible(ErrorDePasarela):
    """Red, timeout, 5xx. Reintentar es correcto -- y seguro, porque la
    referencia se deriva de la intencion y no cambia entre intentos."""

    reintentable = True


class CobroRechazado(ErrorDePasarela):
    """La pasarela dijo que no. El motivo esta en `detalle_proveedor`."""


class RechazadoPorAntifraude(CobroRechazado):
    """`afe_decision: DECLINE`.

    Merece su propia clase porque es el unico control del flujo que el comercio
    no puede ver, configurar ni explicarle al titular. Confundirlo con un
    rechazo por fondos hace que la PoC mida mal: la primera corrida real quedo
    detenida aqui, no en el mandato.
    """


class MedioDePagoRevocado(ErrorDePasarela):
    """La fuente ya no sirve. Hay que volver a enrolar."""


# -- consumo ------------------------------------------------------------ #


class ErrorDeConsumo(ErrorDeDominio):
    pass


class ReservaNoEncontrada(ErrorDeConsumo):
    """`EjecutarIntencion.retomar` (etapa 4) sobre una intencion sin una
    reserva pendiente viva -- ya se resolvio (por `ConciliarEvento`, o por un
    `retomar` anterior), o nunca existio. No es reintentable con los mismos
    datos: retomar de nuevo la misma intencion no hace aparecer una reserva
    que ya no esta."""
