"""`entradas/api/app.py` de punta a punta (etapa 7): el chat, el popup de
firma y el popup de confirmacion, los tres a traves de HTTP con
`TestClient` -- sin tocar DeepSeek ni la red.

El grupo grande (`test_flujo_completo_...`) es el que de verdad importa:
prueba que TODO el camino que antes exigia dos terminales (`chat` +
`firmar`/`retomar` de `entradas/cli/`, etapa 6) ahora se resuelve con una
sola sesion HTTP -- mensaje de chat, evento SSE de "hay que firmar", POST a
`/firmar`, evento SSE de "hay que confirmar", POST a `/retomar`, y en cada
paso el agente se entera y contesta en `respuesta_agente` sin que la
persona tenga que volver a escribirle nada.

`_ModeloProgramable` es mas flexible que `_ModeloGuionado` (`tests/
test_agente_conversacion.py`): en vez de una lista fija de respuestas, mira
el ULTIMO mensaje del historial y decide que hacer -- hace falta aca porque
`mandato_id`/`carrito_id` no existen todavia cuando el test arranca (se
generan recien cuando `/firmar` corre, en medio de la conversacion), asi
que no hay forma de dejarlos precargados en una lista fija como hace
`_ModeloGuionado`.

MULTI-COMERCIO: las rutas de enrolamiento (`/medios/enrolar/...`) ahora
exigen `comercio_id` -- ver el docstring de `aplicacion/enrolar_medio.py`.
Las pruebas de esas rutas usan un `comercio_id` fijo ("com_1"): con la
pasarela simulada (la que usa `_config`) cualquier comercio_id resuelve a
la misma pasarela (`RegistroDePasarelas({}, por_defecto=...)`), asi que no
hace falta que exista de verdad en el catalogo.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace

from fastapi.testclient import TestClient

from agora.composicion.agente import construir_agente
from agora.composicion.configuracion import leer_configuracion
from agora.composicion.contenedor import construir
from agora.dominio.catalogo.modelo import Disponibilidad
from agora.entradas.api.app import crear_app
from agora.entradas.api.sondeo_pagos import SondeoDePagosPendientes
from agora.puertos.modelo_lenguaje import LlamadaHerramienta, RespuestaModelo


class _ModeloProgramable:
    def __init__(self, comercio_id: str, producto_id: str) -> None:
        self._comercio_id = comercio_id
        self._producto_id = producto_id
        self.llamadas: list[tuple[list, list]] = []

    def generar(self, sistema: str, instruccion: str) -> str:
        raise AssertionError("no deberia usarse en el loop de conversacion")

    def responder(self, mensajes, herramientas):
        self.llamadas.append((list(mensajes), list(herramientas)))
        ultimo = mensajes[-1]
        contenido = ultimo.contenido or ""

        if ultimo.rol == "tool" and ultimo.nombre_herramienta == "armar_carrito":
            return RespuestaModelo(contenido="Arme la propuesta -- confirmala firmando en el popup.")
        if ultimo.rol == "tool" and ultimo.nombre_herramienta == "pagar":
            return RespuestaModelo(contenido="Quedo esperando tu confirmacion.")

        if ultimo.rol == "user" and "mandato_id=" in contenido:
            m = re.search(r"mandato_id=([^,]+), carrito_id=([^.]+)\.", contenido)
            assert m, f"no pude leer mandato_id/carrito_id de: {contenido!r}"
            return RespuestaModelo(
                contenido=None,
                llamadas=(
                    LlamadaHerramienta(
                        id="call_pagar", nombre="pagar",
                        argumentos={"mandato_id": m.group(1), "carrito_id": m.group(2)},
                    ),
                ),
            )
        if ultimo.rol == "user" and "rechazo la propuesta" in contenido:
            # Frase unica del aviso de `/propuestas/{id}/rechazar` -- se
            # chequea ANTES que "aprobo"/"rechazo" (mas abajo, para el
            # aviso de `/retomar`) porque esta tambien contiene "rechazo".
            return RespuestaModelo(
                contenido="Entendido, no se firmo nada. Decime si queres otra propuesta."
            )
        if ultimo.rol == "user" and ("aprobo" in contenido or "rechazo" in contenido):
            return RespuestaModelo(contenido="Listo, gracias por confirmar.")
        if ultimo.rol == "user" and "webhook" in contenido:
            # Etapa 9: el aviso que `AlmacenDeSesiones.resolver_pendiente`
            # le manda a la conversacion cuando el sondeo de fondo detecta
            # que el webhook de la pasarela (en otro proceso) ya resolvio
            # un pago que habia quedado PENDING.
            return RespuestaModelo(contenido="Genial, tu pago ya quedo aprobado del lado del banco.")

        # Primer mensaje de la persona: no hay nada de contexto todavia mas
        # que armar el carrito con lo que el test ya sabe que existe en el
        # catalogo.
        return RespuestaModelo(
            contenido=None,
            llamadas=(
                LlamadaHerramienta(
                    id="call_armar", nombre="armar_carrito",
                    argumentos={
                        "comercio_id": self._comercio_id,
                        "items": [{"producto_id": self._producto_id, "cantidad": 1}],
                        "justificacion": "compra de prueba",
                    },
                ),
            ),
        )


def _config(tmp_path) -> dict:
    return {
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "AGORA_PERSISTENCIA": "sqlite",
        "AGORA_SQLITE_PATH": str(tmp_path / "agora.db"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
    }


def _loguear(
    cliente: TestClient, contenedor, nombre_usuario: str = "tit_1", titular_id: str = "tit_1",
) -> str:
    """Multi-usuario (4 de septiembre de 2026): registra un usuario de
    prueba (mismo camino que `scripts/crear_usuario.py`, directo contra el
    `Contenedor`) e inicia sesion con el `TestClient` -- el `TestClient`
    conserva la cookie que deja `POST /auth/iniciar-sesion` para el resto
    de las peticiones que haga, exactamente como un navegador. Devuelve el
    `titular_id`, para las pruebas que todavia necesitan compararlo contra
    algo (por ejemplo, `mandato.titular_id`)."""
    contenedor.registrar_usuario(nombre_usuario, "clave-de-prueba", titular_id=titular_id)
    resp = cliente.post(
        "/auth/iniciar-sesion",
        json={"nombre_usuario": nombre_usuario, "contrasena": "clave-de-prueba"},
    )
    assert resp.status_code == 200, resp.text
    return titular_id


def _producto_barato(contenedor):
    """Mismo criterio que `tests/test_composicion_agente.py`: cualquier
    producto EN_STOCK por 20.000 COP o menos, para que `pagar()` llegue a
    la politica blanda (`esperando_confirmacion_humana`) en vez de
    rechazarse de una por el tope duro."""
    for comercio in contenedor.navegar_catalogo.buscar_comercios():
        for producto in contenedor.navegar_catalogo.buscar_productos(comercio.comercio_id):
            if producto.disponibilidad is Disponibilidad.EN_STOCK and producto.precio.pesos <= 20_000:
                return comercio.comercio_id, producto.producto_id
    raise AssertionError("el catalogo no tiene ningun producto <= 20.000 COP")


def _leer_primer_evento(app, sesion_id: str) -> dict:
    """Lee directo de `app.state.sesiones` (expuesto por `crear_app` para
    pruebas) en vez de conectarse a `GET /sesiones/{id}/eventos`: el
    `TestClient` de FastAPI arma la conexion sobre un transporte ASGI que
    espera a que el generador de un `StreamingResponse` termine antes de
    dejar leer nada -- y el de esta ruta nunca termina por diseno (sigue
    mandando `keepalive` mientras la sesion siga viva). La codificacion en
    si -- que la cola se traduzca a lineas `data: ...` -- la prueba aparte
    `test_flujo_sse_codifica_un_evento_de_la_cola_como_server_sent_event`.
    """
    return app.state.sesiones.eventos(sesion_id).get(timeout=5)


def test_salud_responde_ok_y_dice_si_hay_agente(tmp_path):
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    app = crear_app(None, contenedor)
    cliente = TestClient(app)

    respuesta = cliente.get("/salud")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "agente_disponible": False}


def test_index_sirve_el_html():
    app = crear_app(None, construir(leer_configuracion({})))
    cliente = TestClient(app)

    respuesta = cliente.get("/")

    assert respuesta.status_code == 200
    assert "text/html" in respuesta.headers["content-type"]
    assert "agora" in respuesta.text.lower()


def test_crear_sesion_responde_503_sin_agente(tmp_path):
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    app = crear_app(None, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    respuesta = cliente.post("/sesiones")

    assert respuesta.status_code == 503


def test_sesion_desconocida_responde_404(tmp_path):
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    contenedor = replace(contenedor, modelo_lenguaje=_ModeloProgramable("com_x", "prd_x"))
    agente = construir_agente(contenedor)
    app = crear_app(agente, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    respuesta = cliente.post("/sesiones/no-existe/mensajes", json={"texto": "hola"})

    assert respuesta.status_code == 404


def test_eventos_de_sesion_desconocida_responde_404(tmp_path):
    """404 sale ANTES de armar el `StreamingResponse` (la ruta valida la
    sesion primero) -- por eso esta prueba SI puede usar `TestClient.get`
    normal sin pelear con la limitacion de lectura incremental que explica
    el docstring de `_leer_primer_evento`: nunca llega a crearse un
    generador infinito."""
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    contenedor = replace(contenedor, modelo_lenguaje=_ModeloProgramable("com_x", "prd_x"))
    agente = construir_agente(contenedor)
    app = crear_app(agente, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    respuesta = cliente.get("/sesiones/no-existe/eventos")

    assert respuesta.status_code == 404


def test_flujo_completo_por_http_arma_firma_paga_y_confirma(tmp_path):
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    comercio_id, producto_id = _producto_barato(contenedor)
    # Multi-comercio: enrolar vincula el medio con ESTE comercio -- se
    # descubre antes de enrolar, no despues (ver el docstring de
    # aplicacion/enrolar_medio.py).
    contenedor.enrolar_medio("3001234567", "titular@correo.com", "tit_1", comercio_id)

    contenedor = replace(contenedor, modelo_lenguaje=_ModeloProgramable(comercio_id, producto_id))
    agente = construir_agente(contenedor)
    assert agente is not None
    app = crear_app(agente, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    # 1. Arranca la sesion -- mismo `sesion_id` para toda la charla, como
    #    una pestana de navegador.
    sesion_id = cliente.post("/sesiones").json()["sesion_id"]

    # 2. La persona escribe -- el agente arma el carrito y deja la
    #    propuesta SIN FIRMAR (misma logica que `composicion/agente.py:
    #    armar_carrito`, ahora alcanzada por HTTP en vez de por un tool
    #    call de CLI directo).
    respuesta = cliente.post(
        f"/sesiones/{sesion_id}/mensajes", json={"texto": "quiero comprar algo barato"},
    )
    assert respuesta.status_code == 200
    assert "popup" in respuesta.json()["respuesta"].lower()

    # 3. El evento de "hay que firmar" ya deberia estar en la cola SSE de
    #    esta sesion.
    evento_propuesta = _leer_primer_evento(app, sesion_id)
    assert evento_propuesta["tipo"] == "propuesta_pendiente"
    assert evento_propuesta["comercio_id"] == comercio_id
    assert len(evento_propuesta["items"]) == 1
    propuesta_id = evento_propuesta["propuesta_id"]

    # 4. La persona firma desde el popup -- nunca el agente. `EmitirMandato`
    #    corta el mandato exacto al carrito, asi que el turno que sigue
    #    (disparado por `sesiones.continuar`) casi siempre llama a `pagar()`
    #    y esa cae en la senal blanda `esperando_confirmacion_humana`.
    respuesta = cliente.post(
        f"/propuestas/{propuesta_id}/firmar",
        json={"sesion_id": sesion_id},
    )
    assert respuesta.status_code == 200
    datos_firma = respuesta.json()
    assert datos_firma["mandato_id"]
    assert datos_firma["carrito_id"] == evento_propuesta["carrito_id"]
    # El agente se entero solo (via `sesiones.continuar`) y ya contesto --
    # la persona nunca tuvo que volver a escribirle nada.
    assert datos_firma["respuesta_agente"] == "Quedo esperando tu confirmacion."
    # La propuesta firmada tiene que poder encontrarse de verdad.
    assert contenedor.propuestas.obtener(propuesta_id).propuesta_id == propuesta_id

    # 5. Ese mismo turno (pagar() esperando confirmacion) tambien encolo un
    #    segundo evento SSE -- el popup de confirmar/rechazar el cobro.
    evento_confirmacion = _leer_primer_evento(app, sesion_id)
    assert evento_confirmacion["tipo"] == "confirmacion_pendiente"
    assert evento_confirmacion["mandato_id"] == datos_firma["mandato_id"]
    assert evento_confirmacion["carrito_id"] == datos_firma["carrito_id"]
    intencion_id = evento_confirmacion["intencion_id"]

    # 6. La persona confirma desde el segundo popup.
    respuesta = cliente.post(
        f"/intenciones/{intencion_id}/retomar",
        json={
            "mandato_id": evento_confirmacion["mandato_id"],
            "carrito_id": evento_confirmacion["carrito_id"],
            "aprueba": True,
            "sesion_id": sesion_id,
        },
    )
    assert respuesta.status_code == 200
    datos_retomar = respuesta.json()
    assert datos_retomar["ejecutado"] is True
    assert datos_retomar["respuesta_agente"] == "Listo, gracias por confirmar."

    # 7. `consultar_estado` (la misma herramienta que usa el agente, y el
    #    mismo `contenedor` que arranco la charla) tiene que ver el
    #    resultado -- el bug de la etapa 6 (segunda parte) que esto no
    #    debe reintroducir.
    estado = contenedor.consultar_estado(intencion_id)
    assert estado.estado == "aprobado"


def test_rechazar_propuesta_por_http_le_avisa_al_agente(tmp_path):
    """El bug reportado: rechazar la propuesta desde el popup ("Cancelar")
    no le llegaba al agente de ninguna forma -- el ultimo mensaje del chat
    se quedaba siendo la propuesta armada, sin ningun aviso de que se
    rechazo. `POST /propuestas/{id}/rechazar` tiene que avisarle a la
    conversacion, igual que `/retomar` ya hace con `aprueba=False`."""
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    comercio_id, producto_id = _producto_barato(contenedor)
    contenedor = replace(contenedor, modelo_lenguaje=_ModeloProgramable(comercio_id, producto_id))
    agente = construir_agente(contenedor)
    app = crear_app(agente, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    sesion_id = cliente.post("/sesiones").json()["sesion_id"]
    cliente.post(f"/sesiones/{sesion_id}/mensajes", json={"texto": "quiero comprar algo barato"})
    evento_propuesta = _leer_primer_evento(app, sesion_id)
    propuesta_id = evento_propuesta["propuesta_id"]

    respuesta = cliente.post(
        f"/propuestas/{propuesta_id}/rechazar", json={"sesion_id": sesion_id},
    )

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["propuesta_id"] == propuesta_id
    # El agente se entero solo (via `sesiones.continuar`, el mismo
    # mecanismo que ya usan `firmar`/`retomar`), sin que la persona tuviera
    # que volver a escribirle nada.
    assert datos["respuesta_agente"] == "Entendido, no se firmo nada. Decime si queres otra propuesta."


def test_rechazar_propuesta_desconocida_por_http_responde_400(tmp_path):
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    app = crear_app(None, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    respuesta = cliente.post(
        "/propuestas/prp_no_existe/rechazar", json={"sesion_id": "sin-sesion"},
    )

    assert respuesta.status_code == 400


def test_flujo_sse_codifica_un_evento_de_la_cola_como_server_sent_event():
    """La codificacion misma (`_flujo_sse`, `app.py`), aislada del
    `TestClient` -- ver el docstring de `_leer_primer_evento` sobre por
    que las pruebas de arriba no pasan por la ruta HTTP para leer
    eventos."""
    from queue import Queue

    from agora.entradas.api.app import _flujo_sse

    cola: Queue = Queue()
    cola.put({"tipo": "propuesta_pendiente", "propuesta_id": "prp_1"})

    linea = next(_flujo_sse(cola))

    assert linea == 'data: {"tipo": "propuesta_pendiente", "propuesta_id": "prp_1"}\n\n'
    assert json.loads(linea[len("data:"):].strip()) == {
        "tipo": "propuesta_pendiente", "propuesta_id": "prp_1",
    }


# -- Enrolar y listar medios de pago desde la web (etapa 8) --------------- #
#
# Con la pasarela simulada (la que usa `_config` por defecto -- sin
# `AGORA_PASARELA=wompi`), `preparar_medio` deja el token en "APPROVED" de
# inmediato (`adaptadores/pasarelas/simulada/adaptador.py`), asi que estas
# pruebas alcanzan el camino "aprobado sin sondeo" de un solo tiro, igual
# que el bloque `if (datos.estado === "APPROVED")` de `chat.html`. El
# sondeo en si (`GET /medios/enrolar/{token}/estado` repetido) es
# responsabilidad del navegador, no de esta ruta -- por eso no hace falta
# reproducirlo aca para cubrir la ruta.

COMERCIO_ID = "com_1"


def test_enrolar_por_http_de_punta_a_punta_con_la_pasarela_simulada(tmp_path):
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    app = crear_app(None, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    # 1. Iniciar -- no bloquea, la simulada ya deja el token en APPROVED.
    respuesta = cliente.post(
        "/medios/enrolar/iniciar",
        json={"telefono": "3001234567", "correo": "titular@correo.com", "comercio_id": COMERCIO_ID},
    )
    assert respuesta.status_code == 200
    datos_inicio = respuesta.json()
    assert datos_inicio["estado"] == "APPROVED"
    token = datos_inicio["token"]

    # 2. Consultar el estado -- mismo token, misma respuesta (idempotente).
    #    `comercio_id` viaja como query param: es el mismo que se uso al
    #    iniciar, no un dato nuevo que el navegador decida solo.
    respuesta = cliente.get(f"/medios/enrolar/{token}/estado", params={"comercio_id": COMERCIO_ID})
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "APPROVED"}

    # 3. Confirmar -- la ruta vuelve a consultar el estado ella misma antes
    #    de guardar el medio (nunca confia en lo que mande el navegador).
    #    `titular_id` ya no viaja en el cuerpo -- sale de la cookie de
    #    sesion (`_loguear`, arriba).
    respuesta = cliente.post(
        "/medios/enrolar/confirmar",
        json={"token": token, "correo": "titular@correo.com", "comercio_id": COMERCIO_ID},
    )
    assert respuesta.status_code == 200
    ref = respuesta.json()
    assert ref["proveedor"] == "simulada"
    assert ref["id_externo"]

    # 4. El medio recien guardado tiene que aparecer al listarlo -- del
    #    mismo titular autenticado, sin pasar ningun id por query.
    respuesta = cliente.get("/medios")
    assert respuesta.status_code == 200
    medios = respuesta.json()["medios"]
    assert len(medios) == 1
    assert medios[0] == ref


def test_revocar_medio_por_http_lo_saca_de_la_lista(tmp_path):
    """`POST /medios/{id_externo}/revocar` -- el boton "Eliminar" del popup
    de medios en `chat.html`. Mismo `RevocarMedio` que ya usaba
    `entradas/cli/__main__.py:cmd_revocar`, ahora tambien alcanzable por
    HTTP con el titular saliendo de la cookie de sesion."""
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    app = crear_app(None, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    respuesta = cliente.post(
        "/medios/enrolar/iniciar",
        json={"telefono": "3001234567", "correo": "titular@correo.com", "comercio_id": COMERCIO_ID},
    )
    token = respuesta.json()["token"]
    respuesta = cliente.post(
        "/medios/enrolar/confirmar",
        json={"token": token, "correo": "titular@correo.com", "comercio_id": COMERCIO_ID},
    )
    ref = respuesta.json()

    respuesta = cliente.post(
        f"/medios/{ref['id_externo']}/revocar", json={"proveedor": ref["proveedor"]},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"]

    respuesta = cliente.get("/medios")
    assert respuesta.json() == {"medios": []}


def test_revocar_medio_de_otro_titular_responde_400_y_no_lo_apaga(tmp_path):
    """`RevocarMedio` verifica que la referencia sea `vivos()` del titular
    autenticado antes de pedirle la revocacion a la pasarela -- revocar a
    ciegas podria apagar la fuente equivocada (docstring de `aplicacion/
    revocar_medio.py`). Esta prueba lo ejercita por HTTP: el medio sigue
    vivo despues del intento fallido."""
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    app = crear_app(None, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    respuesta = cliente.post(
        "/medios/enrolar/iniciar",
        json={"telefono": "3001234567", "correo": "titular@correo.com", "comercio_id": COMERCIO_ID},
    )
    token = respuesta.json()["token"]
    respuesta = cliente.post(
        "/medios/enrolar/confirmar",
        json={"token": token, "correo": "titular@correo.com", "comercio_id": COMERCIO_ID},
    )
    ref = respuesta.json()

    # Otra persona, otra sesion -- pisa la cookie de la anterior en el
    # mismo `TestClient`, igual que un logout+login en el navegador.
    _loguear(cliente, contenedor, nombre_usuario="otra_persona", titular_id="tit_otra_persona")

    respuesta = cliente.post(
        f"/medios/{ref['id_externo']}/revocar", json={"proveedor": ref["proveedor"]},
    )
    assert respuesta.status_code == 400

    # El medio del primer titular no se toco. Se verifica contra el
    # repositorio directo (no por HTTP) para no tener que loguearse nuevo
    # como "tit_1" -- `registrar_usuario` haria upsert sobre el mismo
    # `titular_id` (PRIMARY KEY en `usuario`, `esquema.py`) y pisaria el
    # usuario que ya se registro para el, que es justo lo que esta prueba
    # no quiere ejercitar.
    vivos = contenedor.medios.vivos("tit_1", contenedor.config.ambiente)
    assert len(vivos) == 1
    assert vivos[0].to_json() == ref


def test_listar_medios_de_un_titular_sin_nada_enrolado_responde_vacio(tmp_path):
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    app = crear_app(None, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor, nombre_usuario="nadie_por_aca", titular_id="tit_nadie_por_aca")

    respuesta = cliente.get("/medios")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"medios": []}


def test_confirmar_enrolamiento_ignora_un_estado_falso_mandado_por_el_cliente(tmp_path):
    """Aunque el cuerpo de la peticion no tiene un campo de estado (el
    contrato de `_ConfirmarEnrolamientoEntrante` no lo admite), esta prueba
    documenta el porque: si a alguien se le ocurriera agregarlo despues,
    `confirmar_enrolamiento` en `app.py` lo seguiria ignorando porque
    vuelve a consultar `contenedor.consultar_enrolamiento(...)` el mismo
    antes de confirmar. Un token que nunca se inicio (no existe en la
    pasarela) es el caso mas simple para probarlo: la simulada lo trata
    como 'PENDING' (`estado_medio_por_token`), nunca como aprobado."""
    contenedor = construir(leer_configuracion(_config(tmp_path)))
    app = crear_app(None, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    respuesta = cliente.post(
        "/medios/enrolar/confirmar",
        json={"token": "tok-que-no-existe", "correo": "titular@correo.com", "comercio_id": COMERCIO_ID},
    )

    assert respuesta.status_code == 400
    respuesta_medios = cliente.get("/medios")
    assert respuesta_medios.json() == {"medios": []}


def test_sondeo_resuelve_por_http_un_pago_que_el_webhook_confirma_despues(tmp_path):
    """Reproduce el caso real que motivo la etapa 9: `retomar()` deja el
    cobro en 'PENDING' (Wompi real contra Nequi liquida de forma
    asincronica -- aca se fuerza con el correo magico de la pasarela
    simulada, ver `adaptadores/pasarelas/simulada/guion.py`), el webhook
    (en OTRO proceso, `entradas/webhooks/wompi.py`) resuelve el estado mas
    tarde escribiendolo en el mismo sqlite, y `SondeoDePagosPendientes` --
    corriendo en ESTE proceso, sin ningun hilo real ni `time.sleep`, solo
    `una_pasada()` llamada a mano -- es quien se entera y le avisa a la
    conversacion sin que la persona tenga que volver a preguntar."""
    config = _config(tmp_path)
    config["PAGADOR_EMAIL"] = "pendiente@correo.com"  # fuerza EstadoCobro.PENDIENTE
    contenedor = construir(leer_configuracion(config))
    comercio_id, producto_id = _producto_barato(contenedor)
    contenedor.enrolar_medio("3001234567", "titular@correo.com", "tit_1", comercio_id)

    contenedor = replace(contenedor, modelo_lenguaje=_ModeloProgramable(comercio_id, producto_id))
    agente = construir_agente(contenedor)
    app = crear_app(agente, contenedor)
    cliente = TestClient(app)
    _loguear(cliente, contenedor)

    sesion_id = cliente.post("/sesiones").json()["sesion_id"]
    cliente.post(f"/sesiones/{sesion_id}/mensajes", json={"texto": "quiero comprar algo barato"})
    evento_propuesta = _leer_primer_evento(app, sesion_id)
    propuesta_id = evento_propuesta["propuesta_id"]

    datos_firma = cliente.post(
        f"/propuestas/{propuesta_id}/firmar",
        json={"sesion_id": sesion_id},
    ).json()
    evento_confirmacion = _leer_primer_evento(app, sesion_id)
    intencion_id = evento_confirmacion["intencion_id"]

    respuesta = cliente.post(
        f"/intenciones/{intencion_id}/retomar",
        json={
            "mandato_id": evento_confirmacion["mandato_id"],
            "carrito_id": evento_confirmacion["carrito_id"],
            "aprueba": True,
            "sesion_id": sesion_id,
        },
    )
    assert respuesta.json()["motivo"] == "PENDING"

    # 1. La sesion queda registrada como a la espera de esta intencion --
    #    esto es lo que hoy le faltaba al modulo web.
    assert app.state.sesiones.pendientes() == {intencion_id: sesion_id}

    # 2. El webhook resuelve el estado -- desde ESTE test se simula
    #    escribiendo directo en el mismo registro que `ConciliarEvento`
    #    escribiria desde el otro proceso, sin pasar por HTTP ni por la
    #    validacion de checksum (eso ya lo cubre `test_webhook_wompi.py`).
    contenedor.estados.fijar(intencion_id, "aprobado", "APPROVED")

    # 3. Una vuelta de sondeo -- sin hilos, sin esperar ningun intervalo.
    sondeo = SondeoDePagosPendientes(app.state.sesiones, contenedor.consultar_estado)
    sondeo.una_pasada()

    # 4. La sesion ya no esta pendiente, y el navegador tiene un evento SSE
    #    nuevo con lo que el agente contesto sin que nadie le preguntara.
    assert app.state.sesiones.pendientes() == {}
    evento_final = _leer_primer_evento(app, sesion_id)
    assert evento_final == {
        "tipo": "mensaje_agente",
        "texto": "Genial, tu pago ya quedo aprobado del lado del banco.",
    }

    # 5. Y el estado que veria `consultar_estado` (la misma herramienta que
    #    usa el agente) ya refleja el desenlace real.
    assert contenedor.consultar_estado(intencion_id).estado == "aprobado"
