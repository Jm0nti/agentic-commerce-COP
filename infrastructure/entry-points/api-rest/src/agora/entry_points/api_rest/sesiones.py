"""Sesiones de chat en memoria para `entradas/api/` (etapa 7).

Une en un solo proceso lo que hasta la etapa 6 pasaba por dos terminales
separadas: cada `_Sesion` guarda la `Conversacion` de `agente/conversacion.py`
y una cola de eventos de "atencion requerida" (`propuesta_pendiente`,
`confirmacion_pendiente`) que `entradas/api/app.py` expone por Server-Sent
Events. Detectar esos eventos es tarea de este modulo, no de `app.py`: es
quien tiene el historial de mensajes para poder mirar el resultado JSON que
`armar_carrito`/`pagar` (`composicion/agente.py`) dejaron en el ultimo
mensaje de rol "tool".

POR QUE VIVE EN `entradas/` Y NO EN `composicion/` O `agente/`
----------------------------------------------------------------
Sesiones HTTP (un id de sesion por pestana de navegador, una cola de eventos
por sesion) son un concepto de "como llega la charla por HTTP", no de "como
funciona el agente" ni de "como se arma el contenedor" -- exactamente lo que
`docs/arquitectura-v2.md` seccion 2 asigna a `entradas/`. `agente/
conversacion.py` sigue sin saber que existe HTTP, SSE, o mas de una charla a
la vez; este modulo tampoco le agrega nada, solo lo llama una vez por
sesion en lugar de una vez por proceso.

POR QUE UNA COLA POR SESION, NO UN SOLO BUS DE EVENTOS
--------------------------------------------------------
Cada pestana de navegador tiene su propia charla con el agente -- un evento
de "esta propuesta necesita firma" de la sesion A nunca deberia disparar un
popup en la sesion B. `queue.Queue` (no `asyncio.Queue`) porque Starlette
corre generadores sincronos de `StreamingResponse` en un threadpool, asi
que no hace falta -- ni conviene -- meter async/await en un agente que
`docs/arquitectura-v2.md` (seccion 9) ya decidio dejar sincrono.

QUE NO HACE ESTE MODULO
--------------------------
No firma propuestas ni resuelve confirmaciones -- eso lo sigue haciendo
`app.py`, llamando a `EmitirMandatoUseCase`/`PagarCarritoUseCase.retomar`, exactamente como `entradas/cli/__main__.py:
cmd_firmar`/`cmd_retomar`. Este modulo solo le avisa despues a la
conversacion correspondiente (`reanudar`) para que el agente se entere y
conteste -- la persona sigue siendo quien decide firmar o confirmar, nunca
el agente ni este modulo.

LA PAUSA, TIPADA (migracion a agentes, etapa 5)
-------------------------------------------------
Hasta la etapa 4, este modulo deducia "hay algo pendiente" volviendo a
parsear el JSON que `armar_carrito`/`pagar` habian dejado en un mensaje de
rol "tool" -- sabia de memoria la forma de esos resultados. Ahora el turno
se detiene en un nodo explicito del grafo (`agente/grafo.py:espera_humana`)
y deja una `PausaDelTurno` tipada en la conversacion; aca solo se la
enriquece con los items del carrito para el popup, que si es presentacion.
Y la vuelta -- avisarle al modelo que la persona ya decidio -- va por
`reanudar(sesion_id, DecisionHumana)`, con el texto armado en un solo lugar
(`agente/pausa.py`) en vez de en cuatro.

DUEÑO DE LA SESION (multi-usuario, 4 de septiembre de 2026)
------------------------------------------------------------------
Antes de esta version, una sesion de chat no tenia ningun concepto de
dueño -- cualquiera que adivinara un `sesion_id` (un UUID, en la practica
imposible de adivinar, pero igual sin verificacion) podia mandarle
mensajes. Ahora `crear()` recibe el `titular_id` autenticado (`entradas/
api/app.py`, resuelto de la cookie de sesion web, nunca de un campo que
mande el cliente) y lo guarda en la `_Sesion`; `enviar_mensaje`/`eventos`
aceptan un `titular_id` opcional para verificarlo, y tratan un titular
distinto exactamente igual que un `sesion_id` que no existe
(`SesionDesconocida`) -- no hay una distincion "no es tuya" separada de
"no existe": la primera se distingue de la segunda solo por quien mira, y
no vale la pena revelarle a quien no es dueño cual de las dos paso.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from queue import Queue
from typing import Any, Callable

from ...usecase.agente.conversacion import Agente, Conversacion
from ...usecase.agente.pausa import DecisionHumana, PausaDelTurno, TipoDePausa
from ...model.catalogo.modelo import Carrito


class SesionDesconocida(Exception):
    """No existe ninguna sesion con ese id -- el proceso se reinicio, o
    nunca existio. `Conversacion` es en memoria (ver su propio docstring),
    asi que esto es esperable despues de reiniciar `scripts/servir_api.py`
    -- el frontend reacciona pidiendo una sesion nueva."""


@dataclass
class _Sesion:
    conversacion: Conversacion
    sesion_id: str = ""
    # Multi-usuario: quien es dueño de esta sesion -- ver el docstring del
    # modulo. Vacio solo es posible si algo construye una `_Sesion` sin
    # pasar por `AlmacenDeSesiones.crear` (no pasa en este codigo).
    titular_id: str = ""
    eventos: Queue = field(default_factory=Queue)
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Cuanto de `conversacion.mensajes` ya se reviso en busca de eventos --
    # sin esto, mandar un segundo mensaje de chat volveria a encolar el
    # mismo `propuesta_pendiente` del turno anterior.
    escaneado_hasta: int = 0


class AlmacenDeSesiones:
    """Una `Conversacion` por sesion de chat, en memoria del proceso --
    igual que `Conversacion` misma: no sobrevive un reinicio, y esta bien
    que no lo haga, un chat es efimero. Lo que SI tiene que sobrevivir
    entre procesos (propuestas, mandatos, estados) ya vive en sqlite desde
    la etapa 6; esto solo une esas piezas en una sola pestana."""

    def __init__(self, agente: Agente, ver_carrito: Callable[[str], Carrito]) -> None:
        """`ver_carrito` es `NavegarCatalogoUseCase.ver_carrito`: los items del
        popup de firma salen de un caso de uso, nunca de un repositorio."""
        self._agente = agente
        self._ver_carrito = ver_carrito
        self._sesiones: dict[str, _Sesion] = {}
        self._lock = threading.Lock()
        # Etapa 9: que intencion_id le pertenece a que sesion, mientras la
        # pasarela todavia no dio un desenlace final. Vive aca (no adentro
        # de cada `_Sesion`) porque `SondeoDePagosPendientes` necesita
        # poder recorrer TODAS las pendientes de TODAS las sesiones en cada
        # pasada, sin conocer sus ids de antemano -- ver
        # `entradas/api/sondeo_pagos.py`.
        self._pendientes: dict[str, str] = {}

    def crear(self, titular_id: str) -> str:
        sesion_id = uuid.uuid4().hex
        sesion = _Sesion(
            conversacion=self._agente.iniciar(), sesion_id=sesion_id, titular_id=titular_id,
        )
        with self._lock:
            self._sesiones[sesion_id] = sesion
        return sesion_id

    def enviar_mensaje(self, sesion_id: str, texto: str, titular_id: str | None = None) -> str:
        """Un turno completo de charla: agrega lo que escribio la persona,
        deja correr `Agente.turno`, y antes de devolver el texto final
        escanea los mensajes nuevos en busca de eventos de atencion
        requerida para encolarlos.

        `titular_id`, si se pasa, tiene que coincidir con el dueño de la
        sesion (ver el docstring del modulo) -- `None` (el default) se usa
        solo para las llamadas internas de este modulo (`continuar`), que
        ya confian en el `sesion_id` que ellas mismas manejan."""
        sesion = self._obtener(sesion_id, titular_id)
        with sesion.lock:
            respuesta = self._agente.turno(sesion.conversacion, texto)
            self._escanear_eventos(sesion)
            return respuesta

    def pausa_de(self, sesion_id: str, titular_id: str | None = None) -> PausaDelTurno | None:
        """Que quedo esperando a una persona en esta sesion, o `None`
        (etapa 5). Es lo mismo que disparo el popup por SSE, disponible
        tambien para quien pregunte directo."""
        return self._obtener(sesion_id, titular_id).conversacion.pausa

    def reanudar(self, sesion_id: str, decision: DecisionHumana) -> str:
        """La persona resolvio la pausa: el turno sigue (etapa 5).

        Reemplaza a los cuatro `continuar(sesion_id, <string armado a
        mano>)` que habia en `app.py` y aca. El texto que lee el modelo lo
        arma ahora `DecisionHumana.como_aviso()`, en un solo lugar."""
        sesion = self._obtener(sesion_id)
        with sesion.lock:
            respuesta = self._agente.reanudar(sesion.conversacion, decision)
            self._escanear_eventos(sesion)
            return respuesta

    def eventos(self, sesion_id: str, titular_id: str | None = None) -> Queue:
        return self._obtener(sesion_id, titular_id).eventos

    def registrar_pendiente(self, sesion_id: str, intencion_id: str) -> None:
        """`pagar()` (o `/intenciones/{id}/retomar` en `entradas/api/
        app.py`) devolvio 'PENDING' -- todavia no es un desenlace final, lo
        va a resolver el webhook de la pasarela desde OTRO proceso
        (`entradas/webhooks/wompi.py`), que no tiene forma de tocar la
        memoria de este. `SondeoDePagosPendientes` es quien vuelve a
        preguntar por esto a intervalos."""
        with self._lock:
            self._pendientes[intencion_id] = sesion_id

    def pendientes(self) -> dict[str, str]:
        """Copia -- quien sondea no deberia poder mutar el registro por
        afuera de `registrar_pendiente`/`resolver_pendiente`."""
        with self._lock:
            return dict(self._pendientes)

    def resolver_pendiente(self, intencion_id: str, estado: str) -> str | None:
        """La pasarela ya dio un desenlace final para `intencion_id` --
        `SondeoDePagosPendientes` lo supo volviendole a preguntar a
        `consultar_estado`. Le avisa a la conversacion dueña exactamente
        igual que `_continuar_si_hay_sesion` (`entradas/api/app.py`)
        despues de firmar/retomar desde un popup -- mismo mecanismo, solo
        que esta vez nadie hizo click: fue el webhook, en otro proceso, el
        que se entero primero. Ademas encola un evento SSE nuevo
        (`mensaje_agente`) para que el navegador lo muestre sin que la
        persona tenga que volver a preguntar. Devuelve la respuesta del
        agente, o `None` si la sesion ya no existe (la pestana se cerro, o
        el proceso se reinicio)."""
        with self._lock:
            sesion_id = self._pendientes.pop(intencion_id, None)
        if sesion_id is None:
            return None
        # Etapa 5: la cuarta decision externa, tipada como las otras tres --
        # con la diferencia de que aca nadie hizo click (`automatica`).
        decision = DecisionHumana(
            tipo=TipoDePausa.CONFIRMACION_DE_COBRO,
            aprobada=estado == "aprobado",
            intencion_id=intencion_id,
            estado=estado,
            automatica=True,
        )
        try:
            respuesta = self.reanudar(sesion_id, decision)
        except SesionDesconocida:
            return None
        self._obtener(sesion_id).eventos.put({"tipo": "mensaje_agente", "texto": respuesta})
        return respuesta

    def _obtener(self, sesion_id: str, titular_id: str | None = None) -> _Sesion:
        with self._lock:
            sesion = self._sesiones.get(sesion_id)
        if sesion is None:
            raise SesionDesconocida(f"no existe la sesion '{sesion_id}'")
        if titular_id is not None and sesion.titular_id != titular_id:
            # Mismo error que "no existe" -- ver el docstring del modulo
            # sobre por que no distinguir las dos situaciones.
            raise SesionDesconocida(f"no existe la sesion '{sesion_id}'")
        return sesion

    def _escanear_eventos(self, sesion: _Sesion) -> None:
        """Etapa 5: el evento de "atencion requerida" sale de la pausa
        TIPADA que dejo el turno (`agente/pausa.py`), no de volver a
        parsear el JSON que devolvieron las herramientas. Este modulo ya no
        sabe que forma tiene el resultado de `armar_carrito`: solo lo
        enriquece con los items del carrito, que es presentacion y si es su
        trabajo.

        Lo que sigue recorriendo mensajes es otra cosa: un `pagar` que fue
        directo a cobro y volvio 'PENDING' NO es una pausa (nadie tiene que
        decidir nada), es un pago que la pasarela va a liquidar sola --
        tiene su propio mecanismo, el sondeo."""
        mensajes = sesion.conversacion.mensajes
        for i in range(sesion.escaneado_hasta, len(mensajes)):
            m = mensajes[i]
            if m.rol == "tool" and m.contenido and m.nombre_herramienta == "pagar":
                self._registrar_si_pendiente_de_pasarela(sesion, m.contenido)
        sesion.escaneado_hasta = len(mensajes)

        pausa = sesion.conversacion.pausa
        if pausa is None:
            return
        evento = (
            self._evento_propuesta_pendiente(pausa)
            if pausa.tipo is TipoDePausa.FIRMA_DE_PROPUESTA
            else self._evento_confirmacion_pendiente(pausa)
        )
        if evento is not None:
            sesion.eventos.put(evento)

    def _evento_propuesta_pendiente(self, pausa: PausaDelTurno) -> dict[str, Any] | None:
        carrito = self._ver_carrito(pausa.carrito_id)
        return {
            "tipo": "propuesta_pendiente",
            "propuesta_id": pausa.propuesta_id,
            "carrito_id": pausa.carrito_id,
            "comercio_id": pausa.comercio_id,
            "monto_max_cop": pausa.monto_cop,
            "justificacion": pausa.justificacion,
            "items": [
                {
                    "nombre": i.nombre,
                    "cantidad": i.cantidad,
                    "subtotal_cop": i.subtotal.pesos,
                }
                for i in carrito.items
            ],
        }

    def _registrar_si_pendiente_de_pasarela(self, sesion: _Sesion, contenido_json: str) -> None:
        """`pagar()` fue directo a cobro (nunca paso por `esperando_
        confirmacion_humana`, que tiene su propio evento) y la pasarela
        contesto 'PENDING' -- el caso tipico de Wompi real contra Nequi,
        que liquida de forma asincronica. Sin esto, solo el camino que pasa
        por `/intenciones/{id}/retomar` (`entradas/api/app.py`) quedaria
        bajo sondeo."""
        datos = json.loads(contenido_json)
        if datos.get("motivo") == "PENDING":
            self.registrar_pendiente(sesion.sesion_id, datos["intencion_id"])

    def _evento_confirmacion_pendiente(self, pausa: PausaDelTurno) -> dict[str, Any] | None:
        return {
            "tipo": "confirmacion_pendiente",
            "intencion_id": pausa.intencion_id,
            "mandato_id": pausa.mandato_id,
            "carrito_id": pausa.carrito_id,
            "motivo": pausa.motivo,
        }
