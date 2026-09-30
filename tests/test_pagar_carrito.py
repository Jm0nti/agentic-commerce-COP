"""`PagarCarrito`: la `Intencion` sale del carrito guardado, nunca de quien
llama. Es el camino del dinero de cuatro puntos de entrada (agente, CLI x2,
API), asi que se prueba solo, sin pasarela ni mandato."""

from __future__ import annotations

import pytest

from agora.adaptadores.persistencia.memoria.repositorio_carritos import RepositorioCarritosEnMemoria
from agora.aplicacion.pagar_carrito import PagarCarrito
from agora.dominio.catalogo.modelo import Carrito, ItemCarrito
from agora.dominio.comun.dinero import Dinero
from agora.dominio.comun.errores import CarritoDesconocido


class _EjecutarQueAnota:
    def __init__(self) -> None:
        self.llamadas: list[tuple] = []

    def __call__(self, intencion, carrito_hash=None):
        self.llamadas.append(("cobrar", intencion, carrito_hash))
        return "recibo"

    def retomar(self, intencion, aprueba, carrito_hash=None):
        self.llamadas.append(("retomar", intencion, carrito_hash, aprueba))
        return "recibo"


class _Ids:
    def nuevo(self, prefijo: str = "") -> str:
        return f"{prefijo}_nuevo"


CARRITO = Carrito(
    carrito_id="car_1",
    comercio_id="com_1",
    items=(ItemCarrito("prd_1", "Chocolatina", 3, Dinero.de_pesos(2500)),),
)


def _armar() -> tuple[PagarCarrito, _EjecutarQueAnota]:
    carritos = RepositorioCarritosEnMemoria()
    carritos.guardar(CARRITO)
    ejecutar = _EjecutarQueAnota()
    return PagarCarrito(ejecutar, carritos, _Ids()), ejecutar


def test_pagar_arma_la_intencion_desde_el_carrito_guardado() -> None:
    pagar, ejecutar = _armar()

    assert pagar("mnd_1", "car_1") == "recibo"

    (_, intencion, carrito_hash), = ejecutar.llamadas
    assert intencion.intencion_id == "int_nuevo"
    assert (intencion.mandato_id, intencion.carrito_id) == ("mnd_1", "car_1")
    assert intencion.comercio_id == "com_1"
    assert intencion.monto == Dinero.de_pesos(7500)
    assert carrito_hash == CARRITO.hash_canonico


def test_retomar_conserva_el_intencion_id_y_la_decision() -> None:
    pagar, ejecutar = _armar()

    pagar.retomar("int_viejo", "mnd_1", "car_1", aprueba=False)

    (accion, intencion, carrito_hash, aprueba), = ejecutar.llamadas
    assert (accion, intencion.intencion_id, aprueba) == ("retomar", "int_viejo", False)
    assert carrito_hash == CARRITO.hash_canonico


def test_un_carrito_que_no_existe_no_llega_a_cobrarse() -> None:
    pagar, ejecutar = _armar()

    with pytest.raises(CarritoDesconocido):
        pagar("mnd_1", "car_inventado")
    assert ejecutar.llamadas == []
