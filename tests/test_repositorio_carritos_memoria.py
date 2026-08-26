from __future__ import annotations

import pytest

from agora.adaptadores.persistencia.memoria import RepositorioCarritosEnMemoria
from agora.dominio.catalogo.modelo import Carrito, ItemCarrito
from agora.dominio.comun.dinero import Dinero
from agora.dominio.comun.errores import CarritoDesconocido


def _carrito(carrito_id: str = "car_1") -> Carrito:
    return Carrito(
        carrito_id=carrito_id, comercio_id="com_1",
        items=(ItemCarrito(producto_id="prd_1", nombre="X", cantidad=1,
                            precio_unitario=Dinero.de_pesos(1_000)),),
    )


def test_guardar_y_obtener():
    repo = RepositorioCarritosEnMemoria()
    carrito = _carrito()
    repo.guardar(carrito)
    assert repo.obtener("car_1") == carrito


def test_obtener_desconocido_levanta():
    repo = RepositorioCarritosEnMemoria()
    with pytest.raises(CarritoDesconocido):
        repo.obtener("car_x")
