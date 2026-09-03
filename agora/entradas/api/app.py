"""API HTTP + frontend estatico de una sola pagina (etapa 7): une en un
solo proceso lo que las etapas 5 y 6 resolvian con dos terminales -- la
persona charla con el agente y firma la propuesta / confirma el cobro
mediante una ventana emergente, sin salir de la misma pestana.

Misma convencion que `entradas/webhooks/wompi.py`: `crear_app` es una
factoria pura (nada de `os.environ`, nada de construir el `Contenedor`) --
eso es trabajo del composition root, `scripts/servir_api.py`. Lo que prueba
`tests/test_api_app.py` con `TestClient` nunca necesita una variable de
entorno.

QUE HACE QUE FIRMAR/CONFIRMAR SIGA SIENDO DECISION HUMANA
--------------------------------------------------------------
`agente/herramientas.py:PROHIBIDAS` le niega `firmar`/`retomar` al agente a
nivel de catalogo de herramientas -- eso no cambia aca. Las rutas `POST
/propuestas/{id}/firmar` y `POST /intenciones/{id}/retomar` no las llama el
agente: las llama el navegador, cuando la PERSONA aprieta un boton en el
popup. El agente nunca tiene una herramienta que las alcance; la persona
las alcanza por HTTP en lugar de por otra terminal -- el mismo cambio
estructural que se le explico al usuario antes de este commit, ahora
implementado.

SSE SOLO DISPARA EL POPUP, NUNCA LO RESUELVE
-------------------------------------------------
`GET /sesiones/{id}/eventos` empuja `propuesta_pendiente`/
`confirmacion_pendiente` para que el frontend sepa CUANDO mostrar un modal.
La resolucion (firmar, confirmar, rechazar) viaja por la respuesta HTTP
directa de `/firmar` o `/retomar` -- incluyendo el texto que el agente
contesta al enterarse, en `respuesta_agente` -- para que el modal se cierre
con una respuesta en la mano, sin depender de que llegue algo mas por el
stream.

ENROLAR UN MEDIO DE PAGO, AL MARGEN DE CUALQUIER CHAT
------------------------------------------------------------
`POST /medios/enrolar/iniciar`, `GET /medios/enrolar/{token}/estado`,
`POST /medios/enrolar/confirmar` y `GET /medios` no dependen de una sesion
de chat ni de un agente -- son actos del titular, igual que
`entradas/cli/enrolar`/`fuentes`. Van en tres pasos (en vez de una sola
ruta bloqueante) porque el enrolamiento contra Wompi real puede tardar
hasta 5 minutos mientras el titular acepta el push de Nequi
(`aplicacion/enrolar_medio.py:ESPERA_PUSH_SEG`): ninguna peticion HTTP se
queda esperando eso, el navegador sondea `estado` a su propio ritmo hasta
ver un estado final y recien entonces llama a `confirmar`.
"""

from __future__ import annotations

import json
import queue
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ...agente.conversacion import Agente, LimiteDeTurnosExcedido
from ...composicion.contenedor import Contenedor
from ...dominio.comun.errores import ErrorDeDominio, PasarelaNoDisponible
from ...dominio.mandato.modelo import Intencion
from .sesiones import AlmacenDeSesiones, SesionDesconocida

RAIZ_ESTATICO = Path(__file__).resolve().parent / "estatico"


class _MensajeEntrante(BaseModel):
    texto: str


class _FirmarEntrante(BaseModel):
    titular_id: str
    sesion_id: str


class _RetomarEntrante(BaseModel):
    mandato_id: str
    carrito_id: str
    aprueba: bool
    sesion_id: str


class _IniciarEnrolamientoEntrante(BaseModel):
    telefono: str
    correo: str
    # Multi-comercio: enrolar vincula el medio con ESTE comercio (ver el
    # docstring de aplicacion/enrolar_medio.py) -- el navegador lo manda
    # porque es quien sabe en que comercio esta el titular comprando.
    comercio_id: str


class _ConfirmarEnrolamientoEntrante(BaseModel):
    token: str
    correo: str
    titular_id: str
    comercio_id: str


def crear_app(agente: Agente | None, contenedor: Contenedor) -> FastAPI:
    """Factoria pura. `agente` puede ser `None` (falta `DEEPSEEK_API_KEY`,
    mismo criterio que `entradas/cli/__main__.py:cmd_chat`) -- el proceso
    igual levanta, pero `POST /sesiones` responde 503 en vez de arrancar
    una charla que no puede hablarle a ningun modelo."""

    sesiones = AlmacenDeSesiones(agente, contenedor) if agente is not None else None
    app = FastAPI(title="agora -- chat con firma en una sola pestana")
    # Expuesto para pruebas (`tests/test_api_app.py`): leer la cola de
    # eventos de una sesion directo, sin pelear con como el `TestClient` de
    # turno maneja (o no) una lectura incremental de un `StreamingResponse`
    # que nunca termina -- la ruta HTTP sigue siendo el unico camino real
    # para un navegador.
    app.state.sesiones = sesiones

    @app.get("/salud")
    def salud() -> dict[str, Any]:
        return {"ok": True, "agente_disponible": sesiones is not None}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(RAIZ_ESTATICO / "chat.html")

    @app.post("/sesiones")
    def crear_sesion() -> dict[str, Any]:
        if sesiones is None:
            raise HTTPException(
                status_code=503,
                detail="no hay DEEPSEEK_API_KEY configurada -- sin ella no hay agente de chat",
            )
        return {"sesion_id": sesiones.crear()}

    @app.post("/sesiones/{sesion_id}/mensajes")
    def enviar_mensaje(sesion_id: str, cuerpo: _MensajeEntrante) -> dict[str, Any]:
        if sesiones is None:
            raise HTTPException(status_code=503, detail="no hay agente de chat disponible")
        try:
            respuesta = sesiones.enviar_mensaje(sesion_id, cuerpo.texto)
        except SesionDesconocida as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ErrorDeDominio as exc:
            # `ModeloNoDisponible`/`RespuestaModeloInvalida`
            # (`puertos/modelo_lenguaje.py`): el problema es DeepSeek, no lo
            # que mando la persona -- 502, no 400.
            raise HTTPException(status_code=502, detail=exc.mensaje) from exc
        except LimiteDeTurnosExcedido as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"respuesta": respuesta}

    @app.get("/sesiones/{sesion_id}/eventos")
    def eventos(sesion_id: str) -> StreamingResponse:
        if sesiones is None:
            raise HTTPException(status_code=503, detail="no hay agente de chat disponible")
        try:
            cola = sesiones.eventos(sesion_id)
        except SesionDesconocida as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(_flujo_sse(cola), media_type="text/event-stream")

    @app.post("/propuestas/{propuesta_id}/firmar")
    def firmar(propuesta_id: str, cuerpo: _FirmarEntrante) -> dict[str, Any]:
        """Mismo llamado que `entradas/cli/__main__.py:cmd_firmar`: busca
        la propuesta y el carrito por id, nunca arma un carrito nuevo. La
        diferencia es que aca la persona lo dispara apretando "Firmar" en
        el popup, no corriendo un comando en otra terminal."""
        try:
            mandato = contenedor.emitir_mandato(propuesta_id, cuerpo.titular_id)
            carrito_id = contenedor.propuestas.obtener(propuesta_id).carrito_id
        except ErrorDeDominio as exc:
            raise HTTPException(status_code=400, detail=exc.mensaje) from exc

        aviso = (
            f"(la persona firmo la propuesta {propuesta_id} desde el popup. "
            f"El mandato quedo con mandato_id={mandato.mandato_id}, "
            f"carrito_id={carrito_id}. Continua el flujo de compra llamando a "
            "pagar() con ese mandato_id y ese carrito_id.)"
        )
        respuesta_agente = _continuar_si_hay_sesion(sesiones, cuerpo.sesion_id, aviso)
        return {
            "mandato_id": mandato.mandato_id,
            "carrito_id": carrito_id,
            "titular_id": mandato.titular_id,
            "monto_max_cop": mandato.monto_max.pesos,
            "expira": mandato.expira_en.isoformat(timespec="seconds"),
            "respuesta_agente": respuesta_agente,
        }

    @app.post("/intenciones/{intencion_id}/retomar")
    def retomar(intencion_id: str, cuerpo: _RetomarEntrante) -> dict[str, Any]:
        """Mismo llamado que `entradas/cli/__main__.py:cmd_retomar`: pide
        de nuevo `mandato_id`/`carrito_id` porque `EjecutarIntencion.
        retomar` vuelve a evaluar la politica completa contra el mismo
        `Intencion` -- no alcanza con el `intencion_id` solo (ver el
        docstring de `retomar` en `aplicacion/ejecutar_intencion.py`)."""
        try:
            carrito = contenedor.carritos.obtener(cuerpo.carrito_id)
        except ErrorDeDominio as exc:
            raise HTTPException(status_code=400, detail=exc.mensaje) from exc

        intencion = Intencion(
            intencion_id=intencion_id,
            mandato_id=cuerpo.mandato_id,
            comercio_id=carrito.comercio_id,
            carrito_id=cuerpo.carrito_id,
            monto=carrito.total,
        )
        try:
            recibo = contenedor.ejecutar_intencion.retomar(
                intencion, aprueba=cuerpo.aprueba, carrito_hash=carrito.hash_canonico,
            )
        except ErrorDeDominio as exc:
            raise HTTPException(status_code=400, detail=exc.mensaje) from exc

        # Etapa 9: si el cobro real quedo en PENDING (tipico de Wompi contra
        # Nequi, que liquida de forma asincronica), esta sesion se registra
        # para que `SondeoDePagosPendientes` la resuelva sola en cuanto el
        # webhook de la pasarela (otro proceso) le de un desenlace final --
        # ver `entradas/api/sondeo_pagos.py`.
        if recibo.motivo == "PENDING" and sesiones is not None and cuerpo.sesion_id:
            sesiones.registrar_pendiente(cuerpo.sesion_id, intencion_id)

        decision = "aprobo" if cuerpo.aprueba else "rechazo"
        aviso = (
            f"(la persona {decision} desde el popup la confirmacion pendiente de "
            f"la intencion {intencion_id}. ejecutado={recibo.ejecutado}, "
            f"motivo={recibo.motivo}. Confirma el estado con consultar_estado "
            "antes de contarle a la persona el resultado.)"
        )
        respuesta_agente = _continuar_si_hay_sesion(sesiones, cuerpo.sesion_id, aviso)
        return {
            "ejecutado": recibo.ejecutado,
            "motivo": recibo.motivo,
            "respuesta_agente": respuesta_agente,
        }

    # -- Fase A por HTTP: enrolar un medio de pago y verlos ------------------ #
    #
    # Mismo principio que el resto de esta app: enrolar es un acto del
    # titular, nunca del agente (`agente/herramientas.py:PROHIBIDAS` ya le
    # niega "enrolar" y "revocar"). Estas cuatro rutas viven al margen de
    # cualquier sesion de chat -- no hace falta estar charlando con el
    # agente para autorizar o consultar un medio de pago propio.
    #
    # El enrolamiento contra Wompi real puede tardar hasta 5 minutos
    # (`aplicacion/enrolar_medio.py:ESPERA_PUSH_SEG`) mientras el titular
    # acepta el push en la app Nequi -- por eso son DOS peticiones
    # (iniciar, despues confirmar) con una tercera de sondeo en el medio
    # (estado), en vez de una sola que se quede esperando: ninguna de las
    # tres bloquea mas de lo que tarda una llamada a la pasarela, igual que
    # ya exige `puertos/pasarela.py`. El frontend es quien decide el ritmo
    # del sondeo (`GET /medios/enrolar/{token}/estado`, repetido cada pocos
    # segundos) hasta ver un estado final.

    @app.post("/medios/enrolar/iniciar")
    def iniciar_enrolamiento(cuerpo: _IniciarEnrolamientoEntrante) -> dict[str, Any]:
        """Paso 1: crea el token y dispara el push (Wompi real) o lo
        aprueba de inmediato (la simulada). El mismo paso que usa
        `EnrolarMedio` para la CLI -- aca no se queda bloqueado sondeando,
        eso es tarea de quien llame a `estado_enrolamiento` despues."""
        try:
            proceso = contenedor.iniciar_enrolamiento(cuerpo.telefono, cuerpo.correo, cuerpo.comercio_id)
        except PasarelaNoDisponible as exc:
            raise HTTPException(status_code=502, detail=exc.mensaje) from exc
        except ErrorDeDominio as exc:
            raise HTTPException(status_code=400, detail=exc.mensaje) from exc
        return {"token": proceso.token, "estado": proceso.estado}

    @app.get("/medios/enrolar/{token}/estado")
    def estado_enrolamiento(token: str, comercio_id: str) -> dict[str, Any]:
        """Paso 2, repetido por el navegador a su propio ritmo -- nunca
        bloquea esperando un estado final, igual que el resto del puerto
        de pasarela. `comercio_id` tiene que ser el mismo que se uso en
        "iniciar" para este token (ver el docstring de aplicacion/
        enrolar_medio.py:ConsultarEnrolamiento)."""
        try:
            estado = contenedor.consultar_enrolamiento(token, comercio_id)
        except PasarelaNoDisponible as exc:
            raise HTTPException(status_code=502, detail=exc.mensaje) from exc
        except ErrorDeDominio as exc:
            raise HTTPException(status_code=400, detail=exc.mensaje) from exc
        return {"estado": estado.estado}

    @app.post("/medios/enrolar/confirmar")
    def confirmar_enrolamiento(cuerpo: _ConfirmarEnrolamientoEntrante) -> dict[str, Any]:
        """Paso 3: vuelve a consultar el estado del token ACA, en vez de
        confiar en lo que el navegador dice haber visto en su ultimo
        sondeo -- mismo argumento que `carrito_hash` en `composicion/
        agente.py:pagar`: lo que decide si algo se autoriza nunca sale de
        un dato que el cliente podria inventar."""
        try:
            estado = contenedor.consultar_enrolamiento(cuerpo.token, cuerpo.comercio_id).estado
            ref = contenedor.confirmar_enrolamiento(
                cuerpo.token, cuerpo.correo, cuerpo.titular_id, estado, cuerpo.comercio_id
            )
        except PasarelaNoDisponible as exc:
            raise HTTPException(status_code=502, detail=exc.mensaje) from exc
        except ErrorDeDominio as exc:
            raise HTTPException(status_code=400, detail=exc.mensaje) from exc
        return ref.to_json()

    @app.get("/medios")
    def listar_medios(titular_id: str) -> dict[str, Any]:
        """Los medios vivos de un titular en el ambiente que ya tiene
        configurado este proceso (`contenedor.config.ambiente`) -- mismo
        criterio que `entradas/cli/__main__.py:cmd_fuentes`, sin selector
        de ambiente en la peticion: la pasarela (simulada/wompi) y el
        ambiente los fija el .env del servidor, no el navegador."""
        vivos = contenedor.medios.vivos(titular_id, contenedor.config.ambiente)
        return {"medios": [ref.to_json() for ref in vivos]}

    return app


def _continuar_si_hay_sesion(
    sesiones: AlmacenDeSesiones | None, sesion_id: str, aviso: str
) -> str | None:
    """`firmar`/`retomar` pueden invocarse con un `sesion_id` que ya no
    existe (el proceso se reinicio entre que se mostro el popup y que la
    persona lo resolvio) -- eso no es motivo para que la accion misma
    falle: el mandato ya se firmo o el cobro ya se resolvio de verdad.
    Sin sesion para avisarle, el frontend simplemente no recibe un texto
    del agente y muestra el resultado crudo."""
    if sesiones is None:
        return None
    try:
        return sesiones.continuar(sesion_id, aviso)
    except SesionDesconocida:
        return None
    except (ErrorDeDominio, LimiteDeTurnosExcedido):
        # El mandato ya se firmo / el cobro ya se resolvio -- eso no se
        # deshace porque el agente no pudo contestar. El frontend se queda
        # sin `respuesta_agente`, pero el resultado real ya viajo en el
        # resto del cuerpo de la respuesta.
        return None


def _flujo_sse(cola: "queue.Queue[dict[str, Any]]"):
    """Generador sincrono -- Starlette lo corre en un threadpool, no hace
    falta async/await (ver el docstring del modulo). El `keepalive`
    periodico es lo unico que evita que un proxy o el propio navegador
    corte una conexion que puede quedar minutos sin un evento real."""
    while True:
        try:
            evento = cola.get(timeout=15)
        except queue.Empty:
            yield ": keepalive\n\n"
            continue
        yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
