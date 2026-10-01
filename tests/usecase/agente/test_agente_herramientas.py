"""`construir_herramientas`: las seis funciones que le llegan (ya cerradas
sobre sus dependencias por `composicion/agente.py`, aca solo dobles) se
convierten en el catalogo autorizado, con los esquemas correctos, y siguen
pasando `validar_catalogo`."""

from __future__ import annotations

from agora.usecase.agente.herramientas import CATALOGO_DE_HERRAMIENTAS, construir_herramientas


def _funcion(*_a, **_k):
    return {"ok": True}


def _armar():
    return construir_herramientas(
        buscar_comercios=_funcion,
        buscar_productos=_funcion,
        ver_producto=_funcion,
        armar_carrito=_funcion,
        pagar=_funcion,
        consultar_estado=_funcion,
    )


def test_arma_las_seis_herramientas_del_catalogo_autorizado():
    herramientas = _armar()
    assert {h.nombre for h in herramientas} == set(CATALOGO_DE_HERRAMIENTAS)


def test_cada_herramienta_tiene_esquema_de_objeto_json():
    for h in _armar():
        assert h.esquema["type"] == "object"
        assert "properties" in h.esquema


def test_armar_carrito_y_pagar_exigen_sus_campos_obligatorios():
    herramientas = {h.nombre: h for h in _armar()}
    assert set(herramientas["armar_carrito"].esquema["required"]) == {"comercio_id", "items"}
    assert set(herramientas["pagar"].esquema["required"]) == {"mandato_id", "carrito_id"}


def test_las_funciones_pasadas_quedan_atadas_tal_cual():
    herramientas = {h.nombre: h for h in _armar()}
    assert herramientas["buscar_comercios"].ejecutar is _funcion
