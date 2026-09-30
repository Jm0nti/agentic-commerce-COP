"""`GenerarCatalogoSemilla`: valida lo que un `ModeloDeLenguaje` contesta
antes de convertirlo en `Comercio`/`Producto`. Ningun caso aqui toca DeepSeek
de verdad -- el doble solo devuelve el texto que cada prueba necesita.
"""

from __future__ import annotations

import json

import pytest

from agora.aplicacion.generar_catalogo_semilla import GenerarCatalogoSemilla
from agora.model.catalogo.modelo import Disponibilidad
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import RespuestaModeloInvalida


class _IdsDeterministas:
    """No usa `uuid` para que las aserciones sobre ids sean legibles."""

    def __init__(self) -> None:
        self._contador = 0

    def nuevo(self, prefijo: str = "") -> str:
        self._contador += 1
        return f"{prefijo}_{self._contador}" if prefijo else str(self._contador)


class _ModeloQueDevuelve:
    def __init__(self, texto: str) -> None:
        self._texto = texto
        self.llamadas: list[tuple[str, str]] = []

    def generar(self, sistema: str, instruccion: str) -> str:
        self.llamadas.append((sistema, instruccion))
        return self._texto


_RESPUESTA_VALIDA = json.dumps({
    "comercio": {"nombre": "TecnoX", "descripcion": "Electronica y gadgets"},
    "productos": [
        {"nombre": "Audifonos BT", "descripcion": "Cancelacion de ruido",
         "precio_cop": 120_000, "disponibilidad": "en_stock"},
        {"nombre": "Mouse inalambrico", "descripcion": "2.4GHz",
         "precio_cop": 45_000, "disponibilidad": "agotado"},
    ],
})


def _armar(texto: str) -> tuple[GenerarCatalogoSemilla, _ModeloQueDevuelve]:
    modelo = _ModeloQueDevuelve(texto)
    generar = GenerarCatalogoSemilla(modelo, _IdsDeterministas())
    return generar, modelo


def test_camino_feliz_arma_comercio_y_productos():
    generar, _ = _armar(_RESPUESTA_VALIDA)

    generado = generar("tecnologia", cantidad_productos=2)

    assert generado.comercio.nombre == "TecnoX"
    assert generado.comercio.categoria == "tecnologia"
    assert generado.comercio.descripcion == "Electronica y gadgets"
    assert generado.comercio.comercio_id == "com_1"
    assert len(generado.productos) == 2

    audifonos, mouse = generado.productos
    assert audifonos.nombre == "Audifonos BT"
    assert audifonos.precio == Dinero.de_pesos(120_000)
    assert audifonos.disponibilidad is Disponibilidad.EN_STOCK
    assert audifonos.comercio_id == generado.comercio.comercio_id
    assert mouse.disponibilidad is Disponibilidad.AGOTADO


def test_le_pide_al_modelo_la_cantidad_de_productos_correcta():
    generar, modelo = _armar(_RESPUESTA_VALIDA)

    generar("tecnologia", cantidad_productos=2)

    _, instruccion = modelo.llamadas[0]
    assert "2 productos" in instruccion
    assert "tecnologia" in instruccion


def test_disponibilidad_ausente_usa_en_stock_por_defecto():
    texto = json.dumps({
        "comercio": {"nombre": "TecnoX"},
        "productos": [{"nombre": "Cable", "descripcion": "USB-C", "precio_cop": 25_000}],
    })
    generar, _ = _armar(texto)

    generado = generar("tecnologia")

    assert generado.productos[0].disponibilidad is Disponibilidad.EN_STOCK


def test_json_invalido_levanta_respuesta_invalida():
    generar, _ = _armar("esto no es JSON")
    with pytest.raises(RespuestaModeloInvalida, match="JSON valido"):
        generar("tecnologia")


def test_sin_campo_comercio_levanta():
    texto = json.dumps({"productos": []})
    generar, _ = _armar(texto)
    with pytest.raises(RespuestaModeloInvalida, match="comercio"):
        generar("tecnologia")


def test_sin_productos_levanta():
    texto = json.dumps({"comercio": {"nombre": "TecnoX"}, "productos": []})
    generar, _ = _armar(texto)
    with pytest.raises(RespuestaModeloInvalida, match="sin productos"):
        generar("tecnologia")


def test_precio_negativo_levanta():
    texto = json.dumps({
        "comercio": {"nombre": "TecnoX"},
        "productos": [{"nombre": "Cable", "descripcion": "x", "precio_cop": -100}],
    })
    generar, _ = _armar(texto)
    with pytest.raises(RespuestaModeloInvalida, match="positivo"):
        generar("tecnologia")


def test_precio_como_booleano_levanta():
    """`bool` es subclase de `int` en Python -- sin la guarda explicita,
    `"precio_cop": true` pasaria como si fuera un precio de 1 peso."""
    texto = json.dumps({
        "comercio": {"nombre": "TecnoX"},
        "productos": [{"nombre": "Cable", "descripcion": "x", "precio_cop": True}],
    })
    generar, _ = _armar(texto)
    with pytest.raises(RespuestaModeloInvalida):
        generar("tecnologia")


def test_disponibilidad_invalida_levanta():
    texto = json.dumps({
        "comercio": {"nombre": "TecnoX"},
        "productos": [{"nombre": "Cable", "descripcion": "x", "precio_cop": 100,
                        "disponibilidad": "en_camino"}],
    })
    generar, _ = _armar(texto)
    with pytest.raises(RespuestaModeloInvalida, match="disponibilidad"):
        generar("tecnologia")


def test_nombre_de_comercio_vacio_levanta():
    texto = json.dumps({"comercio": {"nombre": "   "}, "productos": [
        {"nombre": "Cable", "descripcion": "x", "precio_cop": 100},
    ]})
    generar, _ = _armar(texto)
    with pytest.raises(RespuestaModeloInvalida):
        generar("tecnologia")


def test_cantidad_productos_menor_a_uno_levanta_sin_llamar_al_modelo():
    generar, modelo = _armar(_RESPUESTA_VALIDA)
    with pytest.raises(ValueError):
        generar("tecnologia", cantidad_productos=0)
    assert modelo.llamadas == []
