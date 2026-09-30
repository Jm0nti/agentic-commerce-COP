"""`dominio/catalogo/modelo.py`: los campos nuevos de la etapa 5
(`Disponibilidad`, `Comercio.descripcion`, `Producto.disponibilidad`).

`Carrito`/`ItemCarrito` ya tienen su propia cobertura en `tests/
test_dominio.py` (el hash canonico, la deteccion de un carrito alterado);
este archivo solo cubre lo que se agrego encima.
"""

from __future__ import annotations

from agora.model.catalogo.modelo import Comercio, Disponibilidad, Producto
from agora.model.commons.dinero import Dinero


def test_comercio_descripcion_por_defecto_es_vacia():
    c = Comercio(comercio_id="com_1", nombre="TiendaX", categoria="tecnologia")
    assert c.descripcion == ""
    assert c.simulado is True


def test_producto_disponibilidad_por_defecto_es_en_stock():
    p = Producto(
        producto_id="prd_1", comercio_id="com_1", nombre="Audifonos",
        descripcion="BT", precio=Dinero.de_pesos(50_000), categoria="tecnologia",
    )
    assert p.disponibilidad is Disponibilidad.EN_STOCK


def test_disponibilidad_tiene_los_tres_valores_del_feed_de_acp_menos_unknown():
    assert {d.value for d in Disponibilidad} == {"en_stock", "agotado", "pedido_anticipado"}
