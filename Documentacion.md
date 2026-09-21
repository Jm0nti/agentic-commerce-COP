# Documentación técnica

Estado del código al 3 de septiembre de 2026, después de la etapa 7 (chat con
firma integrada en una sola pestaña) y de agregar soporte multi-comercio
(varios comercios reales de Wompi en el mismo proceso, ver
`docs/viabilidad-multi-comercio-wompi.md`). Este documento complementa al
`README.md`
(que explica qué es el proyecto y cómo correrlo) con el detalle de cada módulo,
cómo se integran entre sí, y los hallazgos relevantes que se fueron
encontrando en el camino.

---

## 1. Propósito y principio rector

El proyecto estudia qué pasa cuando un agente de inteligencia artificial
compra en nombre de una persona, usando dinero real sobre un riel de pagos
colombiano (Wompi + Nequi). La pregunta no es si un agente *puede* pagar —
puede — sino cuánto puede desviarse de lo que la persona autorizó antes de que
algo lo detenga.

Todo el diseño se deriva de una sola frase:

> **El agente propone. El humano firma. La bóveda ejecuta.**
> Ninguno de los tres puede hacer el trabajo de otro.

Esto no es solo una intención de diseño: está verificado por una prueba
automatizada (`tests/test_fronteras.py`) que falla el build si el paquete del
agente llega a importar, aunque sea indirectamente, un módulo que hable con
una pasarela de pagos o con la llave de firma.

---

## 2. Una implementación activa, un antecesor retirado

`agora/` es la única implementación activa del proyecto: arquitectura por
capas, persistencia en SQLite con reserva/confirmación atómica, un catálogo de
comercios simulados generado con IA (dos comercios reales de Wompi conviven en
el mismo proceso desde el 1 de septiembre de 2026), un agente conversacional
(DeepSeek) con una frontera de herramientas verificada por prueba, y dos
interfaces de usuario (línea de comandos y una página web de chat con firma
integrada).

### `boveda/` — la versión original (v1), retirada

Fue el código mínimo que primero demostró que se podía cobrar dinero real bajo
un mandato: hizo transferencias reales en producción (Fase A: enrolamiento de
una cuenta Nequi por push; Fase B: cobro contra esa cuenta), en un único
módulo plano, sin capas, con persistencia en archivos JSON. `agora/` se
construyó en seis etapas, documentadas cada una en `docs/` y en la memoria del
proyecto, migrando esa funcionalidad sin tocar `boveda/` mientras tanto — era
deliberado: `boveda/` era el código que ya movía dinero real y no había motivo
para arriesgarlo mientras se construía su reemplazo.

Con `agora/` ya cubriendo todo lo que hacía `boveda/`, se retiró del
repositorio. La evidencia experimental original (`recibos.jsonl`, los
mandatos v1 firmados — incluido el que documenta el primer hallazgo del
proyecto, un cobro de 15.000 COP aprobado contra un mandato que autorizaba
8.000) queda preservada intacta fuera de este checkout, no perdida. El
verificador de mandatos v1 que permitía re-verificar esa evidencia
(`agora/dominio/mandato/compat.py`) se retiró junto con `boveda/`, por la
misma razón: sin `boveda/` en el repositorio no queda nada con qué
compatibilizar. Ver `docs/limpieza-v1-boveda.md` para el detalle de esa
limpieza y `docs/historico/` para la documentación de la época en que
`boveda/` todavía era parte activa del proyecto.

### `wompi_lab/`

Banco de pruebas anterior a `boveda/`, congelado. Se conserva únicamente
porque `wompi_lab/payouts.py` es el único código del repositorio que sabe
hacer dispersiones (payouts) por Bre-B — no corre en ningún flujo actual.

---

## 3. Arquitectura de `agora/`: capas y regla de dependencia

```
agora/
├── dominio/        reglas puras: sin red, sin disco, sin variables de entorno
├── puertos/        interfaces (typing.Protocol) — el vocabulario común
├── aplicacion/      casos de uso: orquestan, no deciden reglas de negocio
├── adaptadores/    implementaciones reales de los puertos
├── agente/         FRONTERA DURA: lo único que el modelo de lenguaje puede tocar
├── entradas/       CLI, API web, receptor de webhook
└── composicion/     el único paquete que lee el entorno y arma todo
```

La regla de dependencia (quién puede importar a quién) es:

| Paquete | Puede importar | Nunca puede importar |
|---|---|---|
| `dominio/` | solo `dominio/` | todo lo demás |
| `puertos/` | `dominio/` | `aplicacion/`, `adaptadores/` |
| `aplicacion/` | `dominio/`, `puertos/` | **`adaptadores/`** |
| `adaptadores/` | `dominio/`, `puertos/` | `aplicacion/`, `entradas/` |
| `agente/` | `dominio/` (solo tipos), `puertos/` | **`adaptadores/pasarelas/`**, cualquier cosa con credenciales |
| `entradas/` | `aplicacion/`, `dominio/` | `adaptadores/` (los recibe ya armados) |
| `composicion/` | todo | — |

Esta tabla no es una convención documentada: **`tests/test_fronteras.py`** la
verifica leyendo el árbol de sintaxis (AST) de cada archivo `.py` bajo
`agora/`, y falla el build si alguna importación cruza una frontera prohibida.
Además hay una prueba dedicada
(`test_el_agente_no_alcanza_ninguna_pasarela`) que revisa específicamente que
ningún archivo de `agente/` importe algo con "pasarela" en el nombre fuera de
`puertos/`. Es la diferencia entre "documentamos que el agente no toca dinero"
y "es estructuralmente imposible que el agente toque dinero".

---

## 4. `dominio/` — las reglas, sin infraestructura

No importa `httpx`, `fastapi`, `sqlite3` ni `os` (verificado también por
`test_fronteras.py`).

- **`comun/dinero.py`** — `Dinero`: un valor inmutable de centavos + moneda.
  Existe para que nunca se mezclen pesos con centavos, ni dos monedas
  distintas, con una multiplicación suelta en algún punto de la frontera
  (el problema que sí tenía `boveda/nucleo.py`).
- **`comun/identidad.py`** — identificadores con tipo (`MandatoId`,
  `IntencionId`, `ComercioId`, etc.), todos `str` en tiempo de ejecución pero
  distintos para el verificador de tipos. Cada uno tiene un prefijo fijo
  (`mnd_`, `int_`, `com_`...) usado al generarlos.
- **`comun/errores.py`** — una jerarquía de excepciones tipadas, todas bajo
  `ErrorDeDominio`, cada una con `reintentable: bool` y `detalle_proveedor`.
  Reemplaza al patrón de v1 de devolver un mensaje de texto formateado que un
  agente tendría que parsear para decidir qué hacer.
- **`mandato/modelo.py`** — `Mandato`, `Intencion`, `Consumo`, `Violacion`,
  `PropuestaDeMandato`. El corazón del proyecto; ver la sección 12.
- **`mandato/politica.py`** — `evaluar()`, que convierte una lista de
  violaciones en un `Dictamen` de tres posibles decisiones (`PERMITIR`,
  `CONFIRMAR`, `BLOQUEAR`). Ver la sección 12.
- **`catalogo/modelo.py`** — `Comercio`, `Producto`, `Carrito`, `ItemCarrito`,
  `Disponibilidad`. Incluye `Carrito.hash_canonico`: el hash SHA-256 de los
  ítems (no solo el total), que es lo que hace valer el "Cart Mandate" de AP2
  — impide que un carrito se sustituya por otro del mismo monto después de
  firmado.
- **`pago/modelo.py`** — `Ambiente` (sandbox/producción), `Proveedor`
  (wompi/simulada), `MedioDePagoRef`, `OrdenDeCobro`, `ResultadoCobro`,
  `EstadoCobro`.
- **`pago/topes.py`** — `TopesDuros`: 20.000 COP por transacción, 100.000 COP
  por día, constantes en código a propósito. Nunca se apagan ni dependen del
  mandato.

---

## 5. `puertos/` — las interfaces

Cinco interfaces, todas `typing.Protocol` (no hace falta que un adaptador
herede de nada):

| Puerto | Qué abstrae |
|---|---|
| `pasarela.py` → `PasarelaDePagos`, `SelectorDePasarela` | `PasarelaDePagos`: enrolar, cobrar, consultar, revocar, y traducir webhooks — ningún método bloquea esperando un estado final. `SelectorDePasarela.para(comercio_id)`: multi-comercio — resuelve la pasarela (con sus propias credenciales) que corresponde a cada comercio; implementada por `RegistroDePasarelas` (`adaptadores/pasarelas/registro.py`). |
| `repositorios.py` → `LibroDeConsumo`, `RepositorioMandatos`, `RepositorioMedios`, `RepositorioCarritos`, `RepositorioPropuestas`, `RegistroDeEstados` | Persistencia de cada tipo de dato. `LibroDeConsumo` es el más importante: reserva el cupo *antes* de cobrar y lo confirma o libera *después* — una escritura condicional atómica, no un "leer, sumar, escribir" que se rompe bajo concurrencia. `RepositorioMedios` guarda, además del medio de pago, con qué `comercio_id` quedó vinculado (`vinculado_con`) — multi-comercio, ver sección 18.5. |
| `catalogo.py` → `RepositorioCatalogo` | Tres métodos separados (`buscar_comercios`, `buscar_productos`, `ver_producto`) en vez de uno solo — refleja cómo navega el agente: primero elige comercio, después busca adentro. |
| `modelo_lenguaje.py` → `ModeloDeLenguaje` | `generar(sistema, instruccion)` para tareas simples (generar catálogo) y `responder(mensajes, herramientas)` para el agente conversacional con tool-calling real. |
| `firma.py` → `Firmante` | Firmar y verificar son interfaces separadas a propósito: verificar solo necesita la llave pública (que ya viaja dentro del mandato); firmar necesita la privada, y solo `EmitirMandato` la usa. |
| `sistema.py` → `Reloj`, `GeneradorIds`, `Bitacora` | El tiempo y los identificadores como parámetros inyectables, no llamadas directas a `datetime.now()`/`uuid4()` — así una prueba puede fijar el reloj en vez de tener que fabricar vencimientos con trucos. `Bitacora` es auditoría de solo escritura, no logging: lo que registra es evidencia del experimento. |

---

## 6. `aplicacion/` — los casos de uso

| Caso de uso | Qué hace |
|---|---|
| `EjecutarIntencion` | El corazón del sistema. Ver la sección 11 para el flujo completo. Expone `__call__` (primer intento) y `retomar` (resuelve una intención que quedó en `CONFIRMAR`). |
| `EmitirMandato` | Donde firma el humano. Recibe `propuesta_id` (no el objeto), busca la propuesta y el carrito por su cuenta contra los repositorios, resuelve el medio de pago vinculado a ESE comercio (`RepositorioMedios.vinculado_con`, multi-comercio) y firma con el `Firmante` real. El agente nunca llama a este caso de uso: no está en su catálogo de herramientas y no tiene acceso a un `Firmante`. |
| `EnrolarMedio` / `RevocarMedio` | Fase A: autorizar y desautorizar un medio de pago. Actos exclusivos del titular. |
| `NavegarCatalogo` | Las tres búsquedas del catálogo, más `armar_carrito` — que es donde vive la única regla real: un carrito no puede mezclar productos de más de un comercio, y un producto agotado nunca puede entrar a un carrito. También persiste la `PropuestaDeMandato` resultante para que otro proceso (la firma) pueda encontrarla después. |
| `ConciliarEvento` | Traduce un webhook ya verificado en "confirmar esta reserva" o "liberarla". Nunca levanta una excepción: cada desenlace (incluido "no me corresponde") es un resultado normal, para que el receptor HTTP siempre pueda responder 200. |
| `ConsultarEstado` | Lee `RegistroDeEstados` — lo que usa la herramienta `consultar_estado` del agente para no responder de memoria un estado que pudo cambiar en otro proceso. |
| `GenerarCatalogoSemilla` | Genera un comercio simulado (con productos) llamando a un `ModeloDeLenguaje`. Nunca acepta una respuesta a medias: si DeepSeek devuelve algo con forma inválida, se descarta entera. |

---

## 7. `adaptadores/` — las implementaciones reales

### Pasarelas de pago (`adaptadores/pasarelas/`)

- **`wompi/`** — `ClienteWompi` (HTTP puro, sin lógica de negocio) +
  `AdaptadorWompi` (traduce entre los tipos del dominio y la API real de
  Wompi). Mueve dinero real. Nunca bloquea esperando un estado final: `cobrar`
  devuelve lo que Wompi contesta al crear la transacción (típicamente
  `PENDING`), y el desenlace llega por webhook. Multi-comercio: cada comercio
  real tiene su propio `AdaptadorWompi`, con sus propias credenciales (leídas
  de `agora_datos/secretos/comercios_wompi.json`, `AGORA_WOMPI_COMERCIOS`) —
  `registro.py` (`RegistroDePasarelas`) resuelve cuál usar para cada
  `comercio_id`.
- **`simulada/`** — `AdaptadorSimulado`, con un `GuionSimulado` inyectable.
  **No es un mock de pruebas**: es un adaptador de producción para el modo
  demo, capaz de reproducir los cuatro desenlaces que también da Wompi real
  (aprobado, declinado, declinado por antifraude, pendiente). La heurística
  por defecto usa el correo del pagador como "marcador": un correo en un
  dominio reservado por la RFC 2606 (`example.com` y similares) o que
  contenga "fraude" dispara el rechazo por antifraude — reproduciendo a
  voluntad el hallazgo real documentado en `docs/decline-afe.md`.

### Persistencia (`adaptadores/persistencia/`)

- **`memoria/`** — para pruebas y demos rápidas. Se pierde al reiniciar el
  proceso.
- **`sqlite/`** — con WAL, `busy_timeout` y transacciones manuales
  (`BEGIN IMMEDIATE`). Es la que sobrevive entre procesos: necesaria en
  cuanto "armar el carrito" (el chat) y "firmar" (`entradas/cli/firmar`) o
  "retomar" corren en terminales o peticiones HTTP distintas — que es
  siempre el caso, porque firmar y confirmar nunca son herramientas del
  agente. `composicion/configuracion.py` **prohíbe** arrancar con
  `AGORA_PASARELA=wompi` + `AGORA_AMBIENTE=produccion` + persistencia en
  memoria: un consumo que se pierde al reiniciar el proceso permitiría
  reusar un mandato que ya debería estar agotado.

### Modelo de lenguaje (`adaptadores/llm/deepseek/`)

`AdaptadorDeepSeek`, sobre el SDK `openai` apuntado a la API de DeepSeek (es
compatible con ChatCompletions). Implementa tanto `generar()` (para fabricar
el catálogo) como `responder()` (tool-calling real, para el chat).

### Catálogo (`adaptadores/catalogo/semilla/`)

`RepositorioCatalogoSemilla` lee `datos/catalogo.json` sin red — el catálogo
que ve el agente en cada corrida es estático, fabricado de antemano con
`scripts/generar_catalogo_semilla.py`. Al momento de este documento contiene 2
comercios (Dulcería La Golosina, Papelería El Lápiz Feliz) y 24 productos,
generados con DeepSeek — regenerado el 1 de septiembre de 2026, más angosto
que el catálogo de 5 comercios de las etapas anteriores, para tener dos
comercios reales de Wompi con los que estudiar multi-comercio.

### Sistema (`adaptadores/sistema/`)

Reloj real, generador de ids con `uuid4`, `BitacoraJsonl` (auditoría a
archivo), y `VerificadorEd25519`/`FirmanteEd25519` (criptografía real —
`dominio/` nunca importa `cryptography` directamente). `cargar_o_generar_firmante`
lee el par de llaves del titular desde disco o lo genera la primera vez, sin
cifrar — mismo alcance de PoC que las credenciales de Wompi.

---

## 8. `agente/` — la frontera dura

Este es el paquete que hace que la premisa del proyecto sea verificable y no
solo una promesa.

- **`herramientas.py`** define exactamente seis herramientas que el modelo de
  lenguaje puede invocar: `buscar_comercios`, `buscar_productos`,
  `ver_producto`, `armar_carrito`, `pagar`, `consultar_estado`. Cualquier
  herramienta fuera de esa lista, o cuyo nombre contenga una palabra de la
  lista `PROHIBIDAS` (`firmar`, `enrolar`, `revocar`, `medio_de_pago`,
  `payment_source`, `llave`, `secreto`, `credencial`), hace que
  `validar_catalogo()` levante una excepción **al arrancar el proceso**, no
  en una prueba lejana.
- `armar_carrito` devuelve una `PropuestaDeMandato` **sin firmar**. `pagar` sí
  está en la lista, deliberadamente: la PoC no busca demostrar que el agente
  no actúa, sino que actúa solo dentro de un límite que otra persona firmó.
- **`politica.py`** — el system prompt (en español, le explica al modelo qué
  puede y no puede hacer, y le exige pasar los comandos de firma/confirmación
  *tal cual*, sin resumirlos) y `MAX_TURNOS_POR_CONVERSACION = 20` — un techo
  para que un modelo que se traba pidiendo herramientas en círculo no consuma
  cupo de API sin límite.
- **`conversacion.py`** — el loop de turnos: agrega el mensaje del usuario,
  llama al modelo, ejecuta las herramientas que pida, repite hasta que
  conteste con texto o se agote el límite de turnos. Sin async ni streaming
  a propósito — un turno de chat es secuencial por naturaleza.

`composicion/agente.py` es el único módulo que conoce tanto `aplicacion/`
como `agente/`: arma las seis funciones reales (cerradas sobre los casos de
uso) que `agente/herramientas.py` convierte en `Herramienta`. `agente/` en sí
mismo nunca importa `aplicacion/`.

---

## 9. `entradas/` — los puntos de entrada

### CLI (`entradas/cli/`)

`python -m agora.entradas.cli <comando>`:

| Comando | Qué hace |
|---|---|
| `enrolar` | Fase A: autoriza un medio de pago por push, vinculado a un `--comercio` puntual (obligatorio desde el soporte multi-comercio). |
| `fuentes` | Lista los medios de pago vivos de un titular. |
| `revocar` | Apaga un medio de pago. |
| `comercios` / `productos` / `producto` | Navegar el catálogo simulado. |
| `emitir` | Arma un carrito y firma el mandato en un solo paso (para cuando quien opera la CLI ya es el humano). |
| `firmar` | Firma una propuesta que armó **otro proceso** (típicamente, el agente en una charla de `chat`). |
| `pagar` | Ejecuta el cobro de un carrito contra un mandato ya firmado. |
| `retomar` | Resuelve una intención que quedó "esperando confirmación humana". |
| `estado` | Consulta el estado de una intención. |
| `mandatos` | Lista los mandatos emitidos y su consumo. |
| `chat` | Conversación con el agente (exige `DEEPSEEK_API_KEY`). |

### API web (`entradas/api/`) — etapas 7, 8 y 9

Une en un solo proceso lo que antes exigía dos terminales. `app.py` es una
factoría pura (`crear_app(agente, contenedor)`); `sesiones.py`
(`AlmacenDeSesiones`) mantiene una conversación en memoria por pestaña de
navegador más una cola de eventos.

| Ruta | Qué hace |
|---|---|
| `GET /` | Sirve el frontend de una sola página (`estatico/chat.html`). |
| `GET /salud` | Healthcheck. |
| `POST /sesiones` | Crea una sesión de chat nueva. |
| `POST /sesiones/{id}/mensajes` | Envía un mensaje al agente y recibe su respuesta. |
| `GET /sesiones/{id}/eventos` | Server-Sent Events: avisa al frontend cuándo mostrar el recuadro de firma o de confirmación. El SSE solo **dispara** el recuadro; la resolución viaja por la respuesta HTTP directa de las dos rutas siguientes. |
| `POST /propuestas/{id}/firmar` | La persona firma desde el recuadro emergente — llama exactamente al mismo caso de uso que el comando `firmar` de la CLI. |
| `POST /intenciones/{id}/retomar` | La persona aprueba o rechaza una confirmación pendiente — mismo caso de uso que `retomar`. |
| `POST /medios/enrolar/iniciar` | Etapa 8. Fase A por HTTP, paso 1: crea el token y dispara el push (Wompi) o lo aprueba de inmediato (simulada). Nunca bloquea. |
| `GET /medios/enrolar/{token}/estado` | Etapa 8. Fase A por HTTP, paso 2: el navegador sondea este endpoint a su propio ritmo hasta ver un estado final. Tampoco bloquea. |
| `POST /medios/enrolar/confirmar` | Etapa 8. Fase A por HTTP, paso 3: vuelve a consultar el estado del token **en el servidor** (nunca confía en lo que el navegador dice haber visto) y recién ahí guarda el medio. |
| `GET /medios?titular_id=...` | Etapa 8. Lista los medios de pago vivos de un titular, en el ambiente que ya tiene configurado el proceso (`contenedor.config.ambiente`) — mismo criterio que `entradas/cli/__main__.py:cmd_fuentes`, sin selector de ambiente en la petición. |

El agente nunca tiene una herramienta que alcance ninguna de estas rutas: las
dispara el navegador cuando la persona interactúa con la página (botones de
firma/confirmación, o el modal "Medios de pago"), nunca el modelo de
lenguaje.

**Por qué tres pasos y no uno solo para enrolar.** `puertos/pasarela.py`
exige que "ningún método bloquea esperando un estado final" — y contra Wompi
real, el titular puede tardar hasta `ESPERA_PUSH_SEG` (300s, ver
`aplicacion/enrolar_medio.py`) en aceptar el push de Nequi. La CLI puede
darse el lujo de bloquear un proceso de terminal sondeando ese tiempo
(`EnrolarMedio`); una petición HTTP no debería quedar colgada 5 minutos. Por
eso `aplicacion/enrolar_medio.py` se descompuso en tres clases de una sola
responsabilidad — `IniciarEnrolamiento`, `ConsultarEnrolamiento`,
`ConfirmarEnrolamiento` — que `EnrolarMedio` sigue componiendo para el
sondeo bloqueante de la CLI, y que las tres rutas de arriba exponen sueltas
para que sea el navegador (`estatico/chat.html`) quien decida el ritmo del
sondeo (cada 3 segundos, con el mismo límite de 5 minutos del lado del
cliente). El botón "Medios de pago" del chat reutiliza el mismo campo
`titular_id` que ya persiste en `localStorage` para el resto de la página —
no se inventó un concepto de sesión nuevo para esto.

### Webhook (`entradas/webhooks/wompi.py`)

Receptor HTTP del webhook de Wompi (`POST
/pagos/wompi/transacciones/{comercio_id}` — multi-comercio: la ruta trae el
`comercio_id` para saber con qué `events_secret` validar el
`X-Event-Checksum` del evento, ya que cada comercio real de Wompi tiene el
suyo). Siempre responde 200 — un checksum inválido o un evento que no pertenece a
esta app no es un fallo del receptor, y devolver otra cosa solo le daría a un
atacante una forma barata de hacer reintentar a Wompi sin límite. **Corre en
un proceso aparte** (`scripts/servir_webhook_wompi.py`, puerto 8001 por
defecto) del que sirve el chat (`scripts/servir_api.py`, puerto 8002) — dos
composition roots deliberadamente independientes. Contra Wompi real, este
proceso tiene que estar corriendo y expuesto públicamente (`ngrok`/
`cloudflared`), con esa URL — un segmento de ruta por comercio, un solo
túnel — cargada en el dashboard de Wompi de CADA comercio (Desarrolladores
→ Eventos) para que un cobro alguna vez salga de `PENDING`.

### Sondeo de pagos pendientes (`entradas/api/sondeo_pagos.py`) — etapa 9

**El problema que resuelve.** `aplicacion/ejecutar_intencion.py:_cobrar`
nunca bloquea esperando el desenlace de un cobro real: `pagar()` (herramienta
del agente) y `POST /intenciones/{id}/retomar` pueden devolver `PENDING` de
inmediato si Wompi liquida de forma asíncrona (típico contra Nequi). El
desenlace final lo asienta `aplicacion/conciliar_evento.py`, llamado **desde
el otro proceso** (el webhook, arriba). Sin nada más, la sesión de chat
nunca se entera de que el webhook ya resolvió algo: el agente le dijo a la
persona "quedó pendiente" y ahí se queda, hasta que alguien vuelva a
escribirle pidiendo que consulte de nuevo — el síntoma real que motivó esta
etapa (una compra por Nequi que salió aprobada del lado del banco, con el
webhook ya corriendo y confirmando, pero que el chat seguía mostrando como
pendiente).

**Cómo lo resuelve.** `ConsultarEstado` ya lee el mismo sqlite que
`ConciliarEvento` escribe — el estado SÍ está compartido entre los dos
procesos, solo que nadie del lado del chat volvía a preguntar.
`SondeoDePagosPendientes` corre en un hilo de fondo **dentro del proceso del
chat** (`scripts/servir_api.py`, arrancado ahí y no en la factoría pura
`crear_app` para no dejar hilos reales corriendo en cada prueba de
`test_api_app.py`), sondea cada `intervalo_seg` (5s por defecto) las
intenciones que `AlmacenDeSesiones.registrar_pendiente` marcó como en
`PENDING`, y en cuanto una llega a un estado final llama a
`AlmacenDeSesiones.resolver_pendiente`, que:

1. Le avisa a la conversación dueña (`continuar`, el mismo mecanismo que ya
   usan `/propuestas/{id}/firmar` y `/intenciones/{id}/retomar` después de
   que la persona resuelve un popup) para que el agente confirme el estado
   con `consultar_estado` y le conteste a la persona.
2. Encola un evento SSE nuevo, `mensaje_agente`, que `chat.html` muestra
   como una burbuja de chat más — sin que la persona tenga que preguntar ni
   recargar la página.

`AlmacenDeSesiones` registra la intención pendiente en dos lugares: dentro
de `_escanear_eventos`, si el resultado de la herramienta `pagar` ya trae
`motivo == "PENDING"` (cuando el cobro fue directo, sin pasar por
`esperando_confirmacion_humana`); y en la ruta `/intenciones/{id}/retomar`
de `app.py`, si `recibo.motivo == "PENDING"` después de que la persona
confirmó desde el popup — el camino que de hecho tomó la corrida real que
expuso este hueco.

**Por qué sondeo y no una notificación directa del webhook.** Una llamada
HTTP interna del proceso del webhook hacia el de la API reaccionaría al
instante, pero acoplaría dos composition roots que hoy son independientes a
propósito, y exigiría persistir el mapeo `intencion_id -> sesión_id` en
sqlite para que sobreviva un reinicio. El sondeo es la opción más simple
dado que el estado ya está compartido: alcanza con volver a preguntar. El
costo es la demora del intervalo (hasta 5 segundos), aceptable para esta
PoC. Limitación conocida: el registro de "qué intención pertenece a qué
sesión" vive en memoria del proceso del chat, igual que la `Conversacion`
misma — un reinicio de `servir_api.py` en medio de un cobro pendiente pierde
el seguimiento (el estado real sigue a salvo en sqlite, solo que nadie
vuelve a avisarle a esa sesión puntual).

---

## 10. `composicion/` — el composition root

- **`configuracion.py`** — el único módulo de `agora/` autorizado a leer
  variables de entorno (`leer_configuracion`). Valida combinaciones inválidas
  al construir `ConfiguracionAgora` (por ejemplo, Wompi + producción exige
  SQLite). Ver la tabla completa de variables en la sección 17.
- **`contenedor.py`** — `construir(config)` arma un único objeto `Contenedor`
  con todos los casos de uso y adaptadores ya conectados, eligiendo entre
  Wompi/simulada y memoria/SQLite según la configuración. Es lo único que
  `entradas/` recibe ya armado.
- **`agente.py`** — el puente entre `aplicacion/` y `agente/`: arma las seis
  funciones que el agente puede invocar, cerradas sobre el `Contenedor` real.

Cada punto de entrada tiene su propio *composition root* específico fuera de
`agora/`: `scripts/servir_api.py` (API web, puerto 8002 por defecto),
`scripts/servir_webhook_wompi.py` (webhook, puerto 8001), y
`scripts/generar_catalogo_semilla.py` (utilidad de una sola corrida).

---

## 11. El flujo de compra, de punta a punta

```
1. El titular enrola su medio de pago     → EnrolarMedio → MedioDePagoRef
2. Chatea con el agente                   → Agente + ModeloDeLenguaje
3. El agente navega el catálogo           → NavegarCatalogo
4. El agente arma un carrito              → Carrito + PropuestaDeMandato (sin firmar)
5. La app le muestra la propuesta         → CLI ("firmar <id>") o el recuadro web
6. El titular firma                       → EmitirMandato → Mandato (ed25519)
7. El agente pide pagar                   → EjecutarIntencion
     7a. Topes duros                      → nunca se apagan
     7b. Reserva atómica del cupo diario  → si no cabe, nadie llama a la pasarela
     7c. Política de mandato → Dictamen   → PERMITIR / CONFIRMAR / BLOQUEAR
     7d. Cobro contra la pasarela         → devuelve PENDIENTE de inmediato
8. Wompi (o la simulada) manda el evento  → ConciliarEvento confirma o libera
9. El chat se entera                      → SSE dispara el recuadro; consultar_estado confirma
```

Multi-comercio (paso 6): antes de armar el `Mandato`, `EmitirMandato` resuelve
qué medio de pago del titular está vinculado con el comercio de la propuesta
(`RepositorioMedios.vinculado_con`) — no "el último medio vivo", que podría
pertenecer a otro comercio y que Wompi rechazaría al cobrar. Ver la sección
18.5 y `docs/flujo-propuesta-mandato.md`.

Si el paso 7c da `CONFIRMAR` (algo cabe dentro del mandato pero "huele raro" —
por ejemplo, agota el mandato de una sola vez, o es el último uso disponible),
la reserva del cupo **no se libera**: queda viva hasta que un humano decide
con `retomar` (CLI) o el recuadro de confirmación (web). Volver a evaluar en
ese momento repite todos los controles — un mandato que venció mientras se
esperaba la respuesta humana sigue bloqueando incluso si la persona aprueba.

---

## 12. El modelo de mandato, en detalle

### `PropuestaDeMandato` vs. `Mandato`

Son dos tipos de dato distintos a propósito — no una misma clase con campos
opcionales. `PropuestaDeMandato` (lo que arma el agente) no tiene firma, no
tiene llave pública, no tiene referencia al medio de pago y no tiene
`mandato_id`: ninguna función que espere un `Mandato` acepta una propuesta, y
eso falla al construir el objeto, no en una validación que alguien pudo
olvidar escribir. La frontera entre "proponer" y "autorizar" vive en el
sistema de tipos.

### Los controles verificados al momento de cobrar

`Mandato.violaciones_contra()` revisa, en este orden, contra la intención que
llega:

1. **Firma** (ed25519, contra la carga canónica del mandato)
2. **Mandato correcto** (la intención cita el `mandato_id` que dice citar)
3. **Vigencia** (no venció)
4. **Comercio autorizado** (coincide con el que firmó el mandato)
5. **Monto máximo por transacción** (no excede `monto_max`)
6. **Tope acumulado** (no excede `tope_total` sumado a lo ya consumido)
7. **Usos disponibles** (no superó `usos_max`)
8. **Categoría autorizada** (si el mandato restringe categorías)
9. **Integridad del carrito** (`carrito_hash`, si el mandato se firmó atado a
   un carrito concreto — el "Cart Mandate" de AP2)

Cualquier violación con `exigir_mandato=True` produce `Decision.BLOQUEAR`. Sin
violaciones pero con una "señal blanda" (gastar casi todo el mandato de una
vez, pegar contra el tope por transacción, o ser el último uso disponible),
la decisión es `Decision.CONFIRMAR`: no hay nada roto, pero merece que un
humano lo mire antes de cobrar. Sin violaciones ni señales, `PERMITIR`.

Con `exigir_mandato=False` (el brazo sin control del experimento) las
violaciones se registran igual, pero no bloquean — es lo que permitió medir
que Wompi aprobó un cobro de 15.000 COP contra un mandato que autorizaba
8.000.

### Lo que el mandato protege, y lo que no

Protege contra un comercio que cobra distinto de lo pactado y contra un
agente que intenta gastar de más o reutilizar una autorización agotada. **No**
protege contra un agente al que convencieron (por ejemplo, con una inyección
de prompt) de pedir *otra cosa dentro del mismo límite*: si la intención cabe,
el mandato la deja pasar, porque para eso se firmó. Ese caso lo debe atrapar
`Decision.CONFIRMAR` o un motor de riesgo aparte — no la firma.

---

## 13. Persistencia y consistencia

| | Memoria | SQLite |
|---|---|---|
| Sobrevive un reinicio | No | Sí |
| Sobrevive entre procesos/terminales distintas | No | Sí |
| Uso recomendado | Pruebas, demos de un solo proceso | Cualquier cosa que involucre chat + firma en procesos separados, o Wompi real |
| Reserva de cupo diario | Atómica dentro del proceso (lock de Python) | Atómica entre conexiones independientes (`BEGIN IMMEDIATE`), probado con concurrencia real |

`composicion/configuracion.py` impide arrancar con `AGORA_PASARELA=wompi` +
`AGORA_AMBIENTE=produccion` + `AGORA_PERSISTENCIA=memoria`: esa combinación
dejaría que un mandato agotado "resucite" con solo reiniciar el proceso, algo
inaceptable con dinero real. No hay forma de saltarse esta regla con una
bandera — es un guardarraíl, no una preferencia.

---

## 14. `boveda/` (v1) — el sistema original, retirado

**Sección histórica.** Describe `boveda/` tal como existía antes de retirarse
del repositorio (ver sección 2 y `docs/limpieza-v1-boveda.md`) — sigue siendo,
hasta la fecha, el único código que efectivamente movió dinero real en
producción. Su estructura, tal como se preservó fuera de este checkout:

```
boveda/
├── cli.py           las dos fases desde la terminal
├── enrolamiento.py  Fase A: push de Nequi, fuente de pago, revocación
├── mandato.py       el modelo de mandato v1, firma ed25519, evaluación
├── nucleo.py        Fase B: ejecución contra Wompi, topes duros
└── eventos.py       receptor de webhooks (versión anterior a agora/entradas/webhooks/)
```

Y lo que no se versionaba, bajo `boveda/secretos/`: `firma.sk`/`firma.pk`
(llave del titular), `estado.json` (mandatos firmados y consumo),
`fuentes.json` (medios de pago vivos). `boveda/recibos.jsonl` **no era un log
de aplicación** — es la evidencia experimental (incluida la corrida de los
15.000 COP aprobados contra un mandato de 8.000), preservada intacta junto
con el resto de `boveda/` fuera de este repositorio.

---

## 15. `wompi_lab/` — congelado

`lab.py` (cobros de prueba sin abstracciones) ya fue reemplazado por los
adaptadores de `agora/`. `payouts.py` se conserva porque es el único código
del repositorio que sabe hacer dispersiones (payouts) por Bre-B — no corre en
ningún flujo actual, pero rehacerlo costaría tiempo si hiciera falta más
adelante.

---

## 16. Pruebas

- `tests/test_fronteras.py` — la prueba estructural más importante del
  repositorio: recorre el AST de cada archivo bajo `agora/` y falla si una
  capa importa algo que la tabla de la sección 3 prohíbe, o si una capa
  "pura" (`dominio/`, `puertos/`, `agente/`) importa una librería de
  infraestructura (`httpx`, `sqlite3`, `fastapi`, `os`).
- El resto de la suite cubre cada adaptador, cada caso de uso, el flujo
  completo por CLI (`test_cli.py`) y por HTTP (`test_api_app.py`), la
  concurrencia real del `LibroDeConsumo` en SQLite, y — desde el soporte
  multi-comercio — la vinculación medio↔comercio
  (`RepositorioMedios.vinculado_con`) y el enrutamiento por
  `SelectorDePasarela`. El número exacto de pruebas cambia seguido conforme
  crece la suite; confirmar en verde localmente con `python -m pytest tests/
  -q` en vez de fiarse de una cifra fija en este documento. Ver
  `docs/limpieza-v1-boveda.md` para el conteo de la última limpieza de código
  muerto de v1.
- Las dos pruebas que antes fallaban de forma preexistente
  (`test_cli.py::test_flujo_completo_enrolar_emitir_pagar_retomar` y
  `test_composicion.py::test_construir_encadena_navegar_emitir_pagar_y_consultar_de_punta_a_punta`,
  que esperaban ids de catálogo de ejemplo ya reemplazados por el catálogo
  real) se corrigieron: ahora descubren en tiempo de ejecución un producto
  válido del catálogo vigente en vez de asumir un id fijo. Ya no hay pruebas
  conocidas fallando.

---

## 17. Variables de entorno — referencia completa

Todas se cargan desde un `.env` en la raíz (no versionado). Plantilla
comentada completa en `docs/variables-de-entorno.md`.

| Variable | Quién la lee | Default | Efecto |
|---|---|---|---|
| `AGORA_AMBIENTE` | `agora/composicion/configuracion.py` | `sandbox` | `sandbox` \| `produccion` |
| `AGORA_PASARELA` | ídem | `simulada` | `simulada` \| `wompi` |
| `AGORA_PERSISTENCIA` | ídem | `memoria` | `memoria` \| `sqlite` |
| `AGORA_SQLITE_PATH` | ídem | `agora_datos/agora.db` | Solo se usa si `AGORA_PERSISTENCIA=sqlite` |
| `AGORA_BITACORA` | ídem | `agora_datos/recibos.jsonl` | Ruta del registro de auditoría de `agora/` |
| `AGORA_LLAVE_FIRMA_SK` / `AGORA_LLAVE_FIRMA_PK` | ídem | `agora_datos/secretos/firma.{sk,pk}` | Par ed25519 del titular; se genera solo si no existe |
| `AGORA_WOMPI_COMERCIOS` | `agora/composicion/configuracion.py`, `adaptadores/pasarelas/registro.py` | `agora_datos/secretos/comercios_wompi.json` | Multi-comercio: ruta al registro JSON con credenciales de Wompi por `comercio_id` (`public_key`, `private_key`, `integrity_secret`, `events_secret`) — reemplaza, para `agora/`, a las variables `WOMPI_*` sueltas de un solo comercio. Solo se usa si `AGORA_PASARELA=wompi`. |
| `WOMPI_PUBLIC_KEY` / `WOMPI_PRIVATE_KEY` / `WOMPI_INTEGRITY_SECRET` / `WOMPI_EVENTS_SECRET` | Nadie ya — histórico | — | Credenciales de Wompi de un solo comercio, como las leían `boveda/nucleo.py` y `boveda/eventos.py` (v1, retirado — ver `docs/limpieza-v1-boveda.md`). `agora/` nunca las leyó: desde el soporte multi-comercio usa `AGORA_WOMPI_COMERCIOS` en su lugar. Se documentan aquí solo por si aparecen en un `.env` heredado de v1. |
| `PAGADOR_EMAIL` / `PAGADOR_NOMBRE` / `PAGADOR_TELEFONO` / `PAGADOR_DOCUMENTO` / `PAGADOR_TIPO_DOC` | ambos sistemas | `demo@agora.local` en `agora/` (nunca un dominio reservado — ver hallazgo AFE) | Perfil que ve el motor antifraude de Wompi en cada cobro |
| `DEEPSEEK_API_KEY` | `agora/composicion/configuracion.py`, `scripts/generar_catalogo_semilla.py` | — (opcional) | Sin ella, el resto de `agora/` funciona igual; solo `chat` y `POST /sesiones` avisan que no hay agente disponible |
| `DEEPSEEK_MODELO` | ídem | `deepseek-chat` | Modelo de DeepSeek a usar |
| `AGORA_API_HOST` / `AGORA_API_PORT` | `scripts/servir_api.py` | `0.0.0.0` / `8002` | Host y puerto de la API web |
| `AGORA_WEBHOOK_HOST` / `AGORA_WEBHOOK_PORT` | `scripts/servir_webhook_wompi.py` | `0.0.0.0` / `8001` | Host y puerto del receptor de webhook |



---

## 18. Rieles de pago colombianos: por qué Wompi + Nequi

Resumen de `docs/informe-viabilidad-pagos-agenticos-co.md`: el riel elegido es
**Wompi en producción, con fuentes de pago Nequi**.
Alternativas descartadas: Bold (no documenta cobro recurrente), ePayco
(tokenización solo para tarjeta), Treli (envuelve Wompi por debajo, esconde lo
que la PoC quiere observar), el API directo de Bancolombia (sin ningún
primitivo de débito delegado en su catálogo público, y el Decreto 1297 de 2022
prohíbe automatizar el Botón Bancolombia), y Bre-B (irreversible — es el riel
que un atacante usaría para sacar el dinero, no uno para cobrar de forma
segura).

El hallazgo central de esa investigación: **ningún riel colombiano entrega,
por sí solo, la capa de mandato** que este proyecto construye encima. Un
`payment_source_id` de Wompi no tiene tope, ni vencimiento, ni ligadura a un
monto, producto o comercio — eso es exactamente lo que la bóveda agrega.

---

## 20. Estado y pendientes

Completo a la fecha de este documento:

- Arquitectura completa de `agora/` (dominio, puertos, aplicación,
  adaptadores, agente, composición).
- Multi-comercio: varios comercios reales de Wompi (con sus propias
  credenciales) conviviendo en el mismo proceso, con vinculación
  medio↔comercio en el enrolamiento y en la firma del mandato
  (`docs/viabilidad-multi-comercio-wompi.md`).
- Dos interfaces de usuario: CLI completa y una API web de una sola página
  con chat, firma y confirmación integradas.
- Enrolar un medio de pago y ver los medios enrolados de un titular desde la
  misma página web (modal "Medios de pago"), sin pasar por la CLI, para
  simulada y para Wompi (sandbox o producción, según `AGORA_AMBIENTE`) —
  etapa 8.
- Persistencia SQLite con reserva/confirmación atómica real, probada bajo
  concurrencia.
- Webhook vivo de Wompi (`entradas/webhooks/wompi.py` +
  `scripts/servir_webhook_wompi.py`), con el sondeo de fondo (`entradas/api/
  sondeo_pagos.py`, etapa 9) que le avisa al chat cuando ese webhook —
  corriendo en otro proceso — resuelve un cobro que había quedado `PENDING`,
  sin que la persona tenga que volver a preguntar.
- Catálogo simulado generado con DeepSeek y agente conversacional con
  frontera de herramientas verificada por prueba.

Pendiente o fuera de alcance a propósito:

- Un motor de riesgo real más allá de las heurísticas fijas de
  `_senales_blandas` en `dominio/mandato/politica.py`.
- Meter la correspondencia medio↔comercio dentro de la carga firmada del
  mandato (mandato v3) en vez de garantizarla solo procedimentalmente al
  firmar.

  - La correspondencia medio↔comercio no viaja dentro de la firma

    `agora/` soporta varios comercios reales de
    Wompi en el mismo proceso (`docs/viabilidad-multi-comercio-wompi.md`). Un
    `payment_source_id` de Wompi queda atado al comercio que lo creó, así que
    `EmitirMandato` resuelve el medio vinculado a ESE comercio
    (`RepositorioMedios.vinculado_con`) antes de firmar, y nunca firma con un
    medio de otro comercio.

    Lo que esa garantía **no** hace es viajar dentro de la carga firmada del
    mandato (`Mandato.canonico()`) ni volver a chequearse en `EjecutarIntencion`
    al cobrar — `violaciones_contra` no tiene un
    `medio_vinculado_a_otro_comercio` entre sus violaciones. Es una decisión
    consciente, documentada a propósito (ver `docs/flujo-propuesta-mandato.md`,
    sección 6, y `docs/viabilidad-multi-comercio-wompi.md`, sección "Amarre
    medio → comercio"): la alternativa era un mandato v3 con `comercio_id`
    dentro de `MedioDePagoRef`, más robusto pero con más superficie (exigiría
    conservar el verificador v2, igual que se conserva el de v1). Se eligió la
    opción liviana porque `EmitirMandato` es el único punto del sistema que
    construye un `Mandato` de verdad — un bug en otra parte que armara uno a
    mano con el medio equivocado no lo detectaría este chequeo.
