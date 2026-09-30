from __future__ import annotations

import pytest

from agora.adaptadores.persistencia.memoria import RepositorioPropuestasEnMemoria
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import PropuestaDesconocida
from agora.model.mandato.modelo import PropuestaDeMandato


def _propuesta(propuesta_id: str = "prp_1") -> PropuestaDeMandato:
    return PropuestaDeMandato(
        propuesta_id=propuesta_id, carrito_id="car_1", comercio_id="com_1",
        monto_max=Dinero.de_pesos(1_000),
    )


def test_guardar_y_obtener():
    repo = RepositorioPropuestasEnMemoria()
    propuesta = _propuesta()
    repo.guardar(propuesta)
    assert repo.obtener("prp_1") == propuesta


def test_obtener_desconocida_levanta():
    repo = RepositorioPropuestasEnMemoria()
    with pytest.raises(PropuestaDesconocida):
        repo.obtener("prp_x")
