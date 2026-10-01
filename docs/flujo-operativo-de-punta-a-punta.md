# Flujo operativo, de punta a punta

**9 de septiembre de 2026.** Este documento responde una pregunta distinta a
la de `docs/flujo-propuesta-mandato.md`: ese documento explica **qué es** un
mandato y por qué el agente nunca puede firmarlo; este explica **qué hay que
tener corriendo, en qué orden, y por dónde viaja cada mensaje** para que una
compra real llegue de punta a punta — desde que Juan abre el navegador hasta
que Wompi confirma el cobro por webhook. Es el mapa de infraestructura;
`flujo-propuesta-mandato.md` es el mapa de la criptografía. Se leen mejor
juntos.

---

## 1. Mapa de piezas

Para una demo completa contra Wompi real conviven **tres procesos**, más un
túnel:

| Proceso | Comando | Puerto | Para qué sirve | ¿Hace falta siempre? |
|---|---|---|---|---|
| API + chat web | `python -m agora api` | 8002 | Login, chat con el agente, firma/confirmación por popup, alta de medios de pago — todo en una sola pestaña | Sí (o su equivalente por CLI) |
| Webhook de Wompi | `python -m agora webhook` | 8001 | Recibe la confirmación asíncrona de un cobro (`ConciliarEvento`) | Solo con `AGORA_PASARELA=wompi` |
| Túnel (ngrok / cloudflared) | `ngrok http --url https://<dominio>.ngrok-free.dev 8001` | — | Le da al puerto 8001 una URL pública para que Wompi le pueda pegar | Solo con `AGORA_PASARELA=wompi` |
| CLI | `python -m agora cli ...` | — | Alternativa a la web: enrolar, emitir, pagar, retomar, chatear, todo desde la terminal | No, es intercambiable con la web |

Con `AGORA_PASARELA=simulada` (el valor por defecto) los cobros se resuelven
al instante dentro del mismo proceso — **ni el webhook ni el túnel hacen
falta** para una demo sin dinero real. Los dos procesos y el túnel solo
importan cuando se cobra de verdad contra una cuenta Nequi real vía Wompi.

Los tres procesos (más la CLI, cuando se usa) comparten datos a través de un
único archivo SQLite (`agora_datos/agora.db`, `AGORA_PERSISTENCIA=sqlite`):
ahí viven los carritos, las propuestas sin firmar, los mandatos firmados, los
medios de pago vinculados por comercio, los usuarios y sus llaves de firma, y
el consumo acumulado del día. Sin SQLite (`AGORA_PERSISTENCIA=memoria`) nada
de eso sobrevive ni entre procesos ni entre reinicios — sirve para pruebas o
para una demo de una sola terminal, y `ConfiguracionAgora` directamente se
niega a arrancar en `wompi` + `produccion` + `memoria`: perder el consumo
acumulado al reiniciar permitiría reusar un mandato ya agotado.

---

## 2. Se sirve la API (`servir_api.py`, puerto 8002)

Es el composition root del punto de entrada web: lee el `.env`, arma el
`Contenedor` (`composicion/contenedor.py`) y levanta `agora/entradas/api/`
con `uvicorn`. Sirve, en un solo proceso:

- La página estática (`entradas/api/estatico/chat.html`) en `GET /`.
- Login (`/auth/...`).
- El chat con el agente (`/sesiones/...`).
- Firma y confirmación humana (`/propuestas/{id}/firmar`,
  `/intenciones/{id}/retomar`).
- Alta de medios de pago (`/medios/...`).

No necesita el túnel ni estar expuesto a internet — corre en
`localhost:8002` y solo Juan (o quien esté frente al navegador) le habla.

## 3. Se ejecuta el receptor de webhook (`servir_webhook_wompi.py`, puerto 8001)

Es un composition root aparte, deliberadamente separado del anterior — ver
`docs/etapa-4-webhook-y-retomo.md`. Levanta `agora/entradas/webhooks/
wompi.py` con `uvicorn`, y expone `POST
/pagos/wompi/transacciones/{comercio_id}`: la ruta a la que Wompi golpea
cuando confirma o rechaza un cobro que había quedado `PENDING`. También sirve
`GET /salud` para confirmar que está vivo antes de exponerlo.

Este proceso nunca lo llama una persona a mano — está pensado para correr
desatendido, recibiendo eventos que Wompi manda por su cuenta en cualquier
momento.

## 4. Se abre el canal con ngrok (o cloudflared)

`servir_webhook_wompi.py` escucha en `localhost:8001`, pero el servidor de
Wompi vive en internet y no tiene forma de llegar a un `localhost` de la
máquina de Juan. El túnel resuelve exactamente eso: le da al puerto 8001 una
URL pública (`https://algo.ngrok-free.app` o `https://algo.trycloudflare.com`)
que reenvía cada petición entrante hacia `localhost:8001`.

```bash
ngrok http --url https://rhyme-armless-private.ngrok-free.dev 8001
```

Ese dominio fijo (plan de ngrok con dominio reservado) es a propósito: con un
túnel gratuito efímero la URL cambia cada vez que se reinicia, y hay que
volver a pegarla a mano en el panel de Wompi — **una vez por cada comercio**,
porque aunque el túnel y el puerto son uno solo para todos los comercios
(sección 8), cada comercio real tiene su propia entrada en su propio panel de
Wompi.

Nótese qué NO se expone: el puerto 8002 (el chat) nunca necesita salir a
internet. Solo el webhook necesita ser alcanzable desde afuera, porque es el
único de los tres procesos al que le habla un sistema externo por su cuenta.

---

## 5. El usuario entra a la app: login multiusuario

Desde el 4 de septiembre de 2026 la app dejó de aceptar un `titular_id` como
texto libre (antes era un `<input>` guardado en `localStorage`, sin ninguna
verificación — cualquiera podía escribir el id de otra persona y ver sus
medios de pago). Ahora hay una pantalla de login real:

1. Alguien con acceso a la terminal del servidor da de alta al usuario **de
   antemano**, fuera de la app — no hay registro por HTTP:

   ```bash
   python -m agora crear-usuario --nombre-usuario juan --contrasena ****
   ```

   Este comando hace dos cosas atómicamente: crea el `Usuario` (nombre de
   usuario + hash de la contraseña, `RepositorioUsuarios`) y le genera **su
   propio par de llaves ed25519** (`RepositorioLlaves`) — la contraseña
   nunca es la llave de firma, son dos mecanismos distintos que nacen juntos.
   Antes de este cambio existía una sola llave de firma por proceso
   (`agora_datos/secretos/firma.sk`) y cualquier titular firmaba con ella —
   indistinguible criptográficamente de cualquier otro. Ahora
   `SelectorDeFirmante.para(titular_id)` resuelve la llave correcta de cada
   quien al momento de firmar (ver sección 7).

2. En el navegador, `POST /auth/iniciar-sesion` recibe usuario + contraseña,
   los verifica (`IniciarSesion`, que compara el hash — el mismo error
   genérico si el usuario no existe o si la contraseña no coincide, para no
   poder enumerar usuarios válidos probando) y deja una **cookie httponly**
   (`agora_sesion`, 12 horas de duración, en memoria del proceso
   `servir_api.py` — no en SQLite: es un token efímero, no un dato de
   negocio).

3. De ahí en adelante, toda ruta protegida (firmar, ver medios, abrir un
   chat) saca el `titular_id` de esa cookie vía la dependencia
   `_requiere_titular` — **nunca de un campo que mande el navegador**. Es lo
   que impide que alguien pida firmar o listar medios en nombre de otro
   titular con solo cambiar un valor en el formulario.

La CLI sigue sin pedir login: alcanza con pasarle un `titular_id` que ya
tenga un usuario creado (y por lo tanto, una llave de firma). Si no lo tiene,
el error es explícito (`SinLlaveDeFirma`) en vez de fallar en silencio o
generar una llave nueva sobre la marcha.

---

## 6. Empieza la conversación con el agente

Con sesión iniciada, `POST /sesiones` abre una `Conversacion` nueva
(`entradas/api/sesiones.py:AlmacenDeSesiones`), atada al `titular_id` que la
creó. Cada mensaje viaja por `POST /sesiones/{id}/mensajes`.

**La memoria de la conversación no persiste entre sesiones, a propósito** —
vive en un diccionario en memoria del proceso `servir_api.py`. Si el proceso
se reinicia, todas las conversaciones abiertas se pierden y hay que empezar
de nuevo. Es una simplificación consciente de la PoC (documentada en el
docstring del propio módulo), y es un concepto **completamente distinto** de
la sesión de login de la sección 5: hay tres nociones de "sesión" en esta
app y conviene no confundirlas —

| Qué | Dónde vive | Sobrevive un reinicio | Para qué |
|---|---|---|---|
| Sesión de **login** (`AlmacenDeSesionesWeb`) | Memoria de `servir_api.py` | No | Saber qué `titular_id` hay detrás de la cookie |
| **Conversación** de chat (`AlmacenDeSesiones`) | Memoria de `servir_api.py` | No | El historial de mensajes con el agente |
| **Carritos / propuestas / mandatos** | SQLite (`agora_datos/agora.db`) | Sí | Que `firmar` en otro proceso (o después de un reinicio) encuentre lo que el chat armó |

Es justamente porque la tercera fila sí persiste que el resto del flujo
funciona aunque la conversación en sí sea desechable: el agente arma un
carrito y una propuesta, la persona la firma —incluso desde otra pestaña o
después de que el servidor se haya reiniciado— y el mandato queda en pie,
aunque el historial de chat que lo originó ya no exista.

Mientras se conversa, la ruta `GET /sesiones/{id}/eventos` mantiene abierto
un canal SSE (server-sent events) que **solo dispara avisos, nunca resuelve
nada por sí mismo**: cuando el agente deja una propuesta sin firmar o un
cobro esperando confirmación, empuja `propuesta_pendiente` o
`confirmacion_pendiente` y el navegador abre el popup correspondiente. La
resolución real (firmar, confirmar, rechazar) viaja por la respuesta HTTP
directa de `/firmar` o `/retomar` — el SSE es solo el timbre, no la puerta.

---

## 7. El usuario enrola sus medios de pago

Antes de poder firmar un mandato contra un comercio, el titular necesita un
medio de pago **vinculado a ese comercio específico** (ver sección 8 de
`flujo-propuesta-mandato.md`). Se puede hacer de dos formas equivalentes:

**Desde la web**, con el botón "Medios de pago" del encabezado — no depende
de ningún chat abierto, es un acto del titular en cualquier momento:

1. `POST /medios/enrolar/iniciar` (con `comercio_id`) — nace un token y, con
   `AGORA_PASARELA=wompi`, el titular recibe un **push real en su app
   Nequi**.
2. El navegador sondea `GET /medios/enrolar/{token}/estado` a su propio
   ritmo, hasta ver un estado final. El sondeo existe porque aceptar el push
   puede tardar hasta 5 minutos y ninguna petición HTTP debería quedarse
   bloqueada tanto tiempo esperando.
3. `POST /medios/enrolar/confirmar` — nace el `MedioDePagoRef` (la fuente de
   pago) y `RepositorioMedios.guardar(ref, titular_id, comercio_id)` deja
   registrada la vinculación con ese comercio puntual.
4. `GET /medios` lista lo que ya está enrolado para ese titular.

**Desde la CLI**, en un solo comando bloqueante (`EnrolarMedio` orquesta los
mismos tres pasos):

```bash
python -m agora cli enrolar --telefono 3001234567 --titular tit_demo --comercio <comercio_id>
```

Con `AGORA_PASARELA=simulada` (el default) no hay push real: se genera un
medio de pago de mentiras al instante, sin tocar ninguna cuenta. Con
`AGORA_PASARELA=wompi` en producción, es dinero y una cuenta Nequi reales.

Una vez vinculado un comercio, no hay que volver a enrolar para comprar ahí
de nuevo — `RepositorioMedios.vinculado_con(titular_id, comercio_id,
ambiente)` lo sigue encontrando. La primera compra en un comercio **distinto**
sí pide un enrolamiento nuevo, aunque el titular ya tenga un Nequi enrolado
en otro.

---

## 8. El agente propone, el usuario firma

Este paso es el corazón del sistema y `docs/flujo-propuesta-mandato.md` lo
desarrolla completo (el tipo `PropuestaDeMandato`, la carga canónica que se
firma, Ed25519, por qué el agente no puede firmar ni estructuralmente). Acá
solo el resumen operativo, con lo que cambió desde que ese documento se
escribió: **la firma ya no sale de una llave compartida por el proceso, sale
de la llave propia del titular** (sección 5). `SelectorDeFirmante.
para(titular_id)` — resuelto por `EmitirMandato` contra `RepositorioLlaves`
— reemplazó al `cargar_o_generar_firmante` de una sola llave por proceso.
Todo lo demás del recorrido (la propuesta sin firma, el tipo de dato
separado que hace imposible confundirla con un `Mandato`, la verificación
por `RepositorioMedios.vinculado_con` antes de firmar) sigue exactamente
igual.

En resumen: el agente llama a su herramienta `armar_carrito`, que arma un
`Carrito` y una `PropuestaDeMandato` sin firma. El SSE de la sección 6 abre
el popup; la persona ve el comercio, los ítems y el monto exacto antes de
apretar "Firmar", lo que dispara `POST /propuestas/{id}/firmar`. Ese
endpoint —el mismo caso de uso que usa la CLI cuando la misma persona arma y
firma en una sola terminal— busca la propuesta y el carrito por id (nunca
confía en lo que la propuesta "dice" traer), verifica el medio vinculado con
ESE comercio, arma el `Mandato` y lo firma con la llave del titular
autenticado. El resultado se guarda en SQLite y de ahí en más es lo único
que cualquier cobro futuro puede verificar.

---

## 9. La bóveda ejecuta: el cobro contra Wompi

Con el `mandato_id` en mano, el agente llama a su herramienta `pagar()`, que
arma una `Intencion` y la manda a `EjecutarIntencion`
(`agora/aplicacion/ejecutar_intencion.py`). En orden:

1. **Topes duros** (20.000 COP por transacción, 100.000 COP por día,
   constantes en código, nunca configurables ni siquiera para el
   experimento).
2. **Reserva atómica** contra el cupo diario — si no cabe, ni se llega a
   evaluar el mandato.
3. **El mandato**: `Mandato.violaciones_contra(...)` recalcula la firma
   entera, el vencimiento, el comercio, el monto, el tope, los usos, la
   categoría y el hash del carrito, y `politica.evaluar` traduce eso a
   `PERMITIR` / `CONFIRMAR` (se pausa y se le pregunta a un humano — nunca
   al agente) / `BLOQUEAR`.
4. **El cobro**: `SelectorDePasarela.para(mandato.comercio_id)` resuelve
   cuál de los `AdaptadorWompi` del proceso usar —el de ESE comercio, con
   SUS credenciales propias (sección 10)— y le pide el cobro. Wompi valida
   internamente la firma de integridad calculada con el `integrity_secret`
   de ese comercio.

`EjecutarIntencion` **nunca se queda esperando** el desenlace final del
cobro. Wompi puede responder de dos formas distintas:

- **Sincrónica**, en la misma respuesta HTTP del POST de cobro: `APPROVED` o
  `DECLINED` de una vez (típico de tarjeta, o de un rechazo temprano por
  antifraude).
- **Asincrónica**: `PENDING` — el caso típico de Nequi, que liquida fuera de
  línea. Ahí la reserva del paso 2 se queda "viva" y el proceso sigue su
  curso sin bloquear: el desenlace real llega después, por webhook.

Con un mandato cortado exacto al carrito (`monto_max` igual al total,
`usos_max=1`, que es el default), casi siempre salta una señal blanda de
`CONFIRMAR` — "agota el mandato de una sola vez" y "es el último uso" son
casi automáticas. No es un error del sistema: es la consecuencia esperada de
firmar un mandato angosto. Cuando eso pasa, la persona ve el popup de
confirmación (sección 6) y resuelve con `POST /intenciones/{id}/retomar` (o
`agora.entradas.cli retomar` desde la terminal) — otro acto exclusivamente
humano, nunca del agente.

---

## 10. Wompi responde, y el canal de ngrok cierra el ciclo

Cuando el cobro queda `PENDING`, la única forma de que esta app se entere de
si Wompi terminó aprobando o rechazando es el webhook — **sin el receptor y
el túnel corriendo, una compra por Nequi se queda mostrando "pendiente" para
siempre en el chat, aunque el dinero ya haya salido de la cuenta real**. La
app nunca vuelve a preguntarle a Wompi por su cuenta; espera a que Wompi le
avise.

El recorrido completo de un evento:

1. Wompi resuelve la transacción del lado del banco (puede tardar segundos
   o minutos) y hace un `POST` a la URL que ese comercio tiene configurada
   en su panel — la que apunta al túnel de la sección 4:
   `https://<túnel>/pagos/wompi/transacciones/<comercio_id>`.
2. El túnel reenvía esa petición a `localhost:8001`, donde
   `servir_webhook_wompi.py` la recibe.
3. `entradas/webhooks/wompi.py` valida el `X-Event-Checksum` contra el
   `events_secret` **de ese comercio puntual** — Wompi no manda ningún
   header confiable de "qué comercio soy" antes de validar el checksum; la
   única forma de saber qué secreto usar es por cuál segmento de URL
   golpearon (por eso hay una ruta por comercio y no una sola compartida).
4. `ConciliarEvento` traduce el evento (`resultado_desde_evento`, que
   reconoce la referencia con el prefijo `agora-` que el propio adaptador le
   puso al cobrar), busca la reserva pendiente por `intencion_id`, y la
   confirma o la libera. Esta ruta **nunca levanta una excepción** — cada
   "nada que hacer" es un resultado con `procesado=False`, para que HTTP
   siempre pueda responder `200` (Wompi reintenta agresivamente los eventos
   que no se confirman con `200`).
5. Si la reserva quedó confirmada, `RegistroDeEstados` deja constancia de
   que esa intención ya se resolvió — es lo que le permite a un `retomar()`
   corrido en otro proceso (o al propio chat, si sigue abierto) enterarse de
   que la confirmación ya llegó, sin tener que preguntarle nada a nadie.

Todo esto pasa **sin que la persona haga nada**: ni un push, ni una
notificación llega al titular en esta fase — el webhook es la única señal,
y por eso correrlo (con el túnel apuntando bien) no es opcional en
producción.

---

## 11. Cómo se conecta cada comercio: las claves que genera Wompi

Desde el 1 de septiembre de 2026 el sistema soporta varios comercios reales
de Wompi **en el mismo proceso** — hoy, en el catálogo de la demo, Dulcería
La Golosina y Papelería El Lápiz Feliz. Cada uno es una cuenta de Wompi
distinta, con sus propias cuatro credenciales, generadas desde **el panel de
ESE comercio** (Desarrolladores → Llaves API / Desarrolladores → Eventos):

| Credencial | Para qué se usa |
|---|---|
| `public_key` | Identifica el comercio en las llamadas que no mueven dinero (tokenizar, crear fuente de pago) |
| `private_key` | Autentica las llamadas que sí cobran (`POST /v1/transactions`) |
| `integrity_secret` | Firma la integridad del payload que este sistema le manda a Wompi al cobrar — evita que alguien intercepte y altere un monto en tránsito |
| `events_secret` | Valida el `X-Event-Checksum` de los webhooks que Wompi manda de vuelta — sin él, `ConciliarEvento` marca los eventos de ese comercio como inválidos, y un cobro real nunca se llegaría a confirmar |

Estas cuatro llaves **no van en el `.env`** (esas variables `WOMPI_*` sueltas
solo alcanzaban para un comercio y no escalan a N). En su lugar viven en un
registro JSON, uno por comercio, indexado por el mismo `comercio_id` que usa
el catálogo:

```
agora_datos/secretos/comercios_wompi.json     (ruta configurable con AGORA_WOMPI_COMERCIOS)

{
  "com_a6066287f648": { "public_key": "pub_prod_...", "private_key": "prv_prod_...",
                         "integrity_secret": "prod_integrity_...", "events_secret": "prod_events_..." },
  "com_xxxxxxxxxxxx": { ... }
}
```

Ese archivo nunca se versiona ni se fabrica con datos de ejemplo — son
secretos reales que Juan tiene que crear a mano por comercio antes de correr
con `AGORA_PASARELA=wompi`.

Al arrancar cualquiera de los tres procesos, `composicion/configuracion.py`
lee ese JSON y arma `ConfiguracionAgora.wompi` como
`dict[comercio_id, ConfiguracionWompi]`. `composicion/contenedor.py` usa eso
para construir un `RegistroDePasarelas` (el `SelectorDePasarela`): con
`AGORA_PASARELA=wompi`, **un `AdaptadorWompi` completo por cada comercio**
—cliente HTTP y verificación de checksum totalmente separados, ningún
secreto de un comercio se mezcla con el de otro—; con `AGORA_PASARELA=
simulada` (el default), un único `AdaptadorSimulado` resuelve cualquier
`comercio_id` sin necesitar ninguna credencial real.

De ahí en adelante, cada caso de uso que necesita cobrar o enrolar deja de
recibir "la pasarela" fija por constructor y en su lugar recibe el selector,
resolviendo `selector.para(comercio_id)` en el momento — `EjecutarIntencion`
al cobrar (sección 9), `ConciliarEvento` al conciliar un evento (sección 10,
con el `comercio_id` que trae la URL del webhook, porque ahí todavía no hay
mandato del que sacarlo), y los tres pasos de enrolamiento (sección 7) al
crear o consultar una fuente de pago — un `payment_source_id` de Wompi queda
atado a la cuenta que lo creó y no es portable a otro comercio, aunque los
dos usen Wompi.

**Lo que esto no resuelve** (deuda técnica documentada a propósito, ver
sección 6 de `docs/flujo-propuesta-mandato.md`): la correspondencia entre un
medio de pago y el comercio al que está vinculado la garantiza
`EmitirMandato` en el momento de firmar, pero no viaja dentro de la firma del
mandato ni se reverifica al cobrar.

---

## 12. El recorrido completo, en una línea de tiempo

```
 [arranque]  servir_webhook_wompi.py (8001) ── túnel ngrok/cloudflared ──▶ internet
 [arranque]  servir_api.py (8002)  ◀── Juan, en el navegador

 Juan            servir_api.py                  SQLite            Wompi
  │  login (usuario+contraseña)                                    │
  ├──────────────▶│ cookie httponly                                │
  │  "quiero algo dulce"                                           │
  ├──────────────▶│ agente arma carrito ──▶ Carrito + Propuesta ───▶│(no aplica)
  │◀── popup "firmar" (SSE) ───│                                    │
  │  clic "Firmar"                                                  │
  ├──────────────▶│ EmitirMandato: llave DEL TITULAR ──▶ Mandato ──▶│
  │  (el agente pide pagar)                                         │
  │◀── popup "confirmar" (a veces) │                                │
  │  clic "Confirmar"                                                │
  ├──────────────▶│ EjecutarIntencion ── selector.para(comercio) ──────▶ POST /v1/transactions
  │                │                                                 │◀── PENDING (Nequi)
  │◀── "esperando confirmación" ──│                                  │
  │                │                                                 │  (banco resuelve)
  │                │◀──────────── servir_webhook_wompi.py ◀── túnel ◀── POST evento
  │                │  ConciliarEvento: confirma la reserva            │
  │◀── resultado final, sin volver a preguntar ──│                    │
```

---

## Documentos relacionados

- `docs/flujo-propuesta-mandato.md` — la criptografía detrás de la firma, el
  tipo `PropuestaDeMandato`, y por qué el agente nunca puede firmar (secciones
  3, 5 y 6 en particular).
- `docs/viabilidad-multi-comercio-wompi.md` — la evaluación y el diseño
  completo de multi-comercio (por qué una ruta por comercio y no un puerto
  por comercio, la vinculación medio↔comercio).
- `docs/variables-de-entorno.md` — la plantilla comentada del `.env` y del
  registro `comercios_wompi.json`.
- `README.md` — el runbook paso a paso para correr los tres procesos desde
  cero, incluidas las dos opciones de túnel.
- `docs/etapa-7-chat-con-firma-en-una-pestana.md` — el detalle de
  `entradas/api/`, las rutas HTTP y el mecanismo SSE.
