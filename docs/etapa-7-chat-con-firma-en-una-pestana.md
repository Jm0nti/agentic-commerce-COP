# Etapa 7: el chat y la firma en una sola pestaña

**27 de agosto de 2026.** Responde la pregunta que quedó pendiente después
de la etapa 6 ("¿qué haría falta para no alternar entre dos terminales?"):
`entradas/api/`, una API HTTP + un frontend de una sola página donde el
agente charla y la persona firma la propuesta / confirma el cobro con un
popup, sin salir del navegador.

No cambia el argumento central de la PoC. `agente/herramientas.py:PROHIBIDAS`
le sigue negando `firmar`/`retomar` al agente a nivel de catálogo de
herramientas — nada de esto se toca. Lo único que cambia es CÓMO llega el
humano a apretar el botón que firma o confirma: antes, corriendo un comando
en otra terminal (`firmar`, `retomar`); ahora, con un click en un popup que
llama a `POST /propuestas/{id}/firmar` o `POST /intenciones/{id}/retomar`.
El agente nunca tiene una herramienta que alcance esas rutas.

## Qué se agregó

**`agora/entradas/api/sesiones.py` -- `AlmacenDeSesiones`.** Una
`Conversacion` en memoria por sesión de chat (un id por pestaña de
navegador), igual de efímera que `Conversacion` misma. Después de cada
turno, escanea los mensajes de rol `"tool"` nuevos: si `armar_carrito`
dejó una propuesta, o `pagar` dejó `esperando_confirmacion=true`, encola un
evento (`propuesta_pendiente` / `confirmacion_pendiente`) en una
`queue.Queue` propia de esa sesión.

**`agora/entradas/api/app.py` -- `crear_app(agente, contenedor)`.** Misma
convención que `entradas/webhooks/wompi.py`: factoría pura, sin
`os.environ`, sin construir el `Contenedor`. Siete rutas:

| Ruta | Qué hace |
| --- | --- |
| `GET /` | sirve `estatico/chat.html` |
| `GET /salud` | `{"ok": true, "agente_disponible": bool}` |
| `POST /sesiones` | arranca una `Conversacion` nueva; 503 sin `DEEPSEEK_API_KEY` |
| `POST /sesiones/{id}/mensajes` | un turno de chat -- `{"respuesta": str}` |
| `GET /sesiones/{id}/eventos` | Server-Sent Events: `propuesta_pendiente` / `confirmacion_pendiente` |
| `POST /propuestas/{id}/firmar` | la PERSONA firma desde el popup -- mismo llamado que `cmd_firmar` |
| `POST /intenciones/{id}/retomar` | la PERSONA confirma o rechaza desde el popup -- mismo llamado que `cmd_retomar` |

**SSE solo dispara el popup, nunca lo resuelve.** El evento por streaming
le dice al frontend CUÁNDO mostrar un modal. La resolución (firmar,
confirmar, rechazar) viaja por la respuesta HTTP directa de `/firmar` o
`/retomar` -- que además trae `respuesta_agente`: el texto que el agente
contesta al enterarse de lo que la persona acaba de hacer, calculado ahí
mismo (`sesiones.continuar`, un mensaje más en la misma `Conversacion`, otra
vuelta de `Agente.turno`) para que el modal se cierre con una respuesta en
la mano, sin que la persona tenga que volver a escribir nada.

**`composicion/agente.py`: `pagar()` ahora devuelve `mandato_id` y
`carrito_id` como claves de primer nivel**, no solo enterrados en la
`"nota"` de texto libre -- `sesiones.py` los necesita para armar el evento
`confirmacion_pendiente` sin parsear texto, igual que ya pasaba con
`"propuesta"` en `armar_carrito`.

**`agora/entradas/api/estatico/chat.html`.** Un solo archivo (HTML + CSS +
JS inline, sin build step): un panel de chat, un campo `titular_id`
persistido en `localStorage`, un `EventSource` escuchando `/eventos`, y dos
modales (firmar / confirmar-rechazar) que llaman a las rutas de arriba.

**`scripts/servir_api.py`.** Composition root: lee `.env`, arma el
`Contenedor` y el `Agente`, llama a `crear_app`, corre `uvicorn`. Puerto
por defecto `8002` (`8001` ya lo usa `servir_webhook_wompi.py`).

## Cómo se prueba

`tests/test_api_app.py::test_flujo_completo_por_http_arma_firma_paga_y_confirma`
es la prueba de punta a punta: sesión → mensaje de chat → evento
`propuesta_pendiente` → `POST /firmar` → evento `confirmacion_pendiente` →
`POST /retomar` → `consultar_estado` ve `"aprobado"`, todo por `TestClient`,
sin tocar DeepSeek ni la red.

Usa `_ModeloProgramable`, más flexible que el `_ModeloGuionado` de
`tests/test_agente_conversacion.py`: en vez de una lista fija de
respuestas, mira el último mensaje del historial y decide qué hacer --
hace falta porque `mandato_id`/`carrito_id` no existen todavía cuando el
test arranca (se generan recién cuando `/firmar` corre, en medio de la
conversación), así que no hay forma de dejarlos precargados de antemano.

**Limitación de prueba, no de la app:** `TestClient` (el transporte ASGI
que usa `httpx` para pruebas) no soporta leer un `StreamingResponse` de a
poco cuando el generador nunca termina -- que es exactamente cómo está
armado `GET /sesiones/{id}/eventos` (sigue mandando `keepalive` mientras
la sesión viva). Por eso las pruebas leen los eventos directo de
`app.state.sesiones` (expuesto para esto) en vez de conectarse a la ruta
HTTP; la codificación SSE en sí (`_flujo_sse`) se prueba aparte, aislada,
sin `TestClient` de por medio. Contra un servidor real (`uvicorn`,
verificado a mano más abajo) el streaming funciona sin problema -- es una
limitación del cliente de prueba, no del servidor.

## Cómo probarlo a mano

```
python scripts/servir_api.py
```

Abrir `http://localhost:8002/` en el navegador, escribir el `titular_id`
que ya se enroló por CLI, y chatear. Cuando el agente arme una propuesta
aparece el primer popup ("Firmar"); al firmar, si `pagar()` queda
`esperando_confirmacion` (lo más común con un mandato cortado exacto al
carrito) aparece el segundo popup ("Confirmar" / "Rechazar") -- las dos
veces sin salir de la pestaña.

Verificado en esta sesión contra un `uvicorn` real (no `TestClient`):
`/salud`, `/sesiones`, `POST /propuestas/{id}/firmar` y
`POST /intenciones/{id}/retomar` -- de punta a punta, con sqlite real
(propuesta armada, mandato firmado, cobro esperando confirmación,
confirmado, `consultar_estado` reflejando `"aprobado"`). El turno real
contra DeepSeek no se pudo probar a mano en esta sesión concreta -- el
entorno donde corrió esta verificación no tiene salida de red hacia la API
de DeepSeek -- pero es el mismo camino de código (`Agente.turno` ->
`AdaptadorDeepSeek.responder`) que ya cubre `tests/
test_agente_conversacion.py` y que uno de los descubrimientos de esta
misma sesión (ver más abajo) obligó a blindar con un manejo de errores
explícito.

**Hallazgo real, corregido en el camino:** sin ese manejo, un `DEEPSEEK_API_KEY`
que no puede conectarse tumbaba `POST /sesiones/{id}/mensajes` con un 500
en texto plano (`Internal Server Error`), y silenciaba `firmar`/`retomar`
del mismo modo si el aviso al agente fallaba. Ahora: `ErrorDeDominio`
(`ModeloNoDisponible`, `RespuestaModeloInvalida`) y `LimiteDeTurnosExcedido`
se atrapan igual que ya hacía `entradas/cli/__main__.py:cmd_chat` --
`/mensajes` devuelve un 502 con el motivo real en JSON, y `/firmar`/
`/retomar` devuelven 200 con `"respuesta_agente": null` (el mandato ya se
firmó, o el cobro ya se resolvió; que el agente no pudiera contestar no
deshace eso).

## Qué no cambia

- `AGORA_PERSISTENCIA=sqlite` sigue siendo necesario para que `firmar`
  encuentre una propuesta que armó otro proceso -- acá ya no aplica entre
  dos terminales, sino entre el proceso que corre `scripts/servir_api.py`
  y cualquier reinicio de ese mismo proceso. La `Conversacion` de cada
  sesión de chat, en cambio, sigue sin persistir -- reiniciar el servidor
  en medio de una charla obliga a recargar la página.
- La llave privada de firma (`AGORA_LLAVE_FIRMA_SK`) sigue viviendo en el
  mismo proceso que el agente, exactamente el mismo riesgo que ya aceptaba
  `entradas/cli/chat` desde la etapa 5 (la llave se carga en memoria vía
  `construir()`, solo que antes era estructuralmente inalcanzable para el
  código de tool-calling del agente). Esta etapa no lo empeora ni lo
  arregla -- lo hereda, a propósito, en vez de inventar una separación que
  el resto del proyecto no tiene.
