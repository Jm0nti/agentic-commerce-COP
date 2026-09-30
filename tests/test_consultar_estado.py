from __future__ import annotations

import pytest

from agora.adaptadores.persistencia.memoria import RegistroDeEstadosEnMemoria
from agora.aplicacion.consultar_estado import ConsultarEstado
from agora.model.commons.errores import EstadoDesconocido


def test_camino_feliz_devuelve_el_ultimo_estado_fijado():
    estados = RegistroDeEstadosEnMemoria()
    estados.fijar("int_1", "pendiente", "PENDING")
    estados.fijar("int_1", "aprobado", "APPROVED")  # el ultimo pisa al anterior
    consultar = ConsultarEstado(estados)

    resultado = consultar("int_1")

    assert resultado.intencion_id == "int_1"
    assert resultado.estado == "aprobado"
    assert resultado.detalle == "APPROVED"


def test_intencion_nunca_vista_levanta():
    consultar = ConsultarEstado(RegistroDeEstadosEnMemoria())
    with pytest.raises(EstadoDesconocido):
        consultar("int_nunca")
