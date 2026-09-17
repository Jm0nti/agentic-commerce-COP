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

DECIDIR, DESPUES EJECUTAR (migracion a agentes, etapa 1)
----------------------------------------------------------
Con un `ClasificadorDeIntencion`, cada turno tiene dos pasos explicitos:

    1. decidir   clasificador -> `ClasificacionDeIntencion` -> `Ruta`
                 (`agente/nodos.py`): que nodos actuan este turno y, por lo
                 tanto, que herramientas ve el modelo.
    2. ejecutar  el mismo loop de siempre, pero anunciando SOLO las
                 herramientas de la ruta, con una instruccion corta del
                 orquestador para este turno, y rechazando al ejecutar
                 cualquier llamada a una herramienta fuera de la ruta --
                 aunque exista en el agente. Anunciar menos no alcanza: un
                 modelo puede pedir una herramienta que no se le anuncio.

La instruccion del orquestador NO se guarda en `Conversacion.mensajes`: se
agrega al mensaje de sistema de la vista que recibe el modelo, y se descarta
al terminar el turno. Si se guardara, cada turno viejo arrastraria la
instruccion de una ruta que ya no aplica. Va pegada al mensaje de sistema
inicial -- y no como un mensaje de sistema suelto a mitad del historial --
porque no todo proveedor compatible con Chat Completions acepta un "system"
en cualquier posicion, y un 400 del proveedor tumbaria el turno entero. Lo
que SI queda registrado es la decision: `Conversacion.clasificaciones`.

Sin clasificador (`AGORA_CLASIFICADOR=apagado`, o quien construya un
`Agente` sin pasarle uno) el turno es exactamente el de antes: las
herramientas completas, sin instruccion extra, sin clasificaciones.
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
from .herramientas import (
    HERRAMIENTAS_POR_NODO,
    Herramienta,
    herramientas_para_nodo,
    validar_asignacion_por_nodo,
    validar_catalogo,
)
from .intencion import ClasificacionDeIntencion, ClasificadorDeIntencion
from .nodos import Ruta, ruta_para
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
    # Una por turno, en orden, cuando el `Agente` tiene clasificador. Es el
    # registro auditable de "que decidio el orquestador" -- separado de
    # `mensajes`, que es lo que ve el modelo.
    clasificaciones: list[ClasificacionDeIntencion] = field(default_factory=list)


class Agente:
    def __init__(
        self,
        modelo: ModeloDeLenguaje,
        herramientas: list[Herramienta],
        clasificador: ClasificadorDeIntencion | None = None,
    ) -> None:
        # Se corre al armar el agente, no en un test lejano (mismo
        # argumento que el docstring de `validar_catalogo`): si alguien le
        # agrega una herramienta prohibida, este proceso ni siquiera levanta.
        validar_catalogo(herramientas)
        # Y lo mismo por nodo: la tabla de listas blancas tiene que ser
        # coherente, y cada herramienta que le llega al agente tiene que
        # pasar la validacion del nodo que es su dueño.
        validar_asignacion_por_nodo()
        for nodo in HERRAMIENTAS_POR_NODO:
            herramientas_para_nodo(herramientas, nodo)

        self._modelo = modelo
        self._clasificador = clasificador
        self._herramientas = {h.nombre: h for h in herramientas}
        self._definiciones = [
            DefinicionHerramienta(nombre=h.nombre, descripcion=h.descripcion, esquema=h.esquema)
            for h in herramientas
        ]

    def iniciar(self) -> Conversacion:
        return Conversacion(mensajes=[Mensaje(rol="system", contenido=SYSTEM_PROMPT)])

    def turno(self, conversacion: Conversacion, mensaje_usuario: str) -> str:
        """Un turno completo: agrega lo que escribio la persona, decide la
        ruta, deja correr el loop de herramientas dentro de esa ruta, y
        devuelve el texto final. Muta `conversacion` in place -- llamar de
        nuevo sigue la misma charla."""
        historial_previo = tuple(conversacion.mensajes)
        conversacion.mensajes.append(Mensaje(rol="user", contenido=mensaje_usuario))

        ruta = self._decidir(conversacion, mensaje_usuario, historial_previo)
        return self._ejecutar_turno(conversacion, ruta)

    # -- paso 1: decidir ------------------------------------------------- #

    def _decidir(
        self, conversacion: Conversacion, mensaje_usuario: str, historial: tuple[Mensaje, ...]
    ) -> Ruta:
        if self._clasificador is None:
            return ruta_para(None)
        clasificacion = self._clasificador.clasificar(mensaje_usuario, historial)
        conversacion.clasificaciones.append(clasificacion)
        return ruta_para(clasificacion)

    # -- paso 2: ejecutar ------------------------------------------------ #

    def _ejecutar_turno(self, conversacion: Conversacion, ruta: Ruta) -> str:
        habilitadas = ruta.herramientas & frozenset(self._herramientas)
        definiciones = [d for d in self._definiciones if d.nombre in habilitadas]
        instrucciones = ruta.instrucciones()

        for _ in range(MAX_TURNOS_POR_CONVERSACION):
            vista = _vista_para_el_modelo(conversacion.mensajes, instrucciones)
            respuesta = self._modelo.responder(vista, definiciones)
            conversacion.mensajes.append(
                Mensaje(rol="assistant", contenido=respuesta.contenido, llamadas=respuesta.llamadas)
            )
            if not respuesta.llamadas:
                return respuesta.contenido or ""

            for llamada in respuesta.llamadas:
                conversacion.mensajes.append(
                    Mensaje(
                        rol="tool",
                        contenido=self._ejecutar(llamada, habilitadas, ruta),
                        id_llamada=llamada.id,
                        nombre_herramienta=llamada.nombre,
                    )
                )

        raise LimiteDeTurnosExcedido(
            f"el agente supero {MAX_TURNOS_POR_CONVERSACION} rondas de "
            "herramientas en un mismo turno sin llegar a una respuesta"
        )

    def _ejecutar(
        self, llamada: LlamadaHerramienta, habilitadas: frozenset[str], ruta: Ruta
    ) -> str:
        """Nunca deja que una excepcion de una herramienta tumbe el turno:
        se traduce a un mensaje de rol "tool" que el modelo puede leer y
        decidir que hacer -- pedir de nuevo con otros argumentos, o
        contarle a la persona que no se pudo. Un `ErrorDeDominio` ya trae
        `to_json()` pensado para esto (`dominio/comun/errores.py`).

        Una herramienta que existe pero no esta en la ruta de este turno se
        rechaza ANTES de tocar su funcion: es la diferencia entre "no se la
        anunciamos al modelo" y "no la puede ejecutar"."""
        herramienta = self._herramientas.get(llamada.nombre)
        if herramienta is None:
            return json.dumps({"error": f"herramienta desconocida: '{llamada.nombre}'"})
        if llamada.nombre not in habilitadas:
            intencion = (
                ruta.clasificacion.intencion.value
                if ruta.clasificacion is not None and ruta.clasificacion.intencion is not None
                else "respaldo"
            )
            return json.dumps(
                {
                    "error": f"la herramienta '{llamada.nombre}' no esta habilitada en este "
                    f"turno (intencion: {intencion}; nodos: {', '.join(ruta.nodos)})",
                },
                ensure_ascii=False,
            )
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


def _vista_para_el_modelo(mensajes: list[Mensaje], instrucciones: str | None) -> list[Mensaje]:
    """Lo que recibe `ModeloDeLenguaje.responder`: el historial tal cual,
    con la instruccion del orquestador (si la hay) agregada al final del
    mensaje de sistema inicial. Una copia, siempre -- nunca la lista de la
    conversacion, que el loop sigue mutando."""
    if instrucciones is None:
        return list(mensajes)
    if mensajes and mensajes[0].rol == "system":
        base = mensajes[0].contenido or ""
        return [Mensaje(rol="system", contenido=f"{base}\n\n{instrucciones}"), *mensajes[1:]]
    return [Mensaje(rol="system", contenido=instrucciones), *mensajes]
