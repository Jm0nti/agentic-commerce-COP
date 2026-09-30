"""`AlmacenDeSesiones` (etapa 7, extendida en la etapa 9 con el registro de
pagos que quedan pendientes de la pasarela). Usa un agente falso -- sin
DeepSeek, sin `construir_herramientas` -- para poder controlar exactamente
que mensajes de rol "tool" aparecen en la conversacion, que es lo unico que
`_escanear_eventos` necesita mirar para decidir si hay que registrar algo.
"""

from __future__ import annotations

import json

from agora.agente.conversacion import Conversacion
from agora.agente.pausa import detectar_pausa
from agora.entradas.api.sesiones import AlmacenDeSesiones
from agora.puertos.modelo_lenguaje import Mensaje


class _AgenteFalso:
    """Duck-type de `Agente`: `iniciar()` arma una conversacion vacia,
    `turno()` no llama a ningun modelo -- agrega los mensajes que el test
    le indique para el proximo turno y devuelve un texto fijo."""

    def __init__(self) -> None:
        self.proximos_mensajes_tool: list[Mensaje] = []
        self.proxima_respuesta = "ok"

    def iniciar(self) -> Conversacion:
        return Conversacion(mensajes=[])

    def turno(self, conversacion: Conversacion, mensaje_usuario: str) -> str:
        conversacion.mensajes.append(Mensaje(rol="user", contenido=mensaje_usuario))
        conversacion.mensajes.extend(self.proximos_mensajes_tool)
        self.proximos_mensajes_tool = []
        conversacion.pausa = detectar_pausa(conversacion.mensajes)
        return self.proxima_respuesta

    def reanudar(self, conversacion: Conversacion, decision) -> str:
        """Etapa 5: el contrato del agente crecio -- `AlmacenDeSesiones`
        reanuda con una `DecisionHumana` tipada en vez de un string."""
        conversacion.pausa = None
        return self.turno(conversacion, decision.como_aviso())


def _mensaje_pagar(motivo: str, intencion_id: str = "int_1") -> Mensaje:
    contenido = json.dumps({
        "intencion_id": intencion_id,
        "mandato_id": "mnd_1",
        "carrito_id": "car_1",
        "ejecutado": motivo == "APPROVED",
        "motivo": motivo,
        "esperando_confirmacion": False,
    })
    return Mensaje(rol="tool", contenido=contenido, nombre_herramienta="pagar")


def test_un_pagar_que_queda_pending_se_registra_solo_como_pendiente():
    agente = _AgenteFalso()
    sesiones = AlmacenDeSesiones(agente, ver_carrito=None)
    sesion_id = sesiones.crear("tit_1")
    agente.proximos_mensajes_tool = [_mensaje_pagar("PENDING", "int_1")]

    sesiones.enviar_mensaje(sesion_id, "paga por favor")

    assert sesiones.pendientes() == {"int_1": sesion_id}


def test_un_pagar_ya_resuelto_no_se_registra():
    agente = _AgenteFalso()
    sesiones = AlmacenDeSesiones(agente, ver_carrito=None)
    sesion_id = sesiones.crear("tit_1")
    agente.proximos_mensajes_tool = [_mensaje_pagar("APPROVED", "int_2")]

    sesiones.enviar_mensaje(sesion_id, "paga por favor")

    assert sesiones.pendientes() == {}


def test_resolver_pendiente_avisa_a_la_conversacion_y_encola_un_evento_sse():
    agente = _AgenteFalso()
    sesiones = AlmacenDeSesiones(agente, ver_carrito=None)
    sesion_id = sesiones.crear("tit_1")
    sesiones.registrar_pendiente(sesion_id, "int_3")
    agente.proxima_respuesta = "genial, tu pago ya quedo aprobado"

    respuesta = sesiones.resolver_pendiente("int_3", "aprobado")

    assert respuesta == "genial, tu pago ya quedo aprobado"
    assert sesiones.pendientes() == {}
    evento = sesiones.eventos(sesion_id).get_nowait()
    assert evento == {"tipo": "mensaje_agente", "texto": "genial, tu pago ya quedo aprobado"}


def test_resolver_pendiente_de_una_intencion_no_registrada_no_hace_nada():
    agente = _AgenteFalso()
    sesiones = AlmacenDeSesiones(agente, ver_carrito=None)

    resultado = sesiones.resolver_pendiente("int_fantasma", "aprobado")

    assert resultado is None


def test_resolver_pendiente_de_una_sesion_que_ya_no_existe_no_levanta():
    # Simula un reinicio parcial: la intencion se registro pero la sesion
    # (en memoria, efimera) ya no esta.
    agente = _AgenteFalso()
    sesiones = AlmacenDeSesiones(agente, ver_carrito=None)
    sesiones.registrar_pendiente("ses_fantasma", "int_4")

    resultado = sesiones.resolver_pendiente("int_4", "aprobado")

    assert resultado is None
