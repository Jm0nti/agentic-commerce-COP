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

from ..dominio.catalogo.modelo import Carrito
from ..dominio.comun.dinero import Dinero
from ..dominio.mandato.modelo import Consumo, Mandato, PropuestaDeMandato
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
    """Multi-comercio (evaluacion del 1 de septiembre de 2026, `docs/
    viabilidad-multi-comercio-wompi.md`): un `payment_source_id` de Wompi
    esta atado al comercio (a la llave publica) que lo creo, no es portable
    entre comercios aunque los tres usen Wompi -- asi que "vinculo" no es
    "vivo": un titular puede tener varios medios vivos y ninguno vinculado
    al comercio en el que quiere comprar ahora. `guardar` registra bajo que
    comercio nacio cada medio; `vinculado_con` es la pregunta que evita
    pedirle al titular un enrolamiento (un push mas) que ya hizo antes para
    ese comercio puntual."""

    def guardar(self, ref: MedioDePagoRef, titular_id: str, comercio_id: str) -> None: ...

    def vivos(self, titular_id: str, ambiente: Ambiente) -> list[MedioDePagoRef]: ...

    def vinculado_con(
        self, titular_id: str, comercio_id: str, ambiente: Ambiente
    ) -> MedioDePagoRef | None:
        """El medio vivo mas reciente que este titular ya vinculo con este
        comercio, o `None` si nunca enrolo uno para el -- en ese caso hace
        falta un enrolamiento nuevo, dirigido a `comercio_id`
        (`aplicacion/enrolar_medio.py`), antes de poder firmar un mandato
        contra el (`aplicacion/emitir_mandato.py`)."""
        ...

    def comercio_de(self, ref: MedioDePagoRef) -> str | None:
        """Bajo que comercio se creo este medio, o `None` si el medio no
        esta registrado. Lo usa `RevocarMedio` para resolver con que
        pasarela pedir la revocacion sin que quien llame tenga que volver a
        pasar el `comercio_id` a mano."""
        ...

    def marcar_estado(self, ref: MedioDePagoRef, estado: str) -> None: ...


class RepositorioCarritos(Protocol):
    """Etapa 5. `EmitirMandato` necesita volver a buscar el `Carrito` EXACTO
    por `carrito_id` al momento de firmar, en vez de confiar en un carrito
    que le llegue de afuera (por ejemplo, por parametro desde el agente):
    calcular `carrito_hash` a partir de una fuente que el agente pudo
    manipular volveria inutil la verificacion que ese hash existe para
    ofrecer. `NavegarCatalogo.armar_carrito` es el unico que guarda."""

    def guardar(self, carrito: Carrito) -> None: ...

    def obtener(self, carrito_id: str) -> Carrito:
        """Levanta `CarritoDesconocido` si no existe."""
        ...


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


class RegistroDeEstados(Protocol):
    """Etapa 5. Resuelve un vacio que `LibroDeConsumo.reserva_pendiente_de`
    deja a proposito (ver su docstring): esa reserva vuelve `None` tanto si
    la intencion nunca existio como si ya se resolvio, y no dice si se
    resolvio en `APROBADO` o en `RECHAZADO`. `consultar_estado` (la
    herramienta del agente) necesita esa distincion, y ni `LibroDeConsumo`
    ni `Bitacora` -- que es auditoria de solo escritura, no estado de
    aplicacion (`puertos/sistema.py`) -- estan pensados para contestarla.

    `EjecutarIntencion` y `ConciliarEvento` escriben aqui en cada uno de sus
    puntos de decision ya existentes (parametro opcional, `None` por
    defecto: no cambia su comportamiento si nadie lo provee). `estado` es
    texto libre y corto -- "pendiente", "aprobado", "rechazado",
    "esperando_confirmacion" -- no un enum nuevo: es el mismo vocabulario
    que ya usa `Recibo.motivo`/`EstadoCobro`, no una taxonomia paralela.

    Etapa 6 (segunda parte): tiene adaptador SQLite ademas del de memoria.
    La etapa 5 penso esto como "vocabulario para que el agente se
    autoconsulte dentro de UNA conversacion" y lo dejo sin sqlite a
    proposito -- pero `retomar` nunca es herramienta del agente (resolver
    un CONFIRMAR es decision humana, igual que firmar), asi que SIEMPRE
    corre en otra terminal. Sin persistencia entre procesos, el chat
    quedaria diciendo "esperando confirmacion humana" para siempre aunque
    la persona ya hubiera confirmado en la otra terminal -- exactamente el
    bug que motivo agregar la tabla `estado_intencion`.
    """

    def fijar(self, intencion_id: str, estado: str, detalle: str = "") -> None: ...

    def obtener(self, intencion_id: str) -> tuple[str, str] | None:
        """`(estado, detalle)`, o `None` si nunca se fijo nada para este id."""
        ...
