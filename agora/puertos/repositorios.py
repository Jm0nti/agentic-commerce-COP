"""Persistencia detras de interfaces.

El cambio que importa esta en `LibroDeConsumo`: reservar antes de cobrar,
confirmar despues.

Hoy `Boveda` hace leer -> sumar -> escribir sobre un JSON completo
(`nucleo.py:288-292`). En un CLI de un solo proceso funciona. En una app, dos
cobros simultaneos leen `gastado_dia = 90.000`, cada uno suma 15.000, y el
ultimo escribe 105.000. **El tope duro de 100.000 deja de ser un tope.**

Es el peor sitio posible para una condicion de carrera: el control que existe
para no perder dinero es justo el que se rompe primero bajo concurrencia.

Con reserva, el tope es una escritura condicional atomica. Si dos cobros
compiten por el ultimo tramo, uno gana y el otro recibe `TopeAgotado`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from ..dominio.comun.dinero import Dinero
from ..dominio.mandato.modelo import Consumo, Mandato
from ..dominio.pago.modelo import Ambiente, MedioDePagoRef


class TopeAgotado(Exception):
    """No cabe. Lleva el detalle para que el agente pueda decidir sin parsear texto."""

    def __init__(self, cual: str, disponible: Dinero, pedido: Dinero) -> None:
        super().__init__(f"{cual}: disponible {disponible}, pedido {pedido}")
        self.cual = cual
        self.disponible = disponible
        self.pedido = pedido


@dataclass(frozen=True)
class Reserva:
    reserva_id: str
    intencion_id: str
    mandato_id: str
    monto: Dinero
    dia: date


class LibroDeConsumo(Protocol):
    """Reserva -> cobra -> confirma o libera.

    Si el proceso muere entre reservar y confirmar, la reserva queda colgada y
    la conciliacion por webhook la resuelve. Reservas huerfanas mas viejas que
    un umbral se liberan solas: es preferible sobre-contar temporalmente que
    perder el tope.
    """

    def reservar(
        self, mandato: Mandato, intencion_id: str, monto: Dinero, tope_dia: Dinero
    ) -> Reserva: ...

    def confirmar(self, reserva: Reserva) -> None: ...

    def liberar(self, reserva: Reserva) -> None: ...

    def reserva_pendiente_de(self, intencion_id: str) -> Reserva | None:
        """La reserva viva de esta intencion, o `None`.

        `None` cubre dos casos que a quien llama no le importa distinguir:
        nunca hubo una reserva con este `intencion_id`, o la hubo pero ya se
        resolvio (confirmada o liberada). Es lo que usa `ConciliarEvento`
        (etapa 4) para encontrar, desde un webhook que llega sin memoria de
        haber llamado a `reservar`, cual reserva cerrar -- y lo que usa
        `EjecutarIntencion.retomar` para recuperar una reserva que se dejo
        viva a proposito mientras se esperaba una decision humana
        (`Decision.CONFIRMAR`).
        """
        ...

    def consumo_de(self, mandato_id: str) -> Consumo: ...

    def gastado_hoy(self, ambiente: Ambiente) -> Dinero: ...


class RepositorioMandatos(Protocol):
    def guardar(self, mandato: Mandato, ambiente: Ambiente) -> None: ...

    def obtener(self, mandato_id: str, ambiente: Ambiente) -> Mandato:
        """Levanta si el mandato pertenece a otro ambiente.

        El ambiente va como parametro y no como filtro opcional para que sea
        imposible olvidarlo. Es la version tipada de la guarda que hoy vive en
        `nucleo.py:319-330`.
        """
        ...

    def listar(self, ambiente: Ambiente) -> list[Mandato]: ...


class RepositorioMedios(Protocol):
    def guardar(self, ref: MedioDePagoRef, titular_id: str) -> None: ...

    def vivos(self, titular_id: str, ambiente: Ambiente) -> list[MedioDePagoRef]: ...

    def marcar_estado(self, ref: MedioDePagoRef, estado: str) -> None: ...
