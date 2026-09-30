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

EL ENRUTADOR DE RECUPERACION (migracion a agentes, etapa 4)
-------------------------------------------------------------
`buscar_productos` deja de ser un pasamanos y pasa a ser los tres peldanos
de la decision 1 de `docs/arquitectura-agentes/arquitectura-agentes-
langgraph.md`, en este orden y no en otro:

    1. estructurado   `RepositorioCatalogo.buscar_productos(comercio, consulta)`
                      -- el match por substring de siempre. Auditable, no
                      puede inventar un producto.
    2. reglas duras   `FiltrosDeProducto.aplicar` -- disponibilidad, rango
                      de precio. Se aplican al resultado de CUALQUIER
                      peldano, no solo del semantico.
    3. semantico      solo si 1 no encontro nada Y hay buscador configurado,
                      y solo sobre los candidatos que ya pasaron 2.

Preferir lo estructurado no es una optimizacion: es la decision 1 ("preferida
siempre que alcance: es auditable y no puede devolver un producto
inexistente"). El peldano semantico existe para el caso que el documento
nombra -- alguien que describe una necesidad ("algo para piel reseca") en vez
de nombrar el producto -- y nunca para reordenar lo que ya se encontro bien.

Sin buscador semantico y sin filtros, esta funcion devuelve exactamente lo
mismo que antes de la etapa 4: el peldano 1 y nada mas.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..dominio.catalogo.modelo import Carrito, Comercio, Disponibilidad, ItemCarrito, Producto
from ..dominio.comun.errores import ErrorDeDominio, ProductoDeOtroComercio, ProductoNoDisponible
from ..dominio.mandato.modelo import PropuestaDeMandato
from ..puertos.busqueda_productos import BuscadorSemanticoDeProductos, FiltrosDeProducto
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
        semantico: BuscadorSemanticoDeProductos | None = None,
    ) -> None:
        self._catalogo = catalogo
        self._carritos = carritos
        self._ids = ids
        # Opcional por retrocompatibilidad con pruebas que arman
        # `NavegarCatalogo` sin este puerto y nunca ejercitan `armar_carrito`
        # (`buscar_comercios`/`buscar_productos`/`ver_producto` no lo tocan).
        # `composicion/contenedor.py` siempre lo provee.
        self._propuestas = propuestas
        # Etapa 4. `None` = sin peldano semantico (no hay OPENAI_API_KEY):
        # el catalogo se navega con el match estructurado de siempre.
        self._semantico = semantico

    # -- busqueda ----------------------------------------------------------- #

    def buscar_comercios(self, consulta: str = "") -> list[Comercio]:
        """Sigue delegando tal cual: el enrutador de la etapa 4 es para
        productos. Un comercio se elige por nombre o categoria, que es
        justo lo que el match estructurado resuelve bien."""
        return self._catalogo.buscar_comercios(consulta)

    def buscar_productos(
        self,
        comercio_id: str,
        consulta: str = "",
        filtros: FiltrosDeProducto | None = None,
        limite_semantico: int = 5,
    ) -> list[Producto]:
        """Los tres peldanos (ver el docstring del modulo). Propaga
        `ComercioDesconocido` igual que antes."""
        filtros = filtros or FiltrosDeProducto()
        estructurados = filtros.aplicar(self._catalogo.buscar_productos(comercio_id, consulta))
        if estructurados or not consulta.strip() or self._semantico is None:
            return estructurados

        # Peldano 3. Los candidatos son TODO el comercio pasado por las
        # mismas reglas duras: lo semantico solo puede reordenar y recortar
        # ese conjunto, nunca ampliarlo.
        candidatos = filtros.aplicar(self._catalogo.buscar_productos(comercio_id, ""))
        if not candidatos:
            return []
        try:
            return self._semantico.buscar(consulta, candidatos, limite=limite_semantico)
        except ErrorDeDominio:
            # `RecuperacionNoDisponible`: el proveedor de embeddings no
            # contesto. Una busqueda sin resultados es una respuesta valida
            # del catalogo (el puerto lo dice), asi que el turno sigue con
            # lo estructurado -- vacio -- en vez de caerse. Cualquier otra
            # excepcion es un bug y sube, mismo criterio que
            # `agente/contexto_documental.py`.
            return []

    def ver_producto(self, producto_id: str) -> Producto:
        return self._catalogo.ver_producto(producto_id)

    def ver_carrito(self, carrito_id: str) -> Carrito:
        return self._carritos.obtener(carrito_id)

    def ver_propuesta(self, propuesta_id: str) -> PropuestaDeMandato:
        """Solo lectura: firmarla es de `EmitirMandato`, rechazarla de
        `RechazarPropuesta`."""
        return self._propuestas.obtener(propuesta_id)

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
