"""`NavegarCatalogo`: las busquedas delegan tal cual, `armar_carrito` es
donde vive la regla (un solo comercio por carrito, nada `AGOTADO`).
"""

from __future__ import annotations

import pytest

from agora.adaptadores.persistencia.memoria import (
    RepositorioCarritosEnMemoria,
    RepositorioPropuestasEnMemoria,
)
from agora.adaptadores.sistema import GeneradorIdsUuid
from agora.aplicacion.navegar_catalogo import ItemPedido, NavegarCatalogo
from agora.model.catalogo.modelo import Comercio, Disponibilidad, Producto
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import (
    ComercioDesconocido,
    ProductoDeOtroComercio,
    ProductoNoDisponible,
)

COMERCIO = Comercio(comercio_id="com_1", nombre="TecnoX", categoria="tecnologia")
OTRO_COMERCIO = Comercio(comercio_id="com_2", nombre="LibroSur", categoria="libros")

AUDIFONOS = Producto(
    producto_id="prd_audifonos", comercio_id="com_1", nombre="Audifonos",
    descripcion="BT", precio=Dinero.de_pesos(120_000), categoria="tecnologia",
)
MOUSE_AGOTADO = Producto(
    producto_id="prd_mouse", comercio_id="com_1", nombre="Mouse",
    descripcion="inalambrico", precio=Dinero.de_pesos(45_000), categoria="tecnologia",
    disponibilidad=Disponibilidad.AGOTADO,
)
LIBRO = Producto(
    producto_id="prd_libro", comercio_id="com_2", nombre="Libro",
    descripcion="novela", precio=Dinero.de_pesos(60_000), categoria="libros",
)


class _CatalogoFalso:
    def __init__(self) -> None:
        self._comercios = {COMERCIO.comercio_id: COMERCIO, OTRO_COMERCIO.comercio_id: OTRO_COMERCIO}
        self._productos = {p.producto_id: p for p in (AUDIFONOS, MOUSE_AGOTADO, LIBRO)}

    def buscar_comercios(self, consulta: str = "") -> list[Comercio]:
        return list(self._comercios.values())

    def buscar_productos(self, comercio_id: str, consulta: str = "") -> list[Producto]:
        if comercio_id not in self._comercios:
            raise ComercioDesconocido(comercio_id)
        return [p for p in self._productos.values() if p.comercio_id == comercio_id]

    def ver_producto(self, producto_id: str) -> Producto:
        return self._productos[producto_id]


def _armar() -> NavegarCatalogo:
    return NavegarCatalogo(
        catalogo=_CatalogoFalso(), carritos=RepositorioCarritosEnMemoria(),
        ids=GeneradorIdsUuid(), propuestas=RepositorioPropuestasEnMemoria(),
    )


def test_buscar_comercios_delega():
    nav = _armar()
    assert {c.comercio_id for c in nav.buscar_comercios()} == {"com_1", "com_2"}


def test_buscar_productos_delega_y_propaga_comercio_desconocido():
    nav = _armar()
    assert [p.producto_id for p in nav.buscar_productos("com_1")] == ["prd_audifonos", "prd_mouse"]
    with pytest.raises(ComercioDesconocido):
        nav.buscar_productos("com_x")


def test_armar_carrito_camino_feliz():
    nav = _armar()
    carrito, propuesta = nav.armar_carrito("com_1", [ItemPedido("prd_audifonos", 2)])

    assert carrito.comercio_id == "com_1"
    assert carrito.total == Dinero.de_pesos(240_000)
    assert propuesta.carrito_id == carrito.carrito_id
    assert propuesta.comercio_id == "com_1"
    assert propuesta.monto_max == carrito.total
    assert propuesta.usos_max == 1


def test_armar_carrito_persiste_en_repositorio_carritos():
    nav = _armar()
    carrito, _ = nav.armar_carrito("com_1", [ItemPedido("prd_audifonos")])
    assert nav._carritos.obtener(carrito.carrito_id) == carrito


def test_armar_carrito_persiste_la_propuesta_en_repositorio_propuestas():
    """Etapa 6: sin esto, `entradas/cli/firmar` (otro proceso) nunca podria
    encontrar la propuesta que el chat le mostro a la persona."""
    nav = _armar()
    _, propuesta = nav.armar_carrito("com_1", [ItemPedido("prd_audifonos")])
    assert nav._propuestas.obtener(propuesta.propuesta_id) == propuesta


def test_armar_carrito_con_producto_de_otro_comercio_levanta():
    nav = _armar()
    with pytest.raises(ProductoDeOtroComercio):
        nav.armar_carrito("com_1", [ItemPedido("prd_libro")])


def test_armar_carrito_con_producto_agotado_levanta():
    nav = _armar()
    with pytest.raises(ProductoNoDisponible):
        nav.armar_carrito("com_1", [ItemPedido("prd_mouse")])
