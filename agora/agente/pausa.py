"""El punto donde el turno se detiene a esperar a una persona (migracion a
agentes, etapa 5).

Decision 6 de `docs/arquitectura-agentes/arquitectura-agentes-langgraph.md`:
*"Hoy 'esperando confirmacion humana' vive como una nota de texto mas un
evento SSE... Es exactamente lo que `interrupt()` de LangGraph modela: el
grafo se detiene en un punto explicito hasta que algo externo lo resuelve."*

Este modulo es ese punto explicito, en tipos del proyecto:

    PausaDelTurno    que hay que resolver (firmar una propuesta, confirmar
                     un cobro) y con que ids
    DecisionHumana   que resolvio la persona
    detectar_pausa   mira lo que devolvieron las herramientas y arma la
                     `PausaDelTurno`, o `None` si el turno no dejo nada
                     pendiente

EL AVISO SE ARMA EN UN SOLO LUGAR
-----------------------------------
Antes de esta etapa habia CUATRO sitios que escribian a mano el texto que
le avisa al modelo que la persona ya decidio: firmar, rechazar y retomar en
`entradas/api/app.py`, mas el webhook en `entradas/api/sesiones.py`. Cada
uno tenia que acordarse de meter el `mandato_id` y el `carrito_id` con el
formato correcto, porque del otro lado el modelo los lee del texto. Eso es
exactamente la "nota con el comando ya armado" que la decision 6 quiere
sacar. Ahora hay un solo `DecisionHumana.como_aviso()`, y los cuatro
llamadores pasan datos tipados.

POR QUE VIVE EN `agente/` Y NO EN `entradas/`
-----------------------------------------------
"El turno quedo esperando una firma" es un estado de la conversacion, no de
HTTP: la CLI tiene el mismo problema y hoy lo resuelve con el mismo texto.
`entradas/api/sesiones.py` sigue siendo quien traduce esto a un evento SSE
con los items del carrito para el popup -- eso si es presentacion.

LO QUE ESTE MODULO NO DECIDE
------------------------------
Nada de dinero. Arma descripciones de lo que hay que decidir y textos para
el modelo. Quien emite el mandato y quien cobra siguen siendo
`aplicacion/emitir_mandato.py` y `aplicacion/ejecutar_intencion.py`,
llamados por la persona desde `entradas/`. El agente no gana ninguna
herramienta nueva: `PROHIBIDAS` sigue negandole `firmar` y `retomar`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

from ..model.agente.gateways.modelo_lenguaje import Mensaje


class TipoDePausa(str, Enum):
    FIRMA_DE_PROPUESTA = "firma_de_propuesta"
    CONFIRMACION_DE_COBRO = "confirmacion_de_cobro"


@dataclass(frozen=True)
class PausaDelTurno:
    """Lo que una persona tiene que resolver para que el turno siga.

    Los ids son opacos y no llevan plata: identifican que firmar o que
    confirmar. El monto viaja solo para que el popup pueda mostrarlo -- la
    verdad del monto sigue siendo el `Carrito` y el `Mandato`, que
    `entradas/api/sesiones.py` vuelve a buscar por id antes de dibujar
    nada."""

    tipo: TipoDePausa
    propuesta_id: str = ""
    carrito_id: str = ""
    comercio_id: str = ""
    intencion_id: str = ""
    mandato_id: str = ""
    monto_cop: int = 0
    justificacion: str = ""
    motivo: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo.value,
            "propuesta_id": self.propuesta_id,
            "carrito_id": self.carrito_id,
            "comercio_id": self.comercio_id,
            "intencion_id": self.intencion_id,
            "mandato_id": self.mandato_id,
            "monto_cop": self.monto_cop,
            "justificacion": self.justificacion,
            "motivo": self.motivo,
        }


@dataclass(frozen=True)
class DecisionHumana:
    """Lo que la persona resolvio, ya hecho: el mandato existe (o no se
    firmo), el cobro se retomó (o se rechazo). Llega DESPUES de que
    `aplicacion/` hizo el trabajo, nunca antes -- esta clase no autoriza
    nada, solo cuenta lo que paso para que el modelo se entere."""

    tipo: TipoDePausa
    aprobada: bool
    propuesta_id: str = ""
    carrito_id: str = ""
    intencion_id: str = ""
    mandato_id: str = ""
    # El desenlace que reporto la boveda al resolver: `estado` es el motivo
    # de la pasarela ('APPROVED', 'PENDING', 'DECLINED'...) y `ejecutado`,
    # si el cobro salio. Viajan al modelo porque le ahorran una consulta --
    # pero la instruccion le sigue pidiendo confirmar con consultar_estado
    # antes de contarle el resultado a la persona: el estado real vive en el
    # dominio, no en un texto.
    estado: str = ""
    ejecutado: bool | None = None
    # `True` cuando nadie hizo click: el webhook de la pasarela resolvio la
    # intencion en otro proceso y el sondeo se entero (`entradas/api/
    # sondeo_pagos.py`). Sigue siendo una decision externa al agente.
    automatica: bool = False

    def como_aviso(self) -> str:
        """El texto que entra a la conversacion como un mensaje mas.

        EL UNICO lugar del proyecto que arma este texto. Las frases estan
        elegidas para que el modelo pueda distinguir los casos sin
        ambiguedad -- y se mantienen estables a proposito: cambiarlas es
        cambiar lo que el modelo lee, no un detalle de redaccion."""
        if self.automatica:
            return (
                f"(el webhook de la pasarela ya resolvio la intencion "
                f"{self.intencion_id} de forma asincronica -- estado='{self.estado}'. "
                "Confirma con consultar_estado antes de contarle a la persona "
                "el resultado.)"
            )
        if self.tipo is TipoDePausa.FIRMA_DE_PROPUESTA:
            if not self.aprobada:
                return (
                    f"(la persona rechazo la propuesta {self.propuesta_id} desde el "
                    "popup, sin firmarla -- no hay mandato ni pago. Pregunta si "
                    "quiere que cambies el carrito, comprar en otro comercio o "
                    "producto, o que vuelvas a armar la misma propuesta.)"
                )
            return (
                f"(la persona firmo la propuesta {self.propuesta_id} desde el popup. "
                f"El mandato quedo con mandato_id={self.mandato_id}, "
                f"carrito_id={self.carrito_id}. Continua el flujo de compra llamando a "
                "pagar() con ese mandato_id y ese carrito_id.)"
            )
        veredicto = "aprobo" if self.aprobada else "rechazo"
        return (
            f"(la persona {veredicto} desde el popup la confirmacion pendiente de "
            f"la intencion {self.intencion_id}. ejecutado={self.ejecutado}, "
            f"motivo={self.estado}. Confirma el estado con consultar_estado "
            "antes de contarle a la persona el resultado.)"
        )


def _json_o_nada(contenido: str | None) -> dict[str, Any] | None:
    try:
        leido = json.loads(contenido or "")
    except (json.JSONDecodeError, TypeError):
        return None
    return leido if isinstance(leido, dict) else None


def detectar_pausa(mensajes: Sequence[Mensaje]) -> PausaDelTurno | None:
    """La pausa que dejo este turno, o `None`.

    Se lee de lo que devolvieron las herramientas -- los mensajes de rol
    "tool" que el modelo efectivamente recibio -- y no de una bandera que
    alguien levanto al pasar: mismo criterio que `agente/traza.py`. Si el
    turno dejo mas de una cosa pendiente (no pasa hoy), gana la ultima, que
    es la que la persona tiene delante.

    Un `armar_carrito` que fallo devuelve un error de dominio en vez de una
    propuesta: no hay nada que firmar, y esto devuelve `None`."""
    encontrada: PausaDelTurno | None = None
    for mensaje in mensajes:
        if mensaje.rol != "tool" or not mensaje.contenido:
            continue
        datos = _json_o_nada(mensaje.contenido)
        if datos is None:
            continue
        if mensaje.nombre_herramienta == "armar_carrito":
            propuesta = datos.get("propuesta")
            if isinstance(propuesta, dict):
                encontrada = PausaDelTurno(
                    tipo=TipoDePausa.FIRMA_DE_PROPUESTA,
                    propuesta_id=str(propuesta.get("propuesta_id", "")),
                    carrito_id=str(datos.get("carrito_id", "")),
                    comercio_id=str(propuesta.get("comercio_id", "")),
                    monto_cop=int(propuesta.get("monto_max_cop", 0) or 0),
                    justificacion=str(propuesta.get("justificacion", "")),
                )
        elif mensaje.nombre_herramienta == "pagar":
            if datos.get("esperando_confirmacion"):
                encontrada = PausaDelTurno(
                    tipo=TipoDePausa.CONFIRMACION_DE_COBRO,
                    intencion_id=str(datos.get("intencion_id", "")),
                    mandato_id=str(datos.get("mandato_id", "")),
                    carrito_id=str(datos.get("carrito_id", "")),
                    motivo=str(datos.get("motivo", "")),
                )
    return encontrada
