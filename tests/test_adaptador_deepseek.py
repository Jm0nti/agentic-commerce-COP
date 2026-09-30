"""`AdaptadorDeepSeek`: la traduccion entre el SDK de `openai` y
`ModeloNoDisponible`/`RespuestaModeloInvalida`. El doble de pruebas solo
imita la forma que el adaptador realmente usa
(`.chat.completions.create(...).choices[0].message.content`) -- no se monta
un mock del cliente `OpenAI` real ni se toca la red.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
from openai import APIConnectionError, AuthenticationError

from agora.adaptadores.llm.deepseek import AdaptadorDeepSeek, ConfiguracionDeepSeek
from agora.adaptadores.llm.deepseek.config import ConfiguracionInvalida
from agora.model.commons.errores import ModeloNoDisponible, RespuestaModeloInvalida
from agora.model.agente.gateways.modelo_lenguaje import (
    DefinicionHerramienta,
    LlamadaHerramienta,
    Mensaje,
)


@dataclass
class _Mensaje:
    content: str | None


@dataclass
class _Eleccion:
    message: _Mensaje


@dataclass
class _Respuesta:
    choices: list


class _CompletionsQueDevuelve:
    def __init__(self, contenido: str | None) -> None:
        self._contenido = contenido
        self.llamadas: list[dict] = []

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        return _Respuesta(choices=[_Eleccion(_Mensaje(self._contenido))])


class _CompletionsQueFalla:
    def __init__(self, excepcion: Exception) -> None:
        self._excepcion = excepcion

    def create(self, **kwargs):
        raise self._excepcion


class _Chat:
    def __init__(self, completions) -> None:
        self.completions = completions


class _ClienteFalso:
    def __init__(self, completions) -> None:
        self.chat = _Chat(completions)


def _config() -> ConfiguracionDeepSeek:
    return ConfiguracionDeepSeek(llave_api="sk-prueba")


def test_generar_devuelve_el_contenido_del_primer_choice():
    completions = _CompletionsQueDevuelve('{"ok": true}')
    adaptador = AdaptadorDeepSeek(_config(), _ClienteFalso(completions))

    resultado = adaptador.generar("sos un asistente", "genera algo")

    assert resultado == '{"ok": true}'


def test_generar_manda_sistema_e_instruccion_como_mensajes_separados():
    completions = _CompletionsQueDevuelve('{"ok": true}')
    adaptador = AdaptadorDeepSeek(_config(), _ClienteFalso(completions))

    adaptador.generar("sistema X", "instruccion Y")

    mensajes = completions.llamadas[0]["messages"]
    assert mensajes == [
        {"role": "system", "content": "sistema X"},
        {"role": "user", "content": "instruccion Y"},
    ]
    assert completions.llamadas[0]["response_format"] == {"type": "json_object"}
    assert completions.llamadas[0]["model"] == "deepseek-chat"


def test_generar_con_contenido_vacio_levanta_respuesta_invalida():
    completions = _CompletionsQueDevuelve(None)
    adaptador = AdaptadorDeepSeek(_config(), _ClienteFalso(completions))

    with pytest.raises(RespuestaModeloInvalida):
        adaptador.generar("s", "i")


def test_generar_con_error_de_conexion_levanta_modelo_no_disponible():
    excepcion = APIConnectionError(request=None)
    completions = _CompletionsQueFalla(excepcion)
    adaptador = AdaptadorDeepSeek(_config(), _ClienteFalso(completions))

    with pytest.raises(ModeloNoDisponible):
        adaptador.generar("s", "i")


def test_generar_con_llave_invalida_levanta_modelo_no_disponible():
    """`AuthenticationError` tambien hereda de `OpenAIError` -- se traduce
    igual que cualquier otro fallo del proveedor, no se distingue una llave
    mala de un timeout. Quien llama solo necesita saber que no se pudo."""
    peticion = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    respuesta_401 = httpx.Response(401, request=peticion, json={"error": "llave invalida"})
    excepcion = AuthenticationError(
        message="llave invalida", response=respuesta_401, body=None
    )
    completions = _CompletionsQueFalla(excepcion)
    adaptador = AdaptadorDeepSeek(_config(), _ClienteFalso(completions))

    with pytest.raises(ModeloNoDisponible):
        adaptador.generar("s", "i")


def test_configuracion_sin_llave_es_invalida():
    with pytest.raises(ConfiguracionInvalida):
        ConfiguracionDeepSeek(llave_api="")


# --------------------------------------------------------------------------- #
# responder() -- etapa 5, el loop de tool-calling.
# --------------------------------------------------------------------------- #


@dataclass
class _FuncionLlamada:
    name: str
    arguments: str


@dataclass
class _LlamadaCruda:
    id: str
    function: _FuncionLlamada


@dataclass
class _MensajeConLlamadas:
    content: str | None
    tool_calls: list


def test_responder_sin_llamadas_devuelve_solo_contenido():
    mensaje = _MensajeConLlamadas(content="hola", tool_calls=[])
    completions = _CompletionsQueDevuelveMensaje(mensaje)
    adaptador = AdaptadorDeepSeek(_config(), _ClienteFalso(completions))

    resultado = adaptador.responder([Mensaje(rol="user", contenido="hola")], [])

    assert resultado.contenido == "hola"
    assert resultado.llamadas == ()
    assert completions.llamadas[0]["tools"] is None  # sin herramientas, no se manda `tools`


def test_responder_traduce_las_llamadas_a_herramientas():
    cruda = _LlamadaCruda(id="call_1", function=_FuncionLlamada(name="ver_producto", arguments='{"producto_id": "prd_1"}'))
    mensaje = _MensajeConLlamadas(content=None, tool_calls=[cruda])
    completions = _CompletionsQueDevuelveMensaje(mensaje)
    adaptador = AdaptadorDeepSeek(_config(), _ClienteFalso(completions))
    herramienta = DefinicionHerramienta(
        nombre="ver_producto", descripcion="detalle",
        esquema={"type": "object", "properties": {"producto_id": {"type": "string"}}},
    )

    resultado = adaptador.responder([Mensaje(rol="user", contenido="que es prd_1?")], [herramienta])

    assert resultado.contenido is None
    assert len(resultado.llamadas) == 1
    assert resultado.llamadas[0].id == "call_1"
    assert resultado.llamadas[0].nombre == "ver_producto"
    assert resultado.llamadas[0].argumentos == {"producto_id": "prd_1"}
    cuerpo_herramientas = completions.llamadas[0]["tools"]
    assert cuerpo_herramientas[0]["function"]["name"] == "ver_producto"


def test_responder_manda_los_mensajes_de_rol_tool_con_su_id():
    mensaje = _MensajeConLlamadas(content="listo", tool_calls=[])
    completions = _CompletionsQueDevuelveMensaje(mensaje)
    adaptador = AdaptadorDeepSeek(_config(), _ClienteFalso(completions))
    mensajes = [
        Mensaje(rol="user", contenido="que es prd_1?"),
        Mensaje(
            rol="assistant", contenido=None,
            llamadas=(LlamadaHerramienta(id="call_1", nombre="ver_producto", argumentos={"producto_id": "prd_1"}),),
        ),
        Mensaje(rol="tool", contenido='{"nombre": "Audifonos"}', id_llamada="call_1", nombre_herramienta="ver_producto"),
    ]

    adaptador.responder(mensajes, [])

    enviados = completions.llamadas[0]["messages"]
    assert enviados[1]["tool_calls"][0]["id"] == "call_1"
    assert enviados[1]["tool_calls"][0]["function"]["arguments"] == '{"producto_id": "prd_1"}'
    assert enviados[2]["tool_call_id"] == "call_1"
    assert enviados[2]["name"] == "ver_producto"


def test_responder_con_error_de_conexion_levanta_modelo_no_disponible():
    excepcion = APIConnectionError(request=None)
    completions = _CompletionsQueFalla(excepcion)
    adaptador = AdaptadorDeepSeek(_config(), _ClienteFalso(completions))

    with pytest.raises(ModeloNoDisponible):
        adaptador.responder([Mensaje(rol="user", contenido="hola")], [])


def test_responder_con_argumentos_que_no_son_json_valido_levanta():
    cruda = _LlamadaCruda(id="call_1", function=_FuncionLlamada(name="x", arguments="no es json"))
    mensaje = _MensajeConLlamadas(content=None, tool_calls=[cruda])
    completions = _CompletionsQueDevuelveMensaje(mensaje)
    adaptador = AdaptadorDeepSeek(_config(), _ClienteFalso(completions))

    with pytest.raises(RespuestaModeloInvalida):
        adaptador.responder([Mensaje(rol="user", contenido="hola")], [])


class _EleccionConMensaje:
    def __init__(self, message) -> None:
        self.message = message


class _RespuestaConMensaje:
    def __init__(self, message) -> None:
        self.choices = [_EleccionConMensaje(message)]


class _CompletionsQueDevuelveMensaje:
    def __init__(self, mensaje) -> None:
        self._mensaje = mensaje
        self.llamadas: list[dict] = []

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        return _RespuestaConMensaje(self._mensaje)
