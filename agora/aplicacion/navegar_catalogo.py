"""`NavegarCatalogo`: las tres busquedas de `RepositorioCatalogo` mas
`armar_carrito`, que es donde este caso de uso deja de ser un simple
pasamanos.

`buscar_comercios`/`buscar_productos`/`ver_producto` delegan directo al
puerto -- no hay regla de negocio que agregar ahi, solo la forma en que
`agente/herramientas.py` los expone (etapa 5, misma seccion). La regla vive
en `armar_carrito`: ahi es donde un producto `AGOTADO` no puede convertirse
en un `ItemCarrito` (el docstring de `Disponibilidad` en `dominio/catalogo/
modelo.py` ya lo anuncia), y donde un carrito con productos de mas de un
comercio no se deja formar -- un `Mandato` autoriza a un solo comercio
(`comercio_id`), asi que un carrito mixto no podria representarse despues.

Etapa 6: `armar_carrito` tambien guarda la `PropuestaDeMandato` que
devuelve (via `RepositorioPropuestas`), no solo el `Carrito`. Es lo que
permite que `entradas/cli/firmar` la encuentre por `propuesta_id` desde
OTRO proceso -- por ejemplo, cuando quien arma el carrito es el agente en
una charla de `chat` y quien firma es el titular en una terminal aparte.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..dominio.catalogo.modelo import Carrito, Comercio, Disponibilidad, ItemCarrito, Producto
from ..dominio.comun.errores import ProductoDeOtroComercio, ProductoNoDisponible
from ..dominio.mandato.modelo import PropuestaDeMandato
from ..puertos.catalogo import RepositorioCatalogo
from ..puertos.repositorios import RepositorioCarritos, RepositorioPropuestas
from ..puertos.sistema import GeneradorIds


@dataclass(frozen=True)
class ItemPedido:
    """Lo que el agente pide agregar: un producto y una cantidad. No lleva
    precio -- el precio sale del catalogo en el momento de armar, nunca de
    lo que el agente diga que cuesta."""

    producto_id: str
    cantidad: int = 1


class NavegarCatalogo:
    def __init__(
        self,
        catalogo: RepositorioCatalogo,
        carritos: RepositorioCarritos,
        ids: GeneradorIds,
        propuestas: RepositorioPropuestas | None = None,
    ) -> None:
        self._catalogo = catalogo
        self._carritos = carritos
        self._ids = ids
        # Opcional por retrocompatibilidad con pruebas que arman
        # `NavegarCatalogo` sin este puerto y nunca ejercitan `armar_carrito`
        # (`buscar_comercios`/`buscar_productos`/`ver_producto` no lo tocan).
        # `composicion/contenedor.py` siempre lo provee.
        self._propuestas = propuestas

    # -- busqueda, sin reglas propias: delega tal cual --------------------- #

    def buscar_comercios(self, consulta: str = "") -> list[Comercio]:
        return self._catalogo.buscar_comercios(consulta)

    def buscar_productos(self, comercio_id: str, consulta: str = "") -> list[Producto]:
        return self._catalogo.buscar_productos(comercio_id, consulta)

    def ver_producto(self, producto_id: str) -> Producto:
        return self._catalogo.ver_producto(producto_id)

    # -- armar el carrito ---------------------------------------------------- #

    def armar_carrito(
        self,
        comercio_id: str,
        items: list[ItemPedido],
        turno_id: str | None = None,
        vigencia_minutos: int = 30,
        justificacion: str = "",
    ) -> tuple[Carrito, PropuestaDeMandato]:
        """Devuelve el carrito guardado y una propuesta de mandato SIN
        FIRMAR, con `monto_max` igual al total del carrito y un solo uso --
        los mismos defaults estrechos de la v1 (`boveda/mandato.py:emitir`):
        un mandato amplio deberia costar escribirlo, no ser lo que sale por
        omision. Firmarla es del humano (`aplicacion/emitir_mandato.py`).
        """
        item_carrito: list[ItemCarrito] = []
        for pedido in items:
            producto = self._catalogo.ver_producto(pedido.producto_id)
            if producto.comercio_id != comercio_id:
                raise ProductoDeOtroComercio(
                    f"'{producto.producto_id}' pertenece a '{producto.comercio_id}', "
                    f"no a '{comercio_id}': un carrito es de un solo comercio"
                )
            if producto.disponibilidad is not Disponibilidad.EN_STOCK:
                raise ProductoNoDisponible(
                    f"'{producto.nombre}' esta '{producto.disponibilidad.value}', "
                    "no se puede agregar al carrito"
                )
            item_carrito.append(
                ItemCarrito(
                    producto_id=producto.producto_id,
                    nombre=producto.nombre,
                    cantidad=pedido.cantidad,
                    precio_unitario=producto.precio,
                )
            )

        carrito = Carrito(
            carrito_id=self._ids.nuevo("car"),
            comercio_id=comercio_id,
            items=tuple(item_carrito),
            turno_id=turno_id,
        )
        self._carritos.guardar(carrito)

        propuesta = PropuestaDeMandato(
            propuesta_id=self._ids.nuevo("prp"),
            carrito_id=carrito.carrito_id,
            comercio_id=comercio_id,
            monto_max=carrito.total,
            usos_max=1,
            vigencia_minutos=vigencia_minutos,
            justificacion=justificacion,
        )
        # Persistida igual que el carrito, y por el mismo motivo (docstring
        # de `puertos/repositorios.py:RepositorioPropuestas`): sin esto,
        # nada fuera de ESTE proceso podria volver a encontrar la propuesta
        # para firmarla -- `EmitirMandato` la busca por `propuesta_id`, nunca
        # confia en una que le llegue por parametro.
        if self._propuestas is not None:
            self._propuestas.guardar(propuesta)
        return carrito, propuesta
