"""`Agente.turno`: el loop de tool-calling, contra un `ModeloDeLenguaje`
guionado (una lista de `RespuestaModelo` fijas, una por llamada a
`responder`) -- no toca DeepSeek ni la red."""

from __future__ import annotations

import json

import pytest

from agora.usecase.agente.conversacion import Agente, LimiteDeTurnosExcedido
from agora.usecase.agente.herramientas import Herramienta
from agora.model.commons.errores import ProductoDesconocido
from agora.model.agente.gateways.modelo_lenguaje import LlamadaHerramienta, Mensaje, RespuestaModelo


class _ModeloGuionado:
    def __init__(self, respuestas: list[RespuestaModelo]) -> None:
        self._respuestas = list(respuestas)
        self.llamadas: list[tuple[list[Mensaje], list]] = []

    def generar(self, sistema: str, instruccion: str) -> str:
        raise AssertionError("no deberia usarse en el loop de conversacion")

    def responder(self, mensajes, herramientas):
        self.llamadas.append((list(mensajes), list(herramientas)))
        return self._respuestas.pop(0)


def _herramienta_ver_producto(**kw):
    if kw.get("producto_id") != "prd_1":
        raise ProductoDesconocido(f"no existe '{kw.get('producto_id')}'")
    return {"producto_id": "prd_1", "nombre": "Audifonos"}


def _agente(respuestas: list[RespuestaModelo]) -> Agente:
    modelo = _ModeloGuionado(respuestas)
    herramienta = Herramienta(
        nombre="ver_producto", descripcion="detalle de un producto",
        esquema={"type": "object", "properties": {"producto_id": {"type": "string"}}},
        ejecutar=_herramienta_ver_producto,
    )
    return Agente(modelo=modelo, herramientas=[herramienta]), modelo


def test_turno_sin_llamadas_devuelve_el_texto_directo():
    agente, modelo = _agente([RespuestaModelo(contenido="hola, en que te ayudo?")])
    conversacion = agente.iniciar()

    respuesta = agente.turno(conversacion, "hola")

    assert respuesta == "hola, en que te ayudo?"
    assert len(modelo.llamadas) == 1
    # system + user + assistant
    assert [m.rol for m in conversacion.mensajes] == ["system", "user", "assistant"]


def test_turno_ejecuta_una_herramienta_y_sigue_hasta_el_texto_final():
    llamada = LlamadaHerramienta(id="call_1", nombre="ver_producto", argumentos={"producto_id": "prd_1"})
    agente, modelo = _agente([
        RespuestaModelo(contenido=None, llamadas=(llamada,)),
        RespuestaModelo(contenido="son Audifonos"),
    ])
    conversacion = agente.iniciar()

    respuesta = agente.turno(conversacion, "que es prd_1?")

    assert respuesta == "son Audifonos"
    assert len(modelo.llamadas) == 2
    roles = [m.rol for m in conversacion.mensajes]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    mensaje_tool = conversacion.mensajes[3]
    assert mensaje_tool.id_llamada == "call_1"
    assert json.loads(mensaje_tool.contenido) == {"producto_id": "prd_1", "nombre": "Audifonos"}


def test_una_herramienta_que_levanta_error_de_dominio_no_tumba_el_turno():
    llamada = LlamadaHerramienta(id="call_1", nombre="ver_producto", argumentos={"producto_id": "prd_x"})
    agente, _ = _agente([
        RespuestaModelo(contenido=None, llamadas=(llamada,)),
        RespuestaModelo(contenido="ese producto no existe"),
    ])
    conversacion = agente.iniciar()

    respuesta = agente.turno(conversacion, "que es prd_x?")

    assert respuesta == "ese producto no existe"
    mensaje_tool = conversacion.mensajes[3]
    assert json.loads(mensaje_tool.contenido)["tipo"] == "ProductoDesconocido"


def test_llamada_a_herramienta_desconocida_no_tumba_el_turno():
    llamada = LlamadaHerramienta(id="call_1", nombre="no_existe", argumentos={})
    agente, _ = _agente([
        RespuestaModelo(contenido=None, llamadas=(llamada,)),
        RespuestaModelo(contenido="listo"),
    ])
    conversacion = agente.iniciar()

    assert agente.turno(conversacion, "hola") == "listo"
    assert "desconocida" in conversacion.mensajes[3].contenido


def test_supera_el_limite_de_turnos_levanta():
    llamada = LlamadaHerramienta(id="call_1", nombre="ver_producto", argumentos={"producto_id": "prd_1"})
    respuestas = [RespuestaModelo(contenido=None, llamadas=(llamada,)) for _ in range(25)]
    agente, _ = _agente(respuestas)
    conversacion = agente.iniciar()

    with pytest.raises(LimiteDeTurnosExcedido):
        agente.turno(conversacion, "segui pidiendo cosas")
