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

LOGIN (multi-usuario, 4 de septiembre de 2026)
---------------------------------------------------
Antes de esta version, `titular_id` llegaba como texto libre desde
`chat.html` (un `<input>` guardado en `localStorage`), sin ninguna
verificacion -- cualquiera podia escribir el `titular_id` de otro y ver
sus medios de pago. Ahora `POST /auth/iniciar-sesion` verifica usuario y
contrasena (`contenedor.iniciar_sesion`, `aplicacion/autenticacion.py`,
usuarios creados de antemano con `scripts/crear_usuario.py` -- no hay
registro por HTTP) y deja una cookie httponly (`entradas/api/
autenticacion.py:AlmacenDeSesionesWeb`). Toda ruta que antes aceptaba
`titular_id` por parametro (`firmar`, `confirmar_enrolamiento`,
`listar_medios`) ahora lo resuelve de esa cookie via la dependencia
`_requiere_titular` -- nunca de un campo que mande el cliente. Crear una
sesion de chat (`POST /sesiones`) tambien exige estar autenticado, y queda
atada al `titular_id` que la creo (`entradas/api/sesiones.py`).
"""

from __future__ import annotations

import json
import queue
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ...agente.conversacion import Agente, LimiteDeTurnosExcedido
from ...composicion.contenedor import Contenedor
from ...dominio.comun.errores import (
    CredencialesInvalidas,
    ErrorDeDominio,
    PasarelaNoDisponible,
    SesionInvalida,
)
from ...dominio.mandato.modelo import Intencion
from ...dominio.pago.modelo import MedioDePagoRef, Proveedor
from .autenticacion import COOKIE_SESION, DURACION_SESION, AlmacenDeSesionesWeb
from .sesiones import AlmacenDeSesiones, SesionDesconocida

RAIZ_ESTATICO = Path(__file__).resolve().parent / "estatico"


class _MensajeEntrante(BaseModel):
    texto: str


class _FirmarEntrante(BaseModel):
    sesion_id: str


class _IniciarSesionEntrante(BaseModel):
    nombre_usuario: str
    contrasena: str


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
    comercio_id: str


class _RevocarMedioEntrante(BaseModel):
    # `proveedor` viaja en el cuerpo (no en la URL) porque `id_externo` solo
    # es unico DENTRO de un proveedor. `ambiente` no viaja -- sale de
    # `contenedor.config.ambiente`, igual que en `listar_medios`: nunca de un
    # campo que mande el cliente.
    proveedor: str


def crear_app(agente: Agente | None, contenedor: Contenedor) -> FastAPI:
    """Factoria pura. `agente` puede ser `None` (falta `DEEPSEEK_API_KEY`,
    mismo criterio que `entradas/cli/__main__.py:cmd_chat`) -- el proceso
    igual levanta, pero `POST /sesiones` responde 503 en vez de arrancar
    una charla que no puede hablarle a ningun modelo."""

    sesiones = AlmacenDeSesiones(agente, contenedor) if agente is not None else None
    sesiones_web = AlmacenDeSesionesWeb(contenedor.reloj)
    app = FastAPI(title="agora -- chat con firma en una sola pestana")
    # Expuesto para pruebas (`tests/test_api_app.py`): leer la cola de
    # eventos de una sesion directo, sin pelear con como el `TestClient` de
    # turno maneja (o no) una lectura incremental de un `StreamingResponse`
    # que nunca termina -- la ruta HTTP sigue siendo el unico camino real
    # para un navegador.
    app.state.sesiones = sesiones

    def _requiere_titular(request: Request) -> str:
        """Dependencia de FastAPI: el `titular_id` detras de la cookie de
        sesion (`COOKIE_SESION`), NUNCA de un campo que mande el cliente.
        401 (no 400) si no hay cookie o si `AlmacenDeSesionesWeb` la
        rechaza -- no es un dato mal formado, es una peticion sin
        autenticar (ver `dominio/comun/errores.py:SesionInvalida`)."""
        token = request.cookies.get(COOKIE_SESION)
        if not token:
            raise HTTPException(status_code=401, detail="no hay sesion iniciada")
        try:
            titular_id, _nombre_usuario = sesiones_web.titular_de(token)
        except SesionInvalida as exc:
            raise HTTPException(status_code=401, detail=exc.mensaje) from exc
        return titular_id

    @app.get("/salud")
    def salud() -> dict[str, Any]:
        return {"ok": True, "agente_disponible": sesiones is not None}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(RAIZ_ESTATICO / "chat.html")

    # -- Autenticacion (multi-usuario, 4 de septiembre de 2026) --------------- #
    #
    # Sin registro por HTTP: los usuarios se crean de antemano con
    # `scripts/crear_usuario.py`. Estas tres rutas son las UNICAS que no
    # exigen la cookie de sesion via `_requiere_titular` -- son las que la
    # arman o la destruyen.

    @app.post("/auth/iniciar-sesion")
    def iniciar_sesion(cuerpo: _IniciarSesionEntrante, response: Response) -> dict[str, Any]:
        try:
            usuario = contenedor.iniciar_sesion(cuerpo.nombre_usuario, cuerpo.contrasena)
        except CredencialesInvalidas as exc:
            raise HTTPException(status_code=401, detail=exc.mensaje) from exc
        token = sesiones_web.crear(usuario)
        response.set_cookie(
            COOKIE_SESION, token, httponly=True, samesite="lax",
            max_age=int(DURACION_SESION.total_seconds()),
        )
        return {"titular_id": usuario.titular_id, "nombre_usuario": usuario.nombre_usuario}

    @app.post("/auth/cerrar-sesion")
    def cerrar_sesion(request: Request, response: Response) -> dict[str, Any]:
        token = request.cookies.get(COOKIE_SESION)
        if token:
            sesiones_web.cerrar(token)
        response.delete_cookie(COOKIE_SESION)
        return {"ok": True}

    @app.get("/auth/quien-soy")
    def quien_soy(request: Request) -> dict[str, Any]:
        token = request.cookies.get(COOKIE_SESION)
        if not token:
            raise HTTPException(status_code=401, detail="no hay sesion iniciada")
        try:
            titular_id, nombre_usuario = sesiones_web.titular_de(token)
        except SesionInvalida as exc:
            raise HTTPException(status_code=401, detail=exc.mensaje) from exc
        return {"titular_id": titular_id, "nombre_usuario": nombre_usuario}

    @app.post("/sesiones")
    def crear_sesion(titular_id: str = Depends(_requiere_titular)) -> dict[str, Any]:
        if sesiones is None:
            raise HTTPException(
                status_code=503,
                detail="no hay DEEPSEEK_API_KEY configurada -- sin ella no hay agente de chat",
            )
        return {"sesion_id": sesiones.crear(titular_id)}

    @app.post("/sesiones/{sesion_id}/mensajes")
    def enviar_mensaje(
        sesion_id: str, cuerpo: _MensajeEntrante, titular_id: str = Depends(_requiere_titular),
    ) -> dict[str, Any]:
        if sesiones is None:
            raise HTTPException(status_code=503, detail="no hay agente de chat disponible")
        try:
            respuesta = sesiones.enviar_mensaje(sesion_id, cuerpo.texto, titular_id)
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
    def eventos(sesion_id: str, titular_id: str = Depends(_requiere_titular)) -> StreamingResponse:
        if sesiones is None:
            raise HTTPException(status_code=503, detail="no hay agente de chat disponible")
        try:
            cola = sesiones.eventos(sesion_id, titular_id)
        except SesionDesconocida as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(_flujo_sse(cola), media_type="text/event-stream")

    @app.post("/propuestas/{propuesta_id}/firmar")
    def firmar(
        propuesta_id: str, cuerpo: _FirmarEntrante, titular_id: str = Depends(_requiere_titular),
    ) -> dict[str, Any]:
        """Mismo llamado que `entradas/cli/__main__.py:cmd_firmar`: busca
        la propuesta y el carrito por id, nunca arma un carrito nuevo. La
        diferencia es que aca la persona lo dispara apretando "Firmar" en
        el popup, no corriendo un comando en otra terminal. `titular_id`
        sale de la cookie de sesion (`_requiere_titular`), nunca del cuerpo
        de la peticion -- antes de esta version cualquiera podia mandar el
        `titular_id` que quisiera y firmar en nombre de otro."""
        try:
            mandato = contenedor.emitir_mandato(propuesta_id, titular_id)
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
    def retomar(
        intencion_id: str, cuerpo: _RetomarEntrante, _titular_id: str = Depends(_requiere_titular),
    ) -> dict[str, Any]:
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
    def iniciar_enrolamiento(
        cuerpo: _IniciarEnrolamientoEntrante, _titular_id: str = Depends(_requiere_titular),
    ) -> dict[str, Any]:
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
    def estado_enrolamiento(
        token: str, comercio_id: str, _titular_id: str = Depends(_requiere_titular),
    ) -> dict[str, Any]:
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
    def confirmar_enrolamiento(
        cuerpo: _ConfirmarEnrolamientoEntrante, titular_id: str = Depends(_requiere_titular),
    ) -> dict[str, Any]:
        """Paso 3: vuelve a consultar el estado del token ACA, en vez de
        confiar en lo que el navegador dice haber visto en su ultimo
        sondeo -- mismo argumento que `carrito_hash` en `composicion/
        agente.py:pagar`: lo que decide si algo se autoriza nunca sale de
        un dato que el cliente podria inventar. Mismo criterio con
        `titular_id`: sale de la cookie de sesion, nunca del cuerpo."""
        try:
            estado = contenedor.consultar_enrolamiento(cuerpo.token, cuerpo.comercio_id).estado
            ref = contenedor.confirmar_enrolamiento(
                cuerpo.token, cuerpo.correo, titular_id, estado, cuerpo.comercio_id
            )
        except PasarelaNoDisponible as exc:
            raise HTTPException(status_code=502, detail=exc.mensaje) from exc
        except ErrorDeDominio as exc:
            raise HTTPException(status_code=400, detail=exc.mensaje) from exc
        return ref.to_json()

    @app.get("/medios")
    def listar_medios(titular_id: str = Depends(_requiere_titular)) -> dict[str, Any]:
        """Los medios vivos del titular AUTENTICADO (cookie de sesion, ver
        `_requiere_titular`) en el ambiente que ya tiene configurado este
        proceso (`contenedor.config.ambiente`) -- mismo criterio que
        `entradas/cli/__main__.py:cmd_fuentes`, sin selector de ambiente en
        la peticion: la pasarela (simulada/wompi) y el ambiente los fija
        el .env del servidor, no el navegador. Antes de esta version
        `titular_id` viajaba como query param que cualquiera podia cambiar
        para ver los medios de otro."""
        vivos = contenedor.medios.vivos(titular_id, contenedor.config.ambiente)
        return {"medios": [ref.to_json() for ref in vivos]}

    @app.post("/medios/{id_externo}/revocar")
    def revocar_medio(
        id_externo: str,
        cuerpo: _RevocarMedioEntrante,
        titular_id: str = Depends(_requiere_titular),
    ) -> dict[str, Any]:
        """El boton de panico (`aplicacion/revocar_medio.py`) por HTTP --
        hasta ahora solo lo alcanzaba `entradas/cli/__main__.py:cmd_revocar`.
        Mismo criterio que el resto de esta seccion: `titular_id` sale de la
        cookie de sesion, nunca del cuerpo. `RevocarMedio` ya verifica que la
        referencia sea del titular autenticado (`RepositorioMedios.vivos`)
        antes de pedirle la revocacion a la pasarela -- revocar a ciegas
        podria apagar la fuente equivocada (docstring de `aplicacion/
        revocar_medio.py`)."""
        try:
            ref = MedioDePagoRef(
                proveedor=Proveedor(cuerpo.proveedor),
                ambiente=contenedor.config.ambiente,
                id_externo=id_externo,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"proveedor invalido: {cuerpo.proveedor!r}"
            ) from exc
        try:
            estado = contenedor.revocar_medio(ref, titular_id)
        except ErrorDeDominio as exc:
            raise HTTPException(status_code=400, detail=exc.mensaje) from exc
        # "aviso" viaja vacio salvo que Wompi no haya podido anular la
        # fuente por API (Nequi) y el medio se haya desactivado solo del
        # lado de esta app -- ver AdaptadorWompi.revocar_medio.
        return {"estado": estado.estado, "aviso": (estado.detalle or {}).get("aviso", "")}

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
