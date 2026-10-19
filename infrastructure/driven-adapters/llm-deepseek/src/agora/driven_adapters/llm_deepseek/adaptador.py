"""Implementa `puertos.modelo_lenguaje.ModeloDeLenguaje` contra la API de
DeepSeek, vía el SDK `openai` (compatible, solo cambia `base_url`).

`cliente` se puede inyectar -- mismo patron que `ClienteWompi` con
`cliente_http` -- para que las pruebas no necesiten red ni una llave real.
Solo se le pide al cliente que tenga la forma
`.chat.completions.create(...).choices[0].message.content`; no se importa el
tipo `OpenAI` en la firma para no atar las pruebas a esa clase concreta.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from openai import OpenAI, OpenAIError

from ...model.commons.errores import ModeloNoDisponible, RespuestaModeloInvalida
from ...model.agente.gateways.modelo_lenguaje import (
    DefinicionHerramienta,
    LlamadaHerramienta,
    Mensaje,
    RespuestaModelo,
)
from .config import ConfiguracionDeepSeek


class _ClienteChatCompletions(Protocol):
    """La unica porcion del cliente de OpenAI que este adaptador usa. Un
    doble de pruebas solo necesita cumplir esto, no ser un `OpenAI` de
    verdad."""

    chat: Any


class AdaptadorDeepSeek:
    """Implementa `puertos.modelo_lenguaje.ModeloDeLenguaje`."""

    nombre = "deepseek"

    def __init__(
        self,
        config: ConfiguracionDeepSeek,
        cliente: _ClienteChatCompletions | None = None,
    ) -> None:
        self._config = config
        self._cliente = cliente or OpenAI(
            api_key=config.llave_api,
            base_url=config.url_base,
            timeout=config.timeout_segundos,
        )

    def generar(self, sistema: str, instruccion: str) -> str:
        try:
            respuesta = self._cliente.chat.completions.create(
                model=self._config.modelo,
                messages=[
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": instruccion},
                ],
                response_format={"type": "json_object"},
            )
        except OpenAIError as exc:
            # Red, timeout, 5xx, llave invalida -- todo lo que el SDK de
            # OpenAI empaqueta bajo su propia jerarquia se traduce a la
            # nuestra, igual que `ClienteWompi._pedir` hace con `httpx.
            # HTTPError`. Quien llama no deberia tener que conocer las
            # excepciones de un SDK ajeno.
            raise ModeloNoDisponible(f"DeepSeek no respondio: {exc}") from exc

        contenido = respuesta.choices[0].message.content if respuesta.choices else None
        if not contenido:
            raise RespuestaModeloInvalida(
                "DeepSeek devolvio una respuesta vacia",
                detalle_proveedor={"respuesta": str(respuesta)[:500]},
            )
        return contenido

    def responder(
        self, mensajes: list[Mensaje], herramientas: list[DefinicionHerramienta]
    ) -> RespuestaModelo:
        try:
            respuesta = self._cliente.chat.completions.create(
                model=self._config.modelo,
                messages=[_mensaje_a_openai(m) for m in mensajes],
                tools=[_herramienta_a_openai(h) for h in herramientas] or None,
            )
        except OpenAIError as exc:
            raise ModeloNoDisponible(f"DeepSeek no respondio: {exc}") from exc

        if not respuesta.choices:
            raise RespuestaModeloInvalida(
                "DeepSeek no devolvio ninguna eleccion",
                detalle_proveedor={"respuesta": str(respuesta)[:500]},
            )

        mensaje = respuesta.choices[0].message
        llamadas = tuple(
            LlamadaHerramienta(
                id=tc.id,
                nombre=tc.function.name,
                argumentos=_argumentos_desde(tc.function.arguments),
            )
            for tc in (mensaje.tool_calls or [])
        )
        return RespuestaModelo(contenido=mensaje.content, llamadas=llamadas)


def _mensaje_a_openai(m: Mensaje) -> dict[str, Any]:
    """Traduce `puertos.modelo_lenguaje.Mensaje` al dict que espera
    Chat Completions. Los campos que no aplican a un rol dado (`tool_calls`
    en algo que no sea "assistant", `tool_call_id`/`name` en algo que no sea
    "tool") simplemente no se ponen -- se confia en que quien arma el
    `Mensaje` (`usecase/agente/conversacion.py`) ya respeto esa forma."""
    cuerpo: dict[str, Any] = {"role": m.rol, "content": m.contenido}
    if m.llamadas:
        cuerpo["tool_calls"] = [
            {
                "id": llamada.id,
                "type": "function",
                "function": {
                    "name": llamada.nombre,
                    "arguments": json.dumps(llamada.argumentos, ensure_ascii=False),
                },
            }
            for llamada in m.llamadas
        ]
    if m.id_llamada is not None:
        cuerpo["tool_call_id"] = m.id_llamada
    if m.nombre_herramienta is not None:
        cuerpo["name"] = m.nombre_herramienta
    return cuerpo


def _herramienta_a_openai(h: DefinicionHerramienta) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": h.nombre, "description": h.descripcion, "parameters": h.esquema},
    }


def _argumentos_desde(bruto: str | None) -> dict[str, Any]:
    if not bruto:
        return {}
    try:
        valor = json.loads(bruto)
    except ValueError as exc:
        raise RespuestaModeloInvalida(
            "DeepSeek pidio una herramienta con argumentos que no son JSON valido",
            detalle_proveedor={"argumentos": bruto[:500]},
        ) from exc
    if not isinstance(valor, dict):
        raise RespuestaModeloInvalida(
            "los argumentos de una herramienta no son un objeto JSON",
            detalle_proveedor={"argumentos": bruto[:500]},
        )
    return valor
