"""`RepositorioPropuestasSQLite`. La prueba que importa es la ultima: una
propuesta guardada por un `RepositorioPropuestasSQLite` sobrevive a que ese
objeto se destruya y otro, apuntando al mismo archivo, la vuelva a leer --
eso es lo que hace falta para que `entradas/cli/firmar`, corrido en otra
terminal que la que armo el chat, pueda encontrarla (etapa 6).
"""

from __future__ import annotations

import pytest

from agora.driven_adapters.persistencia_sqlite.repositorio_propuestas import (
    RepositorioPropuestasSQLite,
)
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import PropuestaDesconocida
from agora.model.mandato.modelo import PropuestaDeMandato


def _propuesta(**kw) -> PropuestaDeMandato:
    base = dict(
        propuesta_id="prp_1", carrito_id="car_1", comercio_id="com_1",
        monto_max=Dinero.de_pesos(120_000), usos_max=1, vigencia_minutos=30,
        categorias=("tecnologia",), justificacion="audifonos para Juan",
    )
    base.update(kw)
    return PropuestaDeMandato(**base)


def test_guardar_y_obtener(tmp_path):
    repo = RepositorioPropuestasSQLite(tmp_path / "agora.db")
    propuesta = _propuesta()
    repo.guardar(propuesta)

    assert repo.obtener("prp_1") == propuesta


def test_obtener_desconocida_levanta(tmp_path):
    repo = RepositorioPropuestasSQLite(tmp_path / "agora.db")
    with pytest.raises(PropuestaDesconocida):
        repo.obtener("prp_x")


def test_guardar_es_upsert_por_propuesta_id(tmp_path):
    repo = RepositorioPropuestasSQLite(tmp_path / "agora.db")
    repo.guardar(_propuesta(usos_max=1))
    repo.guardar(_propuesta(usos_max=5))

    assert repo.obtener("prp_1").usos_max == 5


def test_la_propuesta_sobrevive_una_reconexion(tmp_path):
    ruta = tmp_path / "agora.db"
    propuesta = _propuesta()

    repo_1 = RepositorioPropuestasSQLite(ruta)
    repo_1.guardar(propuesta)
    del repo_1

    repo_2 = RepositorioPropuestasSQLite(ruta)
    assert repo_2.obtener("prp_1") == propuesta
