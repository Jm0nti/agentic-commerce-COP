"""El puerto del modelo de lenguaje.

`generar()` es la porcion angosta que se construyo primero, para
`GenerarCatalogoSemillaUseCase` (una sola llamada, sin memoria de turnos, que espera
JSON de vuelta). El docstring original de este archivo explicaba por que
`responder(mensajes, herramientas) -> RespuestaModelo` -- el loop de turnos
con tool-calling que describe `docs/arquitectura.md`, seccion 4 -- todavia
no existia: construirlo sin un `usecase/agente/conversacion.py` real que lo llamara
habria sido disenar a ciegas. Esta etapa agrega ese caso de uso real
(`usecase/agente/conversacion.py`), asi que ahora `responder()` se agrega tambien,
contestando las preguntas que antes no tenian con que contestarse:

    ¿lleva llamadas a herramientas parciales?     No: una respuesta trae
                                                   contenido de texto, o
                                                   llamadas a herramientas,
                                                   o ambos -- nunca una
                                                   llamada a medio construir.
    ¿como se reintenta una que fallo?             No es este puerto: quien
                                                   ejecuta la herramienta
                                                   (`usecase/agente/conversacion.py`)
                                                   decide si reintenta,
                                                   armando un nuevo mensaje
                                                   de rol "tool" con el error.

`DefinicionHerramienta` es DELIBERADAMENTE mas angosta que `agente.
herramientas.Herramienta`: no lleva `ejecutar` (un `Callable`). Este puerto
no puede importar `usecase/agente/` (la regla de dependencia es al reves: `usecase/agente/`
importa `model/<agregado>/gateways/`, nunca al contrario), asi que solo describe lo que un
proveedor de LLM necesita para anunciar una herramienta -- nombre,
descripcion, esquema de argumentos -- y `usecase/agente/conversacion.py` es quien
traduce entre las dos formas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class LlamadaHerramienta:
    """Una invocacion de herramienta que el modelo pidio hacer. `id` es del
    proveedor (lo necesita `AdaptadorDeepSeek` para poder mandar la
    respuesta de vuelta atada a la llamada correcta si hay mas de una en el
    mismo turno)."""

    id: str
    nombre: str
    argumentos: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Mensaje:
    """Un turno de la conversacion, en la forma minima que todo proveedor de
    chat con tool-calling entiende: sistema, usuario, asistente, o el
    resultado de una herramienta.

    `llamadas` solo tiene sentido en un mensaje de rol "assistant" (lo que el
    modelo pidio hacer). `id_llamada`/`nombre_herramienta` solo tienen
    sentido en uno de rol "tool" (la respuesta a esa llamada puntual) -- son
    excluyentes con `llamadas`, no una forma generica que sirva para
    cualquier rol; forzar los dos casos en el mismo shape sin marcar cual
    campo aplica a cual rol seria la clase de ambiguedad que este puerto
    evito hasta tener un llamador real.
    """

    rol: str  # "system" | "user" | "assistant" | "tool"
    contenido: str | None = None
    llamadas: tuple[LlamadaHerramienta, ...] = ()
    id_llamada: str | None = None
    nombre_herramienta: str | None = None


@dataclass(frozen=True)
class DefinicionHerramienta:
    nombre: str
    descripcion: str
    esquema: dict[str, Any]


@dataclass(frozen=True)
class RespuestaModelo:
    """Lo que el modelo devolvio en un turno: texto para mostrar, llamadas a
    herramientas para ejecutar, o ambos. Nunca ninguno de los dos a medias --
    ver el docstring del modulo."""

    contenido: str | None = None
    llamadas: tuple[LlamadaHerramienta, ...] = ()


class ModeloDeLenguaje(Protocol):
    def generar(self, sistema: str, instruccion: str) -> str:
        """Una llamada sin memoria de turnos anteriores: `sistema` fija el
        rol, `instruccion` es el pedido puntual. Devuelve el texto crudo de
        la respuesta -- quien llama decide como interpretarlo (hoy, siempre
        como JSON) y que hacer si no calza; este puerto no sabe ni le
        importa que forma se espera.

        Levanta `ModeloNoDisponible` si el proveedor no respondio (red,
        timeout, 5xx) y `RespuestaModeloInvalida` nunca la levanta este
        metodo -- esa validacion es de quien llama, porque solo quien llama
        sabe que forma esperaba.
        """
        ...

    def responder(
        self, mensajes: list[Mensaje], herramientas: list[DefinicionHerramienta]
    ) -> RespuestaModelo:
        """Un turno del loop de conversacion (`usecase/agente/conversacion.py`).
        `mensajes` es el historial completo hasta ahora (el proveedor no
        guarda estado entre llamadas); `herramientas` es lo que el modelo
        puede pedir ejecutar en este turno -- vacia es una respuesta valida,
        no un error, para el ultimo turno de una charla que ya no necesita
        herramientas.

        Levanta `ModeloNoDisponible` en las mismas condiciones que
        `generar()`.
        """
        ...
