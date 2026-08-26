from __future__ import annotations

from agora.adaptadores.persistencia.memoria import RegistroDeEstadosEnMemoria


def test_obtener_sin_nada_fijado_es_none():
    assert RegistroDeEstadosEnMemoria().obtener("int_x") is None


def test_fijar_sobreescribe():
    registro = RegistroDeEstadosEnMemoria()
    registro.fijar("int_1", "pendiente", "PENDING")
    registro.fijar("int_1", "rechazado", "DECLINED")
    assert registro.obtener("int_1") == ("rechazado", "DECLINED")
