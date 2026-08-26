"""`RegistroDeEstadosSQLite`. La ultima prueba es la que importa: un estado
fijado por un `RegistroDeEstadosSQLite` sobrevive a que ese objeto se
destruya y otro, apuntando al mismo archivo, lo vuelva a leer -- eso es lo
que hace falta para que `consultar_estado` (dentro del chat) vea lo que
`retomar` (en otra terminal, siempre otra terminal) acaba de resolver
(etapa 6, segunda parte).
"""

from __future__ import annotations

from agora.adaptadores.persistencia.sqlite.registro_estados import RegistroDeEstadosSQLite


def test_obtener_sin_nada_fijado_es_none(tmp_path):
    registro = RegistroDeEstadosSQLite(tmp_path / "agora.db")
    assert registro.obtener("int_x") is None


def test_fijar_y_obtener(tmp_path):
    registro = RegistroDeEstadosSQLite(tmp_path / "agora.db")
    registro.fijar("int_1", "esperando_confirmacion", "esperando_confirmacion_humana")
    assert registro.obtener("int_1") == ("esperando_confirmacion", "esperando_confirmacion_humana")


def test_fijar_sobreescribe_por_intencion_id(tmp_path):
    registro = RegistroDeEstadosSQLite(tmp_path / "agora.db")
    registro.fijar("int_1", "pendiente", "PENDING")
    registro.fijar("int_1", "rechazado", "DECLINED")
    assert registro.obtener("int_1") == ("rechazado", "DECLINED")


def test_el_estado_sobrevive_una_reconexion(tmp_path):
    ruta = tmp_path / "agora.db"

    registro_1 = RegistroDeEstadosSQLite(ruta)
    registro_1.fijar("int_1", "aprobado", "APPROVED")
    del registro_1

    registro_2 = RegistroDeEstadosSQLite(ruta)
    assert registro_2.obtener("int_1") == ("aprobado", "APPROVED")
