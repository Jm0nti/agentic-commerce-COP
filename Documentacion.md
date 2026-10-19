# Documentación técnica de agora

Complementa al [`README.md`](README.md) (qué es agora y cómo correrlo) con el
detalle de cada módulo, cómo se integran y qué queda pendiente. La forma
general y las decisiones están en [`docs/arquitectura.md`](docs/arquitectura.md).

**Convención de rutas.** agora está repartido en los módulos del scaffold de
Bancolombia, y cada uno tiene su código en `src/agora/`. Las rutas de este
documento son relativas a esa raíz del paquete: `model/mandato/modelo.py` es
`domain/model/src/agora/model/mandato/modelo.py`, `driven_adapters/pasarela_wompi/`
es `infrastructure/driven-adapters/pasarela-wompi/src/agora/driven_adapters/pasarela_wompi/`,
y así con cada módulo.

---

## 1. Propósito y principio rector

agora estudia qué pasa cuando un agente de IA compra en nombre de una persona,
con dinero real sobre un riel de pagos colombiano (Wompi + Nequi). La pregunta
no es si un agente *puede* pagar —puede— sino cuánto puede desviarse de lo
que la persona autorizó antes de que algo lo detenga.

Todo el diseño se deriva de una frase:

> **El agente propone. El humano firma. El motor de pagos ejecuta.**
> Ninguno de los tres puede hacer el trabajo de otro.

Está verificado, no solo documentado: `tests/arquitectura/test_fronteras.py`
falla el build si el agente llega a importar, aunque sea indirectamente, un
caso de uso, una pasarela de pagos o la llave de firma.

---

## 2. Estructura y regla de dependencia

| Módulo del scaffold | Paquete | Contenido |
|---|---|---|
| `domain/model` | `agora.model` | Entidades, objetos de valor y gateways (`typing.Protocol`). Solo biblioteca estándar. |
| `domain/usecase` | `agora.usecase` | Un caso de uso por carpeta (`<caso>/<caso>_use_case.py`, clase `…UseCase`) y el agente (`usecase/agente/`). |
| `infrastructure/driven-adapters/*` | `agora.driven_adapters.*` | Implementaciones de los gateways, un módulo por tecnología. |
| `infrastructure/entry-points/*` | `agora.entry_points.*` | API web, receptor del webhook y CLI. |
| `applications/app-service` | `agora`, `agora.app_service` | El arranque (`python -m agora`) y el armado (`config/`). |

| Módulo | Puede importar | Nunca importa |
|---|---|---|
| `model` | `model`, biblioteca estándar | todo lo demás |
| `usecase` | `model` | adaptadores, entry points, app-service, el agente |
| `usecase/agente` | `model`, el propio agente | **cualquier otro caso de uso**, adaptadores, gateways de pago, firma, repositorios o autenticación, `importlib` |
| `driven_adapters/*` | `model`, su propia librería | casos de uso, agente, otros adaptadores, entry points, app-service |
| `entry_points/*` | `usecase`, `model` | adaptadores, otros entry points, app-service, atributos de repositorio del contenedor |
| `app_service` | todo | — |

`tests/arquitectura/test_fronteras.py` verifica cada fila leyendo el árbol de
sintaxis (AST) de todos los archivos, y además:

- confina cada librería a su módulo (`httpx` → `pasarela-wompi`, `openai` →
  `llm-deepseek` y `embeddings-openai`, `langgraph` → `orquestacion-langgraph`,
  `langchain_*` → `recuperacion-langchain`, `numpy` →
  `busqueda-semantica-memoria`, `cryptography` → `firma-ed25519`, `sqlite3` →
  `persistencia-sqlite`, `fastapi` → `api-rest` y `webhook-wompi`, `pydantic` →
  `api-rest`, `uvicorn` y `dotenv` → app-service);
- exige la convención de carpetas de los casos de uso;
- prohíbe `__import__` dinámico en el agente;
- y tiene un detector probado para cada regla, sobre un árbol de mentira: una
  prueba de fronteras que nunca falla podría no estar mirando nada.

---

## 3. `domain/model` — las reglas, sin infraestructura

### `commons/`

- **`dinero.py`** — `Dinero`: centavos + moneda, inmutable. Nunca se mezclan
  pesos con centavos ni dos monedas.
- **`identidad.py`** — identificadores con tipo (`MandatoId`, `IntencionId`,
  `ComercioId`…): `str` en ejecución, distintos para el verificador de tipos;
  cada uno con su prefijo (`mnd_`, `int_`, `com_`…).
- **`errores.py`** — jerarquía bajo `ErrorDeDominio`. Cada error lleva
  `reintentable` y `detalle_proveedor`, y se serializa con su nombre de clase:
  es lo que lee el agente para decidir si reintentar o pedir otra cosa.
- **`gateways/sistema.py`** — `Reloj`, `GeneradorIds`, `Bitacora`. El tiempo y
  los ids son inyectables, así una prueba fija el reloj en vez de fabricar
  vencimientos. `Bitacora` es auditoría de solo escritura.

### `mandato/`

- **`modelo.py`** — `Mandato`, `PropuestaDeMandato`, `Intencion`, `Consumo`,
  `Violacion`. Ver la sección 10.
- **`politica.py`** — `evaluar()`: violaciones → `Dictamen` con tres
  decisiones (`PERMITIR`, `CONFIRMAR`, `BLOQUEAR`).
- **`gateways/repositorios.py`** — `RepositorioMandatos`,
  `RepositorioPropuestas` y `LibroDeConsumo` (reserva → confirma o libera; con
  `Reserva` y `TopeAgotado`).
- **`gateways/firma.py`** — `Firmante`, `SelectorDeFirmante`,
  `GeneradorDeLlaves`, `Verificador`. Firmar y verificar van separados:
  verificar solo necesita la llave pública, que viaja dentro del mandato.

### `pago/`

- **`modelo.py`** — `Ambiente` (sandbox/produccion), `Proveedor`
  (wompi/simulada), `MedioDePagoRef`, `OrdenDeCobro`, `ResultadoCobro`,
  `EstadoCobro`.
- **`topes.py`** — `TopesDuros`: 20.000 COP por transacción, 100.000 COP por
  día. Constantes a propósito; nunca dependen del mandato.
- **`gateways/pasarela.py`** — `PasarelaDePagos` (enrolar, cobrar, consultar,
  revocar, validar y traducir webhooks; ningún método bloquea) y
  `SelectorDePasarela.para(comercio_id)`.
- **`gateways/repositorios.py`** — `RepositorioMedios` (con el `comercio_id`
  al que quedó vinculado cada medio: `vinculado_con`) y `RegistroDeEstados`
  (el estado de cada intención, compartido entre procesos).

### `catalogo/`

- **`modelo.py`** — `Comercio`, `Producto`, `Carrito`, `ItemCarrito`,
  `Disponibilidad`. `Carrito.hash_canonico` es el SHA-256 de los ítems (no
  solo del total): hace valer el *Cart Mandate* de AP2 e impide cambiar un
  carrito por otro del mismo monto después de firmado.
- **`gateways/catalogo.py`** — `RepositorioCatalogo`, con tres métodos
  (`buscar_comercios`, `buscar_productos`, `ver_producto`), como navega el
  agente.
- **`gateways/busqueda_productos.py`** — `BuscadorSemanticoDeProductos` y
  `FiltrosDeProducto` (disponibilidad, rango de precio).
- **`gateways/repositorios.py`** — `RepositorioCarritos`.

### `usuario/`

- **`modelo.py`** — `Usuario` (titular, nombre de usuario, hash de contraseña).
- **`gateways/autenticacion.py`** — `HasherDeContrasenas`.
- **`gateways/repositorios.py`** — `RepositorioUsuarios` y `RepositorioLlaves`
  (la llave ed25519 de cada titular, separada del usuario).

### `agente/`

- **`intencion.py`** — `TipoDeIntencion`, `ClasificacionDeIntencion`,
  `ClasificadorDeIntencion`.
- **`contexto.py`** — `ContextoInyectado`, `ProveedorDeContexto`.
- **`gateways/`** — `modelo_lenguaje.py` (`ModeloDeLenguaje`, `Mensaje`,
  `LlamadaHerramienta`), `orquestacion.py` (`DefinicionDeGrafo`,
  `CompiladorDeGrafos`, `PausaRequerida`) y `recuperacion.py`
  (`ProveedorDeEmbeddings`, `BuscadorDocumental`).

---

## 4. `domain/usecase` — los casos de uso

| Caso de uso | Qué hace |
|---|---|
| `EjecutarIntencionUseCase` | **El motor de pagos.** Topes duros → reserva atómica → política de mandato → cobro (sección 9). `__call__` es el primer intento; `retomar` resuelve una intención que quedó en `CONFIRMAR`. |
| `PagarCarritoUseCase` | Cobra un carrito guardado contra un mandato: arma la `Intencion` con comercio, monto y `carrito_hash` leídos del carrito, nunca de quien llama. Lo usan el agente, la CLI y la API. |
| `EmitirMandatoUseCase` | Donde firma el humano. Recibe `propuesta_id`, busca la propuesta y el carrito por su cuenta, resuelve el medio vinculado a ese comercio y firma con la llave del titular. El agente nunca lo alcanza. |
| `RechazarPropuestaUseCase` | El humano rechaza la propuesta sin firmar: queda en la bitácora y la conversación se entera. |
| `IniciarEnrolamientoUseCase` · `ConsultarEnrolamientoUseCase` · `ConfirmarEnrolamientoUseCase` | Fase A en tres pasos que nunca bloquean (crear token y push; sondear; confirmar y guardar). |
| `EnrolarMedioUseCase` | Compone los tres pasos con un sondeo bloqueante, para la CLI. |
| `RevocarMedioUseCase` | El botón de pánico: apaga un medio de pago, previa verificación de que es del titular. |
| `NavegarCatalogoUseCase` | Las búsquedas del catálogo (en tres peldaños, ver sección 5), `armar_carrito` —un carrito no mezcla comercios ni admite productos agotados— y la lectura de carritos y propuestas. |
| `ConciliarEventoUseCase` | Traduce un webhook ya verificado en confirmar o liberar la reserva. Nunca levanta: cada desenlace es un resultado, para que el receptor siempre responda 200. |
| `ConsultarEstadoUseCase` | El estado de una intención (lo usa la herramienta `consultar_estado`). |
| `ListarMediosVivosUseCase` · `ListarMandatosUseCase` | Consultas para la API y la CLI, en el ambiente del proceso. |
| `RegistrarUsuarioUseCase` · `IniciarSesionUseCase` | Multi-usuario: crear un usuario (con su par de llaves) e iniciar sesión. |
| `GenerarCatalogoSemillaUseCase` | Genera un comercio simulado con un `ModeloDeLenguaje`. Una respuesta con forma inválida se descarta entera. |

---

## 5. `domain/usecase/agente` — la frontera dura

El módulo que hace verificable la premisa del proyecto. Documentación
completa, con diagramas, en
[`docs/arquitectura-agentes/`](docs/arquitectura-agentes/).

- **`herramientas.py`** — exactamente seis herramientas: `buscar_comercios`,
  `buscar_productos`, `ver_producto`, `armar_carrito`, `pagar`,
  `consultar_estado`. Cualquier herramienta fuera de esa lista, o con un nombre
  de `PROHIBIDAS` (`firmar`, `enrolar`, `revocar`, `medio_de_pago`,
  `payment_source`, `llave`, `secreto`, `credencial`, `contrasena`,
  `password`, `sesion`), detiene el proceso **al arrancar**. También fija qué
  herramientas ve cada nodo del grafo.
- **`clasificacion/`** — decide la intención de cada mensaje: reglas primero
  (gratis), modelo después, en cadena (`AGORA_CLASIFICADOR`).
- **`grafo.py`, `agentes.py`, `nodos.py`** — el turno como grafo: un
  orquestador enruta a uno de siete agentes especializados (catálogo,
  carrito y pago, estado, soporte, medios de pago, fuera de alcance, respaldo),
  cada uno con solo las herramientas de su dominio. Un agente que recibe la
  ruta de otro la rechaza; una herramienta alucinada se rechaza al ejecutar.
- **`pausa.py`** — `PausaDelTurno` y `DecisionHumana`: si el turno dejó una
  propuesta sin firmar o un cobro sin confirmar, el grafo se detiene en
  `espera_humana`, y se reanuda con la decisión tipada de la persona.
- **`contexto_documental.py`** — en turnos de soporte inyecta fragmentos de
  `docs/soporte/` (RAG), con cada cifra reemplazada por `[cifra omitida]`:
  montos y topes salen siempre de los objetos reales, nunca de un documento.
- **`conversacion.py`** — el loop de turnos, sin async a propósito.
- **`politica.py`** — el system prompt y `MAX_TURNOS_POR_CONVERSACION = 20`.
- **`traza.py`** — un evento por turno en `agora_datos/trazas.jsonl`: qué
  herramientas se ofrecieron, cuáles se llamaron y con qué resultado
  (`python -m agora cli trazas`).

**Búsqueda en el catálogo, en tres peldaños** (`NavegarCatalogoUseCase`):
1) coincidencia estructurada, auditable, que no puede inventar un producto;
2) reglas duras (`FiltrosDeProducto`); 3) solo si los dos primeros no
encontraron nada y hay `OPENAI_API_KEY`, un orden semántico por coseno que
solo reordena y recorta candidatos ya aprobados.

El agente nunca importa un caso de uso: `app_service/config/agente.py` arma las
seis funciones cerradas sobre los casos de uso reales y se las entrega.

---

## 6. `infrastructure/driven-adapters` — las implementaciones

| Módulo | Implementa | Notas |
|---|---|---|
| `pasarela-wompi` | `PasarelaDePagos` | `ClienteWompi` (HTTP puro) + `AdaptadorWompi`. Mueve dinero real. Valida el `X-Event-Checksum` de cada webhook con el `events_secret` del comercio. La referencia de cobro es `agora-<intencion_id>`. |
| `pasarela-simulada` | `PasarelaDePagos` | Reproduce aprobado, declinado, declinado por antifraude y pendiente, a voluntad (`GuionSimulado`). Un correo en un dominio reservado (`example.com`…) o con "fraude" declina por antifraude. |
| `selector-pasarelas` | `SelectorDePasarela` | `RegistroDePasarelas`: un `AdaptadorWompi` por comercio, o una simulada para todos. |
| `persistencia-sqlite` | todos los repositorios | WAL, `busy_timeout`, `BEGIN IMMEDIATE`. La reserva de consumo es atómica entre conexiones independientes. |
| `persistencia-memoria` | todos los repositorios | Pruebas y demos de un solo proceso. |
| `catalogo-semilla` | `RepositorioCatalogo` | Lee `datos/catalogo.json` (2 comercios, 24 productos, generado con DeepSeek). |
| `llm-deepseek` | `ModeloDeLenguaje` | SDK `openai` contra la API de DeepSeek (compatible con ChatCompletions); `generar()` y `responder()` con tool-calling. |
| `embeddings-openai` | `ProveedorDeEmbeddings` | `text-embedding-3-small` por defecto. |
| `recuperacion-langchain` | `BuscadorDocumental` | Fragmenta `docs/soporte/` y busca en un índice en memoria. |
| `busqueda-semantica-memoria` | `BuscadorSemanticoDeProductos` | Coseno con numpy sobre los productos del catálogo; índice separado del documental. |
| `orquestacion-langgraph` | `CompiladorDeGrafos` | El único módulo que importa `langgraph`. |
| `firma-ed25519` | `Firmante`, `Verificador`, `GeneradorDeLlaves`, `SelectorDeFirmante` | `RegistroDeFirmantes` resuelve el firmante de cada titular desde `RepositorioLlaves`. |
| `hasher-pbkdf2` | `HasherDeContrasenas` | PBKDF2-SHA256; las iteraciones viajan dentro del hash. |
| `bitacora-jsonl` | `Bitacora` | Un `.jsonl` de solo agregar. |
| `sistema` | `Reloj`, `GeneradorIds` | Reloj del sistema y ids con `uuid4`. |

Ningún adaptador importa a otro (lo verifica `test_fronteras.py`).

---

## 7. `infrastructure/entry-points`

Los entry points reciben casos de uso ya armados y nunca tocan un
repositorio. La API recibe un `DependenciasDeLaApi` y la CLI un
`DependenciasDeLaCli` (Protocols con los casos de uso, el ambiente y poco
más); el `Contenedor` del app-service cumple ambos.

### `cli` — `python -m agora cli <comando>`

| Comando | Qué hace |
|---|---|
| `enrolar` | Fase A: autoriza un medio por push, vinculado a un `--comercio`. |
| `fuentes` | Medios de pago vivos de un titular. |
| `revocar` | Apaga un medio de pago. |
| `comercios` / `productos` / `producto` | Navegar el catálogo. |
| `emitir` | Arma un carrito y firma el mandato en un paso. |
| `firmar` | Firma una propuesta que armó otro proceso (el agente). |
| `pagar` | Cobra un carrito contra un mandato firmado. |
| `retomar` | Resuelve una intención que quedó esperando confirmación (`--rechazar` para rechazar). |
| `estado` | Estado de una intención. |
| `mandatos` | Mandatos emitidos y su consumo. |
| `chat` | Conversación con el agente (`--mostrar-intencion` muestra la clasificación de cada turno). |
| `trazas` | Lee la trazabilidad del agente (`--seguir`, `--ultimas N`, `--crudo`). |

### `api-rest` — `python -m agora api` (puerto 8002)

`app.py` es una factoría pura (`crear_app(agente, dependencias)`);
`sesiones.py` guarda una conversación en memoria por pestaña, con su cola de
eventos; `autenticacion.py` maneja la sesión web (cookie `agora_sesion`,
httponly, 12 horas). El `titular_id` sale siempre de la cookie, nunca del
cuerpo de la petición.

| Ruta | Qué hace |
|---|---|
| `GET /` · `GET /salud` | El frontend (`estatico/chat.html`) y el healthcheck. |
| `POST /auth/iniciar-sesion` · `POST /auth/cerrar-sesion` · `GET /auth/quien-soy` | Sesión web. No hay registro por HTTP: los usuarios se crean con `python -m agora crear-usuario`. |
| `POST /sesiones` · `POST /sesiones/{id}/mensajes` | Abrir una conversación con el agente y enviarle mensajes. |
| `GET /sesiones/{id}/eventos` | Server-Sent Events: avisan cuándo mostrar el popup de firma o de confirmación, y los mensajes del agente que llegan solos. |
| `POST /propuestas/{id}/firmar` · `POST /propuestas/{id}/rechazar` | La persona firma o rechaza la propuesta desde el popup; la conversación se reanuda con esa decisión. |
| `POST /intenciones/{id}/retomar` | La persona aprueba o rechaza un cobro que quedó en `CONFIRMAR`. |
| `POST /medios/enrolar/iniciar` · `GET /medios/enrolar/{token}/estado` · `POST /medios/enrolar/confirmar` | Fase A desde el navegador, en tres pasos que no bloquean: el navegador sondea a su ritmo, y al confirmar el servidor vuelve a consultar el estado del token por su cuenta. |
| `GET /medios` · `POST /medios/{id_externo}/revocar` | Medios vivos del titular y revocación. |

Ninguna de estas rutas es alcanzable por el agente: las dispara el navegador
cuando la persona interactúa.

**Sondeo de pagos pendientes** (`sondeo_pagos.py`). Contra Wompi, `pagar()` y
`retomar` suelen devolver `PENDING`; el desenlace lo asienta el webhook, en
otro proceso. `SondeoDePagosPendientes` corre en un hilo del proceso de la API,
consulta cada pocos segundos las intenciones pendientes y, cuando una llega a
un estado final, reanuda la conversación dueña y empuja la respuesta del
agente por SSE — sin que la persona tenga que volver a preguntar. El registro
"intención → sesión" vive en memoria: un reinicio de la API en medio de un
cobro pierde el aviso (no el estado, que sigue en SQLite).

### `webhook-wompi` — `python -m agora webhook` (puerto 8001)

`POST /pagos/wompi/transacciones/{comercio_id}`. La ruta trae el
`comercio_id` para validar el checksum con el `events_secret` de ese comercio.
Siempre responde 200: un checksum inválido o un evento ajeno no es un fallo
del receptor, y responder otra cosa le daría a un atacante una forma barata de
hacer reintentar a Wompi. Corre en un proceso aparte de la API y, contra Wompi
real, tiene que estar expuesto con un túnel (ngrok, cloudflared) y registrado
en el panel de Wompi de cada comercio.

---

## 8. `applications/app-service`

- **`main.py`** — el único arranque: `python -m agora <perfil>` con `api`,
  `webhook`, `cli`, `crear-usuario` y `generar-catalogo`. Cada perfil importa
  solo lo que necesita.
- **`config/configuracion.py`** — el único lugar que lee el entorno
  (`desde_el_entorno()`: el `.env` de la raíz y después `os.environ`).
  `leer_configuracion(entorno)` recibe el mapping por parámetro y valida
  combinaciones inválidas al construir `ConfiguracionAgora`: Wompi en
  producción exige SQLite, y el ambiente de cada credencial tiene que coincidir
  con su prefijo de llave.
- **`config/contenedor.py`** — `construir(config)` arma el `Contenedor`: todos
  los casos de uso y adaptadores, eligiendo Wompi o simulada y SQLite o
  memoria.
- **`config/agente.py`** — arma las seis herramientas sobre los casos de uso
  reales, el clasificador (`AGORA_CLASIFICADOR`), el contexto documental y el
  grafo (`AGORA_ORQUESTACION`).
- **`servir_api.py`**, **`servir_webhook_wompi.py`**, **`crear_usuario.py`**,
  **`generar_catalogo_semilla.py`** — los perfiles.
- **`agora/__init__.py`** — encuentra los módulos del scaffold
  (`domain/*`, `infrastructure/*/*`, `applications/*`) y los suma a
  `agora.__path__`. Funciona desde el repositorio o con `pip install -e .`, no
  desde un wheel.

---

## 9. El flujo de compra, de punta a punta

```
1. El titular inicia sesión              → IniciarSesionUseCase
2. Enrola su medio para un comercio      → Iniciar/Consultar/ConfirmarEnrolamiento → MedioDePagoRef
3. Chatea con el agente                  → grafo del turno + ModeloDeLenguaje
4. El agente navega el catálogo          → NavegarCatalogoUseCase
5. El agente arma un carrito             → Carrito + PropuestaDeMandato (sin firmar)
6. El turno se detiene                   → popup web, o "cli firmar <propuesta_id>"
7. El titular firma                      → EmitirMandatoUseCase → Mandato (ed25519)
8. El agente pide pagar                  → PagarCarritoUseCase → EjecutarIntencionUseCase
     8a. Topes duros                     → nunca se apagan
     8b. Reserva atómica del cupo diario → si no cabe, nadie llama a la pasarela
     8c. Política de mandato → Dictamen  → PERMITIR / CONFIRMAR / BLOQUEAR
     8d. Cobro                           → devuelve PENDING de inmediato
9. La pasarela manda el evento           → webhook → ConciliarEventoUseCase confirma o libera
10. El chat se entera                    → sondeo + SSE; consultar_estado confirma
```

En el paso 7, `EmitirMandatoUseCase` resuelve el medio **vinculado a ese
comercio** (`RepositorioMedios.vinculado_con`), no "el último medio vivo", que
podría ser de otro comercio y que Wompi rechazaría al cobrar.

Si 8c da `CONFIRMAR` (cabe en el mandato pero "huele raro": lo agota de una
vez, pega contra el tope por transacción o es el último uso), la reserva queda
viva hasta que una persona decide. Al decidir se repiten todos los controles:
un mandato que venció mientras tanto sigue bloqueando aunque la persona
apruebe.

---

## 10. El modelo de mandato

### `PropuestaDeMandato` vs. `Mandato`

Son tipos distintos a propósito. La propuesta (lo que arma el agente) no tiene
firma, llave pública, medio de pago ni `mandato_id`: ninguna función que
espere un `Mandato` acepta una propuesta, y eso falla al construir el objeto,
no en una validación que alguien pudo olvidar. La frontera entre proponer y
autorizar vive en el sistema de tipos.

### La carga firmada

`Mandato.canonico()` serializa, ordenado y sin la firma: `version` (hoy 2),
`mandato_id`, `titular_id`, `medio`, `comercio_id`, `monto_max`, `tope_total`,
`usos_max`, `expira_en`, `creado_en`, `categorias`, `carrito_hash` y
`llave_publica`. La versión va dentro de la carga para que una firma nunca se
reinterprete bajo otras reglas. Cambiar un nombre de campo o un valor de enum
invalidaría los mandatos ya firmados: lo vigila
`tests/arquitectura/test_invariantes_del_refactor.py`.

### Los controles al momento de cobrar

`Mandato.violaciones_contra()` revisa, en este orden:

1. **Firma** (ed25519, contra la carga canónica)
2. **Mandato correcto** (la intención cita ese `mandato_id`)
3. **Vigencia**
4. **Comercio autorizado**
5. **Monto máximo por transacción** (`monto_max`)
6. **Tope acumulado** (`tope_total` más lo consumido)
7. **Usos disponibles** (`usos_max`)
8. **Categoría autorizada** (si el mandato las restringe)
9. **Integridad del carrito** (`carrito_hash`, si el mandato se firmó atado a
   un carrito: el *Cart Mandate* de AP2)

Con `exigir_mandato=True`, cualquier violación da `BLOQUEAR`. Sin violaciones
pero con una señal blanda, `CONFIRMAR`. Sin nada, `PERMITIR`. Con
`exigir_mandato=False` (el brazo sin control del experimento) las violaciones
se registran pero no bloquean: así se midió que la pasarela aprobó un cobro de
15.000 COP contra un mandato que autorizaba 8.000.

### Lo que el mandato protege, y lo que no

Protege contra un comercio que cobra distinto de lo pactado y contra un agente
que intenta gastar de más o reutilizar una autorización agotada. **No** protege
contra un agente al que convencieron (por ejemplo, con una inyección de
prompt) de pedir *otra cosa dentro del mismo límite*: si la intención cabe, el
mandato la deja pasar, porque para eso se firmó. Ese caso lo atrapa
`CONFIRMAR` o un motor de riesgo aparte, no la firma.

---

## 11. Persistencia y consistencia

| | Memoria | SQLite |
|---|---|---|
| Sobrevive un reinicio | No | Sí |
| Compartido entre procesos (API, webhook, CLI) | No | Sí |
| Uso | Pruebas, demos de un solo proceso | Cualquier uso con chat y firma, y siempre con Wompi |
| Reserva del cupo diario | Atómica en el proceso (lock) | Atómica entre conexiones (`BEGIN IMMEDIATE`), probada con concurrencia real |

`AGORA_PASARELA=wompi` + `AGORA_AMBIENTE=produccion` +
`AGORA_PERSISTENCIA=memoria` no arranca: un mandato agotado "resucitaría" con
solo reiniciar el proceso. No hay bandera para saltarse esa regla.

---

## 12. Usuarios, sesiones y llaves

- Los usuarios se crean con `python -m agora crear-usuario --nombre-usuario
  <nombre>` (la contraseña se pide sin eco si no se pasa). No hay registro
  público.
- `RegistrarUsuarioUseCase` guarda el usuario con su contraseña hasheada
  (PBKDF2-SHA256) y genera **un par ed25519 propio** para ese titular. Cada
  mandato se firma con la llave de su titular, resuelta por
  `RegistroDeFirmantes`; si el titular no tiene llave, `SinLlaveDeFirma`.
- La sesión web es una cookie httponly (`agora_sesion`, 12 horas). El
  `titular_id` de cada acción sale de ahí, nunca del cliente.
- La llave privada se guarda sin cifrar en SQLite: alcance de PoC, igual que
  las credenciales de Wompi.

---

## 13. Pruebas

`python -m pytest -q`. La suite está en carpetas espejo de los módulos:
`tests/arquitectura`, `model`, `usecase`, `usecase/agente`,
`driven_adapters`, `entry_points` y `app_service`.

- **`tests/arquitectura/test_fronteras.py`** — el `validateStructure` (sección 2).
- **`tests/arquitectura/test_invariantes_del_refactor.py`** — un mandato
  firmado y guardado sigue verificando; los errores que lee el agente no
  cambian de nombre ni de `reintentable`; las rutas de datos se resuelven
  desde la raíz del repositorio.
- El resto cubre cada adaptador, cada caso de uso, el agente (clasificación,
  grafo, agentes especializados, pausa, traza), la CLI y la API de punta a
  punta, la concurrencia real del `LibroDeConsumo` en SQLite y el enrutamiento
  multi-comercio.

El número de pruebas cambia con la suite: confirmar en verde localmente en vez
de fiarse de una cifra escrita.

---

## 14. Variables de entorno

Se cargan desde el `.env` de la raíz (no versionado). Plantilla comentada en
[`docs/variables-de-entorno.md`](docs/variables-de-entorno.md). Todas las lee
`app_service/config/configuracion.py`.

| Variable | Default | Efecto |
|---|---|---|
| `AGORA_AMBIENTE` | `sandbox` | `sandbox` \| `produccion` |
| `AGORA_PASARELA` | `simulada` | `simulada` \| `wompi` |
| `AGORA_PERSISTENCIA` | `memoria` | `memoria` \| `sqlite` |
| `AGORA_SQLITE_PATH` | `agora_datos/agora.db` | Solo con `sqlite`. |
| `AGORA_BITACORA` | `agora_datos/recibos.jsonl` | Bitácora de cobros. |
| `AGORA_TRAZAS` | `agora_datos/trazas.jsonl` | Trazas de cada turno del agente. |
| `AGORA_WOMPI_COMERCIOS` | `agora_datos/secretos/comercios_wompi.json` | Credenciales de Wompi por `comercio_id` (`public_key`, `private_key`, `integrity_secret`, `events_secret`). Solo con `wompi`. |
| `PAGADOR_EMAIL` · `PAGADOR_NOMBRE` · `PAGADOR_TELEFONO` · `PAGADOR_DOCUMENTO` · `PAGADOR_TIPO_DOC` | `demo@agora.local` (correo) | El `customer_data` que ve el antifraude de Wompi en cada cobro. Un correo en un dominio reservado es leído como fraude. |
| `DEEPSEEK_API_KEY` | — | Sin ella, todo funciona salvo el chat (la API responde 503 en `POST /sesiones`). |
| `DEEPSEEK_MODELO` | `deepseek-chat` | |
| `OPENAI_API_KEY` | — | Embeddings para el soporte documental y la búsqueda semántica. Opcional. |
| `AGORA_EMBEDDINGS_MODELO` | `text-embedding-3-small` | |
| `AGORA_SOPORTE_DOCUMENTOS` | `docs/soporte` | Corpus del agente de soporte. |
| `AGORA_CLASIFICADOR` | `hibrido` | `hibrido` \| `reglas` \| `apagado` |
| `AGORA_ORQUESTACION` | `grafo` | `grafo` (LangGraph) \| `directo` |
| `AGORA_API_HOST` · `AGORA_API_PORT` | `0.0.0.0` · `8002` | `python -m agora api` |
| `AGORA_WEBHOOK_HOST` · `AGORA_WEBHOOK_PORT` | `0.0.0.0` · `8001` | `python -m agora webhook` |

---

## 15. Rieles de pago: por qué Wompi + Nequi

Resumen de [`docs/utils/informe-viabilidad-pagos-agenticos-co.md`](docs/utils/informe-viabilidad-pagos-agenticos-co.md):
el riel es **Wompi en producción, con fuentes de pago Nequi**. Alternativas
descartadas: Bold (no documenta cobro recurrente), ePayco (tokenización solo
para tarjeta), Treli (envuelve Wompi y esconde lo que la PoC quiere observar),
el API de Bancolombia (sin primitivo de débito delegado; el Decreto 1297 de
2022 prohíbe automatizar el Botón Bancolombia) y Bre-B (irreversible: es el
riel que usaría un atacante para sacar el dinero, no uno para cobrar con
seguridad).

El hallazgo central de esa investigación: **ningún riel colombiano entrega por
sí solo la capa de mandato**. Un `payment_source_id` de Wompi no tiene tope,
vencimiento ni ligadura a un monto, producto o comercio — eso es lo que agrega
el motor de pagos de agora. Y el primer cobro real mostró otro control que
nadie del lado del comercio ve: el antifraude de Wompi
([`docs/utils/decline-afe.md`](docs/utils/decline-afe.md)).

---

## 16. Estado y pendientes

Completo:

- Arquitectura en la Clean Architecture de Bancolombia, con su
  `validateStructure` (`tests/arquitectura/`).
- Agente en grafo con siete agentes especializados, clasificación de
  intención, soporte documental, búsqueda en tres peldaños, pausa humana tipada
  y trazabilidad, validado contra modelos reales.
- Chat web con login, firma, rechazo y confirmación en popup, y gestión de
  medios de pago; CLI completa.
- Multi-usuario con una llave de firma por titular.
- Multi-comercio con credenciales de Wompi por comercio.
- SQLite con reserva/confirmación atómica; webhook vivo y sondeo de pagos
  pendientes.

Pendiente o fuera de alcance a propósito:

- Un motor de riesgo real más allá de las señales blandas fijas de
  `model/mandato/politica.py`.
- Meter la correspondencia medio↔comercio dentro de la carga firmada (una
  versión nueva del mandato), en vez de garantizarla solo al firmar
  (ADR-8 en [`docs/arquitectura.md`](docs/arquitectura.md)).
- Extraer de `entry_points/api_rest/sesiones.py` la lógica de reanudar turnos y
  registrar pendientes a un caso de uso con su propio repositorio de sesiones.
- Cifrar las llaves privadas en reposo.
