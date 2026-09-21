"""La traza de un turno: como el agente llego a su respuesta.

No es logging de diagnostico -- es lo mismo que dice
`puertos/sistema.py:Bitacora`: *auditoria*. Un turno del agente es una
cadena de decisiones (clasificar -> enrutar -> habilitar herramientas ->
inyectar contexto -> llamar herramientas -> contestar), y cada eslabon es
una respuesta a "por que contesto esto". La traza es esa cadena, escrita
entera, una linea por turno.

QUE SE RECONSTRUYE, Y DE DONDE
--------------------------------
Todo sale de la `Conversacion` -- que ya venia registrando lo que hace
falta desde las etapas 1 y 2 (`clasificaciones`, `contextos`) mas el
historial de siempre (`mensajes`). Nada se anota "en paralelo" mientras el
turno corre.

Es deliberado: una contabilidad paralela puede divergir de lo que el modelo
realmente vio, y entonces la traza miente justo cuando mas importa. Leyendo
`conversacion.mensajes` la traza dice lo que paso, no lo que alguien creyo
que pasaba. Por eso "esta herramienta se rechazo por estar fuera de ruta"
se deduce del mensaje de rol "tool" que recibio el modelo, y no de una
bandera que el loop levanto al pasar.

LO QUE LA TRAZA PRUEBA
------------------------
El principio de la PoC -- *el agente propone, el humano firma, la boveda
ejecuta* -- es hoy una propiedad estructural (`test_fronteras.py`) y una
propiedad de ejecucion (una herramienta fuera de ruta se rechaza al
ejecutar). La traza la vuelve una propiedad OBSERVABLE despues del hecho:
por cada turno queda escrito que herramientas se le ofrecieron al modelo,
cuales pidio, cuales se le negaron y por que. Es lo que se le muestra a
alguien que pregunta "¿y como se yo que el agente no cobro solo?".

DATOS PERSONALES
------------------
La traza incluye lo que escribio la persona y lo que contesto el agente:
es una transcripcion, y hay que tratarla como tal. Lo que NO puede
aparecer, por construccion y no por filtro, es una credencial: el agente
no tiene ninguna (`herramientas.py:PROHIBIDAS`), asi que no hay ninguna que
pueda entrar por los argumentos de una herramienta.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from ..puertos.modelo_lenguaje import Mensaje
from .nodos import Ruta

EVENTO = "turno_del_agente"
# Los argumentos y resultados de herramientas se recortan: una busqueda de
# catalogo puede devolver decenas de productos, y una traza que nadie puede
# leer no sirve de evidencia. El recorte se marca, nunca es silencioso.
MAX_CARACTERES_POR_CAMPO = 600
MARCA_DE_RECORTE = "...[recortado]"


@dataclass(frozen=True)
class InicioDelTurno:
    """Donde estaba la conversacion antes de este turno. Se toma ANTES de
    `abrir_turno` (que agrega el mensaje de la persona), asi los tres
    indices marcan exactamente lo que el turno agrego."""

    mensajes: int
    clasificaciones: int
    contextos: int
    comenzado: float


def comenzar(conversacion: Any) -> InicioDelTurno:
    return InicioDelTurno(
        mensajes=len(conversacion.mensajes),
        clasificaciones=len(conversacion.clasificaciones),
        contextos=len(conversacion.contextos),
        comenzado=time.perf_counter(),
    )


def _recortar(texto: str) -> str:
    if len(texto) <= MAX_CARACTERES_POR_CAMPO:
        return texto
    return texto[:MAX_CARACTERES_POR_CAMPO] + MARCA_DE_RECORTE


def _resultado_de(contenido: str | None) -> dict[str, Any]:
    """Lo que el modelo recibio como resultado de una herramienta.

    `Agente._ejecutar` siempre devuelve un JSON: o el resultado real, o un
    `{"error": ...}`. Se vuelve a parsear para poder marcar el rechazo por
    ruta como lo que es -- la evidencia de que el enrutamiento funciono --
    en vez de dejarlo como un string mas."""
    crudo = contenido or ""
    salida: dict[str, Any] = {"resultado": _recortar(crudo)}
    try:
        leido = json.loads(crudo)
    except (json.JSONDecodeError, TypeError):
        return salida
    if isinstance(leido, dict) and "error" in leido:
        error = str(leido["error"])
        salida["error"] = _recortar(error)
        # La frase la arma `Agente._ejecutar`. Es la unica forma de rechazo
        # que significa "el enrutamiento hizo su trabajo", y merece un campo
        # propio: es lo que se mira en una auditoria.
        salida["fuera_de_ruta"] = "no esta habilitada" in error
    return salida


def _llamadas_del_turno(nuevos: list[Mensaje]) -> list[dict[str, Any]]:
    """Cada llamada a herramienta con su resultado, en orden, numerada por
    ronda del loop. Se emparejan por `id_llamada`."""
    resultados = {
        m.id_llamada: m for m in nuevos if m.rol == "tool" and m.id_llamada is not None
    }
    llamadas: list[dict[str, Any]] = []
    ronda = 0
    for mensaje in nuevos:
        if mensaje.rol != "assistant":
            continue
        ronda += 1
        for llamada in mensaje.llamadas or ():
            entrada: dict[str, Any] = {
                "ronda": ronda,
                "herramienta": llamada.nombre,
                "argumentos": _recortar(
                    json.dumps(llamada.argumentos, ensure_ascii=False, default=str)
                ),
            }
            respuesta = resultados.get(llamada.id)
            entrada.update(
                _resultado_de(respuesta.contenido if respuesta is not None else None)
            )
            llamadas.append(entrada)
    return llamadas


def armar_traza(
    conversacion: Any,
    inicio: InicioDelTurno,
    mensaje: str,
    respuesta: str,
    ruta: Ruta | None,
    agente: str | None = None,
    pausa: Any | None = None,
) -> dict[str, Any]:
    """El cuerpo que se le pasa a `Bitacora.anotar`. Una sola linea por
    turno, con la cadena de decisiones completa."""
    nuevos = list(conversacion.mensajes[inicio.mensajes :])
    clasificaciones = conversacion.clasificaciones[inicio.clasificaciones :]
    contextos = conversacion.contextos[inicio.contextos :]

    cuerpo: dict[str, Any] = {
        "conversacion_id": getattr(conversacion, "conversacion_id", None),
        "turno": len(conversacion.clasificaciones) or None,
        "duracion_ms": round((time.perf_counter() - inicio.comenzado) * 1000, 1),
        "mensaje": _recortar(mensaje),
        "respuesta": _recortar(respuesta),
        # Paso 1: DECIDIR. `None` sin clasificador (AGORA_CLASIFICADOR=apagado).
        "clasificacion": clasificaciones[-1].to_json() if clasificaciones else None,
        # Paso 2: ENRUTAR. Que agente atendio y con que podia contar.
        "agente": agente,
        "nodos": list(ruta.nodos) if ruta is not None else [],
        "es_respaldo": ruta.es_respaldo if ruta is not None else None,
        "herramientas_habilitadas": sorted(ruta.herramientas) if ruta is not None else [],
        # Paso 3: CONTEXTO. De que documentos salio lo que se le inyecto.
        "contexto": [
            {
                "nodo": nodo,
                "fuentes": list(contexto.fuentes),
                "caracteres": len(contexto.texto),
            }
            for nodo, contexto in contextos
        ],
        # Paso 4: EJECUTAR.
        "rondas": sum(1 for m in nuevos if m.rol == "assistant"),
        "llamadas": _llamadas_del_turno(nuevos),
        # Paso 5 (etapa 5): el turno se detuvo esperando a una persona. Es
        # el momento exacto en que el agente deja de decidir -- por eso vale
        # la pena que quede escrito, no solo que lo sepa el popup.
        "pausa": pausa.to_json() if pausa is not None else None,
    }
    return cuerpo
