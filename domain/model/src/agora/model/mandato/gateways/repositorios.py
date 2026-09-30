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

from ...commons.dinero import Dinero
from ...pago.modelo import Ambiente
from ..modelo import Consumo, Mandato, PropuestaDeMandato


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


class RepositorioPropuestas(Protocol):
    """Etapa 6. El mismo argumento que `RepositorioCarritos`, aplicado a la
    otra mitad de lo que se firma: `EmitirMandato` vuelve a buscar la
    `PropuestaDeMandato` EXACTA por `propuesta_id` al momento de firmar, en
    vez de aceptar una que le llegue por parametro.

    Antes de esta etapa `EmitirMandato` recibia el objeto `PropuestaDeMandato`
    directo -- comodo mientras "armar el carrito" y "firmar" corrian en el
    mismo proceso (`entradas/cli/emitir`, el humano operando la CLI de punta
    a punta). En cuanto la propuesta la arma el agente en una conversacion de
    chat y la firma un humano en OTRO proceso (`entradas/cli/firmar`),
    aceptar una `PropuestaDeMandato` por parametro significaria confiar en
    cualquier `monto_max`/`usos_max`/`categorias` que ese segundo proceso
    diga tener -- el mismo hueco que `carrito_hash` existe para cerrar del
    lado del carrito. `NavegarCatalogo.armar_carrito` es el unico que
    guarda."""

    def guardar(self, propuesta: PropuestaDeMandato) -> None: ...

    def obtener(self, propuesta_id: str) -> PropuestaDeMandato:
        """Levanta `PropuestaDesconocida` si no existe."""
        ...
