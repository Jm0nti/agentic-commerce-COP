"""El loop de turnos. `docs/arquitectura-v2.md`, seccion 4: `responder(mensajes,
herramientas) -> RespuestaModelo`, corrido hasta que el modelo conteste con
texto y sin mas llamadas pendientes -- o hasta `MAX_TURNOS_POR_CONVERSACION`
(`politica.py`).

    usuario -> Conversacion.mensajes += Mensaje(user)
                        |
              modelo.responder(...)  -----------------.
                        |                              |
              ¿trae llamadas a herramientas?           |
                 si -> ejecutarlas, agregar            |
                       Mensaje(tool) por cada una,      |
                       volver a llamar a responder -----'
                 no -> devolver el contenido de texto

No hay async ni streaming aqui a proposito (`arquitectura-v2.md`, seccion 9:
"no hagas el agente asincrono todavia" -- un turno de chat es secuencial por
naturaleza). `entradas/cli/` llama a `Agente.turno` una vez por linea que
escribe la persona.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..dominio.comun.errores import ErrorDeDominio
from ..puertos.modelo_lenguaje import (
    DefinicionHerramienta,
    LlamadaHerramienta,
    Mensaje,
    ModeloDeLenguaje,
)
from .herramientas import Herramienta, validar_catalogo
from .politica import MAX_TURNOS_POR_CONVERSACION, SYSTEM_PROMPT


class LimiteDeTurnosExcedido(Exception):
    """El modelo encadeno mas de `MAX_TURNOS_POR_CONVERSACION` llamadas a
    herramientas seguidas sin llegar a una respuesta de texto."""


@dataclass
class Conversacion:
    """El historial de una charla. Vive en memoria del proceso mientras dura
    -- no hay persistencia entre reinicios en esta etapa, igual que el
    `Carrito` en `RepositorioCarritosEnMemoria`."""

    mensajes: list[Mensaje] = field(default_factory=list)


class Agente:
    def __init__(self, modelo: ModeloDeLenguaje, herramientas: list[Herramienta]) -> None:
        # Se corre al armar el agente, no en un test lejano (mismo
        # argumento que el docstring de `validar_catalogo`): si alguien le
        # agrega una herramienta prohibida, este proceso ni siquiera levanta.
        validar_catalogo(herramientas)
        self._modelo = modelo
        self._herramientas = {h.nombre: h for h in herramientas}
        self._definiciones = [
            DefinicionHerramienta(nombre=h.nombre, descripcion=h.descripcion, esquema=h.esquema)
            for h in herramientas
        ]

    def iniciar(self) -> Conversacion:
        return Conversacion(mensajes=[Mensaje(rol="system", contenido=SYSTEM_PROMPT)])

    def turno(self, conversacion: Conversacion, mensaje_usuario: str) -> str:
        """Un turno completo: agrega lo que escribio la persona, deja correr
        el loop de herramientas, y devuelve el texto final. Muta
        `conversacion.mensajes` in place -- llamar de nuevo sigue la misma
        charla."""
        conversacion.mensajes.append(Mensaje(rol="user", contenido=mensaje_usuario))

        for _ in range(MAX_TURNOS_POR_CONVERSACION):
            respuesta = self._modelo.responder(conversacion.mensajes, self._definiciones)
            conversacion.mensajes.append(
                Mensaje(rol="assistant", contenido=respuesta.contenido, llamadas=respuesta.llamadas)
            )
            if not respuesta.llamadas:
                return respuesta.contenido or ""

            for llamada in respuesta.llamadas:
                conversacion.mensajes.append(
                    Mensaje(
                        rol="tool",
                        contenido=self._ejecutar(llamada),
                        id_llamada=llamada.id,
                        nombre_herramienta=llamada.nombre,
                    )
                )

        raise LimiteDeTurnosExcedido(
            f"el agente supero {MAX_TURNOS_POR_CONVERSACION} rondas de "
            "herramientas en un mismo turno sin llegar a una respuesta"
        )

    def _ejecutar(self, llamada: LlamadaHerramienta) -> str:
        """Nunca deja que una excepcion de una herramienta tumbe el turno:
        se traduce a un mensaje de rol "tool" que el modelo puede leer y
        decidir que hacer -- pedir de nuevo con otros argumentos, o
        contarle a la persona que no se pudo. Un `ErrorDeDominio` ya trae
        `to_json()` pensado para esto (`dominio/comun/errores.py`)."""
        herramienta = self._herramientas.get(llamada.nombre)
        if herramienta is None:
            return json.dumps({"error": f"herramienta desconocida: '{llamada.nombre}'"})
        try:
            resultado = herramienta.ejecutar(**llamada.argumentos)
        except ErrorDeDominio as exc:
            return json.dumps(exc.to_json(), ensure_ascii=False)
        except TypeError as exc:
            return json.dumps(
                {"error": f"argumentos invalidos para '{llamada.nombre}': {exc}"},
                ensure_ascii=False,
            )
        return json.dumps(resultado, ensure_ascii=False, default=str)
