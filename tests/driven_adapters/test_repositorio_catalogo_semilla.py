"""`RepositorioCatalogoSemilla`: lee un `catalogo.json` de mentiras (no el
real, `datos/catalogo.json`, que puede cambiar de contenido cada vez que se
corre `app_service/generar_catalogo_semilla.py`) y sirve el puerto
`RepositorioCatalogo`.
"""

from __future__ import annotations

import json

import pytest

from agora.driven_adapters.catalogo_semilla import RepositorioCatalogoSemilla
from agora.driven_adapters.catalogo_semilla import serializacion
from agora.model.catalogo.modelo import Comercio, Disponibilidad, Producto
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import ComercioDesconocido, ProductoDesconocido


def _catalogo_de_prueba(tmp_path):
    comercios = [
        Comercio(comercio_id="com_tecnox", nombre="TecnoX", categoria="tecnologia",
                 descripcion="Electronica y gadgets"),
        Comercio(comercio_id="com_librosur", nombre="LibroSur", categoria="libros"),
    ]
    productos = [
        Producto(producto_id="prd_audif", comercio_id="com_tecnox", nombre="Audifonos BT",
                  descripcion="Cancelacion de ruido", precio=Dinero.de_pesos(120_000),
                  categoria="tecnologia", disponibilidad=Disponibilidad.EN_STOCK),
        Producto(producto_id="prd_mouse", comercio_id="com_tecnox", nombre="Mouse inalambrico",
                  descripcion="2.4GHz", precio=Dinero.de_pesos(45_000),
                  categoria="tecnologia", disponibilidad=Disponibilidad.AGOTADO),
        Producto(producto_id="prd_novela", comercio_id="com_librosur", nombre="Novela ficticia",
                  descripcion="Tapa blanda", precio=Dinero.de_pesos(38_000),
                  categoria="libros", disponibilidad=Disponibilidad.EN_STOCK),
    ]
    ruta = tmp_path / "catalogo.json"
    ruta.write_text(json.dumps({
        "comercios": [serializacion.comercio_a_json(c) for c in comercios],
        "productos": [serializacion.producto_a_json(p) for p in productos],
    }), encoding="utf-8")
    return ruta


def test_buscar_comercios_sin_consulta_devuelve_todos(tmp_path):
    repo = RepositorioCatalogoSemilla(_catalogo_de_prueba(tmp_path))
    assert {c.comercio_id for c in repo.buscar_comercios()} == {"com_tecnox", "com_librosur"}


def test_buscar_comercios_filtra_por_nombre_categoria_o_descripcion(tmp_path):
    repo = RepositorioCatalogoSemilla(_catalogo_de_prueba(tmp_path))
    assert [c.comercio_id for c in repo.buscar_comercios("tecno")] == ["com_tecnox"]
    assert [c.comercio_id for c in repo.buscar_comercios("libros")] == ["com_librosur"]
    assert [c.comercio_id for c in repo.buscar_comercios("gadgets")] == ["com_tecnox"]
    assert repo.buscar_comercios("no existe nada asi") == []


def test_buscar_comercios_es_insensible_a_mayusculas(tmp_path):
    repo = RepositorioCatalogoSemilla(_catalogo_de_prueba(tmp_path))
    assert [c.comercio_id for c in repo.buscar_comercios("TECNOX")] == ["com_tecnox"]


def test_buscar_productos_filtra_por_comercio(tmp_path):
    repo = RepositorioCatalogoSemilla(_catalogo_de_prueba(tmp_path))
    productos = repo.buscar_productos("com_tecnox")
    assert {p.producto_id for p in productos} == {"prd_audif", "prd_mouse"}


def test_buscar_productos_con_consulta_filtra_dentro_del_comercio(tmp_path):
    repo = RepositorioCatalogoSemilla(_catalogo_de_prueba(tmp_path))
    productos = repo.buscar_productos("com_tecnox", "mouse")
    assert [p.producto_id for p in productos] == ["prd_mouse"]


def test_buscar_productos_con_comercio_desconocido_levanta(tmp_path):
    repo = RepositorioCatalogoSemilla(_catalogo_de_prueba(tmp_path))
    with pytest.raises(ComercioDesconocido):
        repo.buscar_productos("com_fantasma")


def test_ver_producto_devuelve_el_producto_completo(tmp_path):
    repo = RepositorioCatalogoSemilla(_catalogo_de_prueba(tmp_path))
    producto = repo.ver_producto("prd_mouse")
    assert producto.nombre == "Mouse inalambrico"
    assert producto.disponibilidad is Disponibilidad.AGOTADO
    assert producto.precio == Dinero.de_pesos(45_000)


def test_ver_producto_desconocido_levanta(tmp_path):
    repo = RepositorioCatalogoSemilla(_catalogo_de_prueba(tmp_path))
    with pytest.raises(ProductoDesconocido):
        repo.ver_producto("prd_fantasma")


def test_archivo_inexistente_levanta_con_instrucciones(tmp_path):
    with pytest.raises(FileNotFoundError, match="generar_catalogo_semilla"):
        RepositorioCatalogoSemilla(tmp_path / "no_existe.json")
