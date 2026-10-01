# Migración de `agora/` a la Clean Architecture de Bancolombia

**Roadmap, viabilidad y riesgos** · 30 sep 2026 · rama de partida: `dev` (`2e743f1`)

> Alcance acordado: **se mantiene Python** (LangGraph, LangChain, FastAPI). Se adopta
> la estructura de módulos, la nomenclatura y las reglas de dependencia del
> *Scaffold Clean Architecture* de Bancolombia, traducidas a Python. Este documento
> no contiene código: es el plan para escribirlo.

---

## 0. Resumen ejecutivo

- **Viabilidad: alta.** `agora/` ya es hexagonal: el grafo de imports (medido con
  AST sobre los 123 archivos) muestra que **todas las dependencias apuntan hacia
  adentro**. El dominio no importa ningún framework y los puertos son `Protocol`.
  El 80 % del trabajo es reubicar y renombrar.
- **Lo que no es mecánico son tres cambios de diseño:**
  1. **Fusionar `dominio/` + `puertos/` en `domain/model`.** En el modelo de
     Bancolombia, los *gateways* viven dentro del *model*, junto a su agregado.
  2. **Los *entry points* tienen que dejar de tocar repositorios.** Hoy la API y la
     CLI leen `contenedor.carritos`, `.propuestas`, `.medios`, `.mandatos` y
     `.consumo` directo, sin pasar por un caso de uso, y además importan
     `composicion.Contenedor`.
  3. **Un único `app-service`.** Hoy hay seis *composition roots* (`servir_api`,
     `servir_webhook_wompi`, la CLI, `crear_usuario`, `generar_catalogo_semilla`,
     `validar_con_modelos_reales`).
- **Riesgo principal: que la frontera del agente siga en verde sin estar
  protegiendo nada.** `tests/test_fronteras.py` decide la capa por el primer
  segmento de la ruta y, en un caso, busca la cadena `"pasarela"` en el nombre del
  módulo. Si se mueven los archivos sin reescribir esa prueba antes, puede pasar
  sin revisar nada. **Por eso es lo primero del roadmap, antes de mover un solo
  archivo.**
- **Segundo riesgo: datos y dinero real.** Ahí están la firma canónica de los
  mandatos (`Mandato.canonico()` serializa los nombres de los campos), las rutas
  calculadas con `__file__` (si se rompen, se crea un `agora.db` **vacío** en
  silencio) y la rama `prod`.
- **Esfuerzo estimado:** 9 a 13 días-persona en 8 fases incrementales, más una
  fase opcional. Todas dejan las **1.117 pruebas** en verde; ese es el número
  medido hoy en `dev`: 1.117 aprobadas, 0 fallidas, Python 3.10.

---

## 1. La arquitectura objetivo (resumen del artículo y del scaffold)

Fuente: [Clean Architecture — Aislando los detalles (Bancolombia Tech)](https://medium.com/bancolombia-tech/clean-architecture-aislando-los-detalles-4f9530f35d7a)
y el [Scaffold Clean Architecture](https://github.com/bancolombia/scaffold-clean-architecture).

| Módulo | Capa | Responsabilidad | Puede depender de |
|---|---|---|---|
| `domain/model` | Dominio | Entidades y objetos de valor **con comportamiento**, más las interfaces **gateways** (puertos) que abstraen la infraestructura | Solo de sí mismo |
| `domain/usecase` | Dominio | Casos de uso: lógica de aplicación que orquesta el *model*. Complejidad esencial | `model` |
| `infrastructure/driven-adapters/*` | Infraestructura | Implementan los gateways (BD, APIs, archivos). Complejidad accidental, intercambiable | `model` |
| `infrastructure/entry-points/*` | Infraestructura | Exponen los casos de uso por una tecnología (REST, CLI, colas). Traducen señales externas a DTOs y **delegan en el caso de uso** | `usecase` (y `model`) |
| `infrastructure/helpers/*` | Infraestructura | Utilidades compartidas por adaptadores y *entry points* | — |
| `applications/app-service` | Aplicación | El módulo más externo: **único `main`**. Resuelve dependencias e inyecta implementaciones concretas en los casos de uso | Todo |
| `deployment/` | — | Artefactos de despliegue (Dockerfile, etc.) | — |

Principios que el artículo pone por encima de la estructura:

- **Política vs. detalle.** Las reglas de negocio son la política; frameworks,
  protocolos y bases de datos son detalles. La forma del sistema tiene que hacer
  irrelevantes los detalles para la política.
- **Complejidad esencial vs. accidental.** La primera va en `model`/`usecase`, en el
  lenguaje del negocio; la segunda queda aislada en infraestructura.
- **Regla de dependencia unidireccional**, sostenida con inversión de dependencias
  (el dominio define la interfaz) e inyección por constructor.
- **Convenciones del scaffold:** `model/<agregado>/` con su subcarpeta
  `gateways/`, `usecase/<caso>/` con clases terminadas en `UseCase`, un módulo por
  adaptador o *entry point*, y la tarea `validateStructure` para verificar que el
  dominio no dependa de infraestructura.
- El scaffold pregunta **`imperative | reactive`**. `agora` es imperativo: FastAPI
  síncrono, hilos para el sondeo y ningún `async` en el dominio. Se elige
  **imperative** y la migración a async **no** se mezcla con este refactor.

> Nota: el artículo muestra la versión 1.5.3 del plugin. La vigente es bastante
> posterior, pero la forma de los módulos es la misma. Lo que es propio de Java
> (Gradle, el `UseCasesConfig` de Spring que registra los *beans* que terminan en
> `UseCase`) no tiene equivalente directo en Python. Aquí la inyección es manual y
> la hace el `app-service`, como ya la hace `composicion/`.

---

## 2. Radiografía del estado actual

### 2.1 Tamaño por capa (`agora/`, 12.666 líneas)

| Capa actual | Archivos | Líneas | Terceros que importa |
|---|---:|---:|---|
| `dominio/` | 10 | 1.093 | ninguno ✅ |
| `puertos/` | 11 | 1.071 | ninguno ✅ |
| `aplicacion/` | 11 | 1.481 | ninguno ✅ |
| `agente/` | 16 | 2.488 | ninguno ✅ |
| `adaptadores/` | 61 | 3.633 | httpx, openai, langgraph, langchain-core, numpy, cryptography |
| `entradas/` | 10 | 1.755 | fastapi, pydantic, dotenv |
| `composicion/` | 4 | 1.145 | — |
| **pruebas** (`tests/`, 62 archivos) | 62 | 10.842 | ~335 referencias de import a `agora.*` |

### 2.2 Grafo de dependencias medido (AST, imports relativos resueltos)

- `dominio` → solo `dominio` ✅
- `puertos` → `dominio` ✅. Pasa a ser interno al fusionarse en `model`.
- `aplicacion` → `dominio`, `puertos` ✅
- `agente` → `dominio.comun`, `puertos` ✅. **No** importa `aplicacion` (la frontera).
- `adaptadores/*` → `dominio`, `puertos` ✅. Ninguno importa `aplicacion` ni `entradas`.
- `composicion` → todo ✅. Es la raíz de composición.
- `entradas.api` → **`composicion`** ❌, `agente`, `aplicacion`, `dominio`, `puertos`
- `entradas.cli` → **`composicion`** ❌, `aplicacion`, `dominio`
- `entradas.webhooks` → `aplicacion` ✅

### 2.3 Brechas contra el modelo de Bancolombia

| # | Regla de Bancolombia | Estado actual | Brecha |
|---|---|---|---|
| B1 | Los gateways viven en `model/<agregado>/gateways` | Separados: `dominio/` y `puertos/`. `puertos/repositorios.py` agrupa **8 interfaces de 4 agregados** en un solo archivo | Fusionar y partir por agregado |
| B2 | `model` solo contiene entidades, VOs y gateways | Hay contratos dentro de las entidades (`Verificador(Protocol)` en `dominio/mandato/modelo.py`) y tipos de dominio dentro de los puertos (`TopeAgotado`, `Reserva`, `FiltrosDeProducto` con lógica, `DefinicionDeGrafo` con validaciones, `PausaRequerida`, los DTOs de la pasarela, `Mensaje`/`LlamadaHerramienta`) | Reubicar cada tipo en su agregado |
| B3 | Los *entry points* delegan en casos de uso | La API y la CLI leen repositorios crudos: `carritos.obtener` (5 usos), `propuestas.obtener` (2), `medios.vivos` (2), `mandatos.listar`, `consumo.consumo_de`, `ids.nuevo` | Crear casos de uso de consulta |
| B4 | Los *entry points* no dependen de `app-service` | `entradas/api/app.py`, `sesiones.py` y `cli/__main__.py` importan `composicion.contenedor.Contenedor` | Inyectarles casos de uso, no el contenedor |
| B5 | Un único `main` en `app-service` | Seis raíces de composición repartidas entre `scripts/` y la CLI, cada una con su `load_dotenv`/`leer_configuracion` | Unificar en `app-service` con perfiles |
| B6 | Un módulo por adaptador o *entry point* | Hay subpaquetes, pero no módulos independientes | Un módulo por tecnología |
| B7 | Nomenclatura del scaffold | `dominio`, `puertos`, `aplicacion`, `adaptadores`, `entradas`, `composicion` | Renombrar la estructura (no el negocio) |
| B8 | Un caso de uso por unidad | `enrolar_medio.py` tiene 4 casos de uso y `autenticacion.py` tiene 2 | Uno por carpeta |
| B9 | `helpers` | No existe; `utilidades/env.py` queda fuera del paquete | Absorber en `app-service` |
| B10 | `validateStructure` | **Superado:** `test_fronteras.py` tiene 29 funciones de prueba, incluido un detector que se prueba a sí mismo. Pero está acoplado a los nombres de carpeta | Reescribir antes de mover |
| B11 | Sin detalles de proveedor en `model` | `ComercioSinCredencialesWompi` es un error del dominio; `Proveedor.WOMPI` es un enum del dominio | Aceptable como dato; revisar el nombre del error |
| B12 | *(no contemplado)* | `agente/` es una capa propia con reglas más estrictas que las de Bancolombia | Decidir dónde vive (D3) |

**Lo que ya cumple sin tocar nada:** el dominio no tiene frameworks ni
`os`/`sqlite3`/`httpx`; los adaptadores implementan puertos y no orquestan; la
configuración se lee en un solo lugar (`leer_configuracion(entorno)` recibe un
mapping); los topes duros están en código; las pruebas de frontera se verifican a
sí mismas.

---

## 3. Mapa de correspondencias: actual → objetivo

### 3.1 Estructura objetivo

```
poc-agentic-commerce-fraud/
├── applications/
│   └── app-service/                 agora.app_service
│       ├── main                     único punto de arranque, con perfiles: api | webhook | cli | crear-usuario | generar-catalogo
│       └── config/                  contenedor, configuración (.env), cableado del agente, raíz del repo
├── domain/
│   ├── model/                       agora.model
│   │   ├── commons/                 Dinero, identidad, ErrorDeDominio (base); gateways/: Reloj, GeneradorIds, Bitacora
│   │   ├── mandato/                 Mandato, PropuestaDeMandato, Intencion, Consumo, Violacion, Dictamen, errores
│   │   │   └── gateways/            RepositorioMandatos, RepositorioPropuestas, LibroDeConsumo (+Reserva, TopeAgotado), Verificador
│   │   ├── pago/                    MedioDePagoRef, OrdenDeCobro, ResultadoCobro, TopesDuros, Ambiente, errores
│   │   │   └── gateways/            PasarelaDePagos (+DTOs de enrolamiento), SelectorDePasarela, RepositorioMedios, RegistroDeEstados
│   │   ├── catalogo/                Comercio, Producto, Carrito, FiltrosDeProducto, errores
│   │   │   └── gateways/            RepositorioCatalogo, RepositorioCarritos, BuscadorSemanticoDeProductos
│   │   ├── usuario/                 Usuario, errores de autenticación
│   │   │   └── gateways/            RepositorioUsuarios, RepositorioLlaves, HasherDeContrasenas, Firmante, SelectorDeFirmante, GeneradorDeLlaves
│   │   └── agente/                  Mensaje, LlamadaHerramienta, Herramienta, TipoDeIntencion, PausaDelTurno, DecisionHumana, DefinicionDeGrafo, PausaRequerida
│   │       └── gateways/            ModeloDeLenguaje, CompiladorDeGrafos, BuscadorDocumental, ProveedorDeEmbeddings
│   └── usecase/                     agora.usecase
│       ├── ejecutar_intencion/      EjecutarIntencionUseCase (+ Recibo)
│       ├── emitir_mandato/  rechazar_propuesta/  conciliar_evento/  consultar_estado/
│       ├── iniciar_enrolamiento/  consultar_enrolamiento/  confirmar_enrolamiento/  enrolar_medio/  revocar_medio/
│       ├── registrar_usuario/  iniciar_sesion/
│       ├── navegar_catalogo/  generar_catalogo_semilla/
│       ├── consultas/  (NUEVO)      obtener_carrito, obtener_propuesta, listar_medios_vivos, listar_mandatos, consultar_consumo
│       └── agente/                  conversación, grafo del turno, agentes especializados, nodos, lista blanca de herramientas,
│                                    clasificación, contexto documental, pausa, traza, política/prompt
├── infrastructure/
│   ├── driven-adapters/
│   │   ├── pasarela-wompi/          (+ cliente HTTP, config)
│   │   ├── pasarela-simulada/       (+ guion)
│   │   ├── selector-pasarelas/      (registro.py actual)
│   │   ├── persistencia-sqlite/
│   │   ├── persistencia-memoria/
│   │   ├── catalogo-semilla/        (+ datos/catalogo.json)
│   │   ├── llm-deepseek/
│   │   ├── embeddings-openai/
│   │   ├── recuperacion-langchain/
│   │   ├── busqueda-semantica-memoria/
│   │   ├── orquestacion-langgraph/
│   │   ├── firma-ed25519/
│   │   ├── hasher-pbkdf2/
│   │   ├── bitacora-jsonl/
│   │   └── sistema/                 reloj, ids
│   ├── entry-points/
│   │   ├── api-rest/                FastAPI, sesiones de chat, sondeo de pagos, estatico/chat.html
│   │   ├── webhook-wompi/
│   │   └── cli/
│   └── helpers/                     (vacío al inicio; ver D9)
├── deployment/                      (opcional: Dockerfile)
├── tests/                           reorganizados por módulo (ver D7)
├── scripts/                         solo utilidades de laboratorio fuera de la arquitectura (validar_con_modelos_reales)
├── agora_datos/  docs/              SIN MOVER
```

Cómo se ve en Python: cada módulo tiene su carpeta con el nombre exacto del
scaffold (`driven-adapters/pasarela-wompi`) y adentro un `src/` con el paquete
importable (`agora/driven_adapters/pasarela_wompi/`). Todos comparten el
*namespace package* `agora` (PEP 420, sin `__init__.py` en la raíz `agora`), que
cumple el papel de `co.com.bancolombia` en Java. Ver D1.

### 3.2 Tabla archivo → destino

| Actual | Destino |
|---|---|
| `dominio/comun/{dinero,identidad}.py` | `model/commons/` |
| `dominio/comun/errores.py` (42 clases) | Base en `model/commons/`; cada familia al agregado que la lanza (mandato, pago, catálogo, usuario, agente) |
| `dominio/{mandato,pago,catalogo,usuario}/*` | `model/<agregado>/` |
| `dominio/mandato/modelo.py::Verificador` | `model/mandato/gateways/` |
| `puertos/repositorios.py` | Se parte en cuatro: mandato, pago, catálogo y usuario (el `gateways/` de cada uno) |
| `puertos/{pasarela,firma,autenticacion,catalogo,busqueda_productos,sistema}.py` | El `gateways/` del agregado que corresponda; los DTOs y las excepciones van al agregado |
| `puertos/{modelo_lenguaje,orquestacion,recuperacion}.py` | `model/agente/` (tipos) + `model/agente/gateways/` (Protocols) |
| `aplicacion/*.py` | `usecase/<caso>/`, uno por carpeta, con sufijo `UseCase` (D2) |
| `agente/**` | `usecase/agente/**`; sus tipos puros van a `model/agente/` (D3) |
| `adaptadores/<familia>/<impl>/` | `driven-adapters/<familia>-<impl>/` |
| `entradas/{api,webhooks,cli}` | `entry-points/{api-rest,webhook-wompi,cli}` |
| `composicion/*`, `utilidades/env.py`, el arranque de `scripts/servir_*.py`, `crear_usuario.py`, `generar_catalogo_semilla.py` y `cli/__main__.py` | `applications/app-service/` |
| `tests/test_fronteras.py` | Pasa a ser el `validateStructure` del proyecto (Fase 0 y Fase 6) |

---

## 4. Decisiones a tomar (ADRs)

> **Estado: aceptadas.** Las diez recomendaciones se aprobaron tal cual el 30 sep 2026.

Cada una trae una recomendación. Conviene cerrarlas **antes** de la Fase 1.

**D1. La forma de los módulos en Python.**
- *(A, recomendada)* Carpetas idénticas a las del scaffold, cada una con su `src/`
  y el *namespace* `agora.*`. Un solo `pyproject.toml` en la raíz declara todas las
  raíces `src/`. Es fiel a la estructura oficial y ya deja el terreno listo para
  D1-B.
- *(B)* Un workspace (uv) donde **cada módulo tiene su propio `pyproject.toml`** y
  declara sus dependencias; es el equivalente real del multi-módulo de Gradle
  (`langgraph` solo se instala con `orquestacion-langgraph`). Más fiel, pero suma
  unos 20 manifiestos para una PoC de 12.600 líneas. **Se deja como Fase 8
  opcional.**
- *(C)* Un paquete único con guiones bajos (`agora/infrastructure/driven_adapters/…`).
  Es lo más simple, pero se aparta a la vista de la estructura oficial.

**D2. Idioma y sufijos.** La estructura va en inglés, como en el scaffold
(`model`, `usecase`, `gateways`, `driven-adapters`, `entry-points`, `helpers`,
`app-service`). **El lenguaje de negocio se queda en español** (`Mandato`,
`Intencion`, `PropuestaDeMandato`, `RepositorioMandatos`): es el lenguaje ubicuo, y
además va dentro de la firma (ver R2). Los casos de uso llevan el sufijo `UseCase`
(`EjecutarIntencionUseCase`); los gateways conservan sus nombres, que ya dicen su
rol (`Repositorio*`, `Pasarela*`).

**D3. Dónde vive el agente.** Bancolombia no tiene una capa "agente".
- *(Recomendada)* La lógica de orquestación (el bucle de conversación, el grafo del
  turno, el enrutado, la lista blanca de herramientas, la pausa humana, la traza)
  es **caso de uso**: va a `usecase/agente/`. Sus tipos (mensajes, intenciones,
  pausa, definición del grafo) van a `model/agente/`. El LLM, LangGraph y el
  retrieval quedan como *driven adapters*, igual que hoy.
- **Consecuencia crítica:** en Bancolombia un caso de uso **sí puede** importar a
  otro, porque están en el mismo módulo. La regla de la PoC ("el agente no puede
  importar `EjecutarIntencion`") queda **más estricta que la de la organización** y
  hay que mantenerla con una regla propia:
  `usecase.agente` no puede importar ningún otro `usecase.*`, ni los gateways de
  pago, firma o llaves, ni `importlib`. Esa regla es la tesis de la PoC y no se
  negocia en el refactor.

**D4. Cómo llegan las herramientas al agente.** Se mantiene el mecanismo actual:
el agente recibe seis *callables* ya cerrados sobre casos de uso reales. Los arma
el único lugar que conoce las dos cosas (hoy `composicion/agente.py`, mañana
`app-service/config`). Descartado: convertir las herramientas en un *entry point*
(el caso de uso del agente terminaría llamando a infraestructura) o en un
*driven adapter* (un adaptador no puede depender de casos de uso en el modelo de
Bancolombia).

**D5. Un solo `main`, varios perfiles.** Queda un único arranque en `app-service`
con perfiles `api`, `webhook`, `cli`, `crear-usuario` y `generar-catalogo`. La API
(8002) y el webhook (8001, detrás de ngrok) **siguen siendo procesos separados**:
se unifica el código de arranque, no el despliegue. `validar_con_modelos_reales.py`
es un experimento, no una aplicación, y se queda en `scripts/` consumiendo el
`app-service`.

**D6. Módulos puente temporales.** Se recomienda dejarlos. Mientras dura la
migración, las rutas viejas (`agora/dominio/...`) re-exportan desde las nuevas, así
cada fase es pequeña y las pruebas se actualizan por partes. Una prueba impide que
el código de producción importe un puente, y todos se borran en la Fase 6.

**D7. Dónde quedan las pruebas.** En `tests/` se reorganizan en subcarpetas
espejo (`tests/model`, `tests/usecase`, `tests/driven_adapters/...`,
`tests/entry_points/...`, `tests/app_service`). Moverlas a cada módulo (`src/test`,
como en Gradle) solo tiene sentido si se ejecuta D1-B.

**D8. Cómo se hace cumplir la estructura.** `test_fronteras.py`, reescrito, pasa a
ser el `validateStructure` y conserva las reglas propias de la PoC. Opcional:
sumar contratos de `import-linter` (capas + independencia) como segunda red,
declarativa y legible para alguien de arquitectura que no conozca el proyecto.

**D9. `helpers` y `sesiones.py`.** `utilidades/env.py` es arranque, así que va a
`app-service`, no a `helpers`. `entry-points/api-rest/sesiones.py` (297 líneas)
hoy tiene lógica de aplicación: reanuda turnos, registra pagos pendientes a partir
de los resultados de las herramientas y guarda estado en memoria. En este refactor
se mueve **tal cual** y queda anotado como deuda. Extraerlo a un
`ConversarConAgenteUseCase` con un gateway `RepositorioDeSesiones` es una mejora
posterior, con su propio riesgo.

**D10. `ComercioSinCredencialesWompi`.** El nombre de la clase **llega al agente**
(`to_json()` → `"tipo": type(self).__name__`) y queda en `recibos.jsonl`. Se
recomienda **no renombrar ninguna clase de error** en este refactor (ver R3). El
cambio a un nombre agnóstico, que empuja la rama de rieles simulados, se hace
después, con un alias y una nota en la bitácora.

---

## 5. Roadmap por fases

Reglas para **todas** las fases:

- Se trabaja en una rama `refactor/clean-architecture-bancolombia` que sale de
  `dev`. Nada llega a `prod` hasta la Fase 7.
- Cada fase termina con las **1.117 pruebas en verde**, más las nuevas, y con el
  flujo de punta a punta en `AGORA_PASARELA=simulada` (CLI y chat web).
- **Los movimientos y las ediciones van en commits separados** (primero `git mv`,
  después el ajuste de imports), para que git detecte los renombres y
  `git blame` conserve la historia.
- Ninguna fase cambia el comportamiento observable **salvo la Fase 1**, que cambia
  cómo los *entry points* consultan datos (el resultado debe ser el mismo).

### Fase 0: Preparación y red de seguridad (1 a 1,5 días) · sin mover código

> **✅ Hecha (30 sep 2026).** Queda en 1.140 pruebas; ver `linea-base.md`. Diferencias con lo planeado:
> - El detector no se probó "sobre ambos layouts": el layout nuevo todavía no existe. Lo que sí quedó es que la capa sale de la tabla `CAPAS`, así que la Fase 2 solo agrega entradas y las pruebas del detector se reescriben ahí.
> - Además, una regla que apunta a un módulo o carpeta que ya no existe (`_es_modulo`, `_modulos_bajo`) ahora falla en vez de pasar en vacío.
> - La frontera del agente quedó **más estricta**: también le quedan vedados los *puertos* de pasarela, firma, repositorios y autenticación. La regla anterior los dejaba pasar.
> - El flujo de punta a punta en modo simulado no se registró aparte: lo cubren `test_cli.py` y `test_api_app.py`.
> - El mandato dorado se firmó con una llave de prueba fija, no se exportó de `agora.db`: prueba lo mismo sin sacar datos reales de la base.
> - Pendiente de Juan: `git switch -c refactor/clean-architecture-bancolombia` y el commit (ver el resumen de la sesión).

1. **Dejar el árbol limpio.** Los 7 archivos que hoy aparecen modificados en `dev`
   (`dinero.py`, `pago/*`, `utilidades/*`, `cmds.txt`) **solo difieren en los
   finales de línea**: `git diff --ignore-cr-at-eol` sale vacío. Agregar
   `.gitattributes` para normalizar CRLF/LF; si no, cada `git mv` + edición va a
   mostrar archivos completos como cambiados y se pierde la detección de
   renombres. Limpiar los `__pycache__` viejos (hay `.pyc` de `mandato/compat.py`
   y `scripts/probe_v2.py`, que ya no existen).
2. **Registrar la línea base:** número de pruebas por archivo, la salida del flujo
   de punta a punta en modo simulado y un mandato v2 firmado real exportado como
   *fixture* dorado (ver R2).
3. **Reescribir `test_fronteras.py` para que no dependa de rutas.** Hoy
   `_capa()` toma el primer segmento de la ruta como capa, y
   `test_el_agente_no_alcanza_ninguna_pasarela` busca `"pasarela"` en el nombre del
   import y exceptúa lo que contenga `"puertos"`. La versión nueva:
   - Una **tabla explícita de módulo → capa**, con las reglas expresadas entre
     capas, no entre nombres de carpeta. Así en la Fase 2 solo se cambia la tabla.
   - **Guardas de cobertura:** cada capa tiene que tener al menos N archivos
     (hoy 10/11/11/16/61/10/4). Si un movimiento deja una capa vacía, la prueba
     falla en vez de pasar sin revisar nada.
   - El detector (las pruebas `test_el_detector_atrapa_*` sobre un árbol de
     mentira en `tmp_path`) se reescribe **sobre ambos layouts**, para demostrar
     que atrapa las violaciones antes y después.
   - `MODULOS_DE_LA_MIGRACION_A_AGENTES` pasa de rutas a una lista de módulos
     lógicos resuelta por la tabla.
4. **Una sola forma de encontrar la raíz del repo.** Hoy hay 7 cálculos con
   `Path(__file__).parent…`: `configuracion.py` usa 3 niveles, la CLI 4 y cada
   script 2. Reemplazarlos por una función que busque un marcador (`pyproject.toml`)
   y **una prueba que verifique** que `agora_datos/agora.db`, `docs/soporte/` y
   `agora_datos/secretos/` se resuelven a rutas existentes (ver R4).
5. **Crear `pyproject.toml`** (hoy solo hay `requirements.txt`). El proyecto queda
   instalable en modo editable y `pytest` encuentra los paquetes sin depender del
   directorio actual. Sumar `openai` y `numpy` (ya están en `requirements.txt`)
   y fijar versiones mínimas.
6. Redactar y aprobar los ADR D1 a D10.

**Salida:** la misma suite en verde, con fronteras que no dependen de nombres de
carpeta y una raíz del repo que no depende de la ubicación del archivo.

### Fase 1: Sanear las fronteras en el layout actual (1,5 a 2 días)

> **✅ Hecha (30 sep 2026).** Queda en 1.156 pruebas; también se corrió de punta a punta por CLI en modo simulado con SQLite temporal (enrolar, emitir, pagar, retomar, estado, mandatos, fuentes). Diferencias con lo planeado:
> - **`PagarCarrito`** (`aplicacion/pagar_carrito.py`) reemplaza a `ObtenerCarrito` y al `ids.nuevo` suelto. La misma `Intencion` se armaba a mano en cuatro lugares (la herramienta `pagar` del agente, `cli pagar`, `cli retomar` y `POST /intenciones/{id}/retomar`); ahora comercio, monto y `carrito_hash` salen siempre del carrito guardado, en un solo lugar.
> - `ObtenerPropuesta` y la lectura del carrito para el popup quedaron como `NavegarCatalogo.ver_propuesta` y `ver_carrito`, no como clases aparte. `ConsultarConsumo` quedó dentro de `ListarMandatos`. `ListarMediosVivos` sí es un caso de uso propio.
> - La API recibe un `DependenciasDeLaApi` (un `Protocol` con casos de uso, `ambiente` y `reloj`). El `Contenedor` lo cumple sin que la API lo importe, así que las pruebas y `servir_api.py` no cambiaron.
> - La CLI **sigue** importando `composicion`, porque es composition root hasta la Fase 5. Quedó como `EXCEPCIONES_PROVISORIAS` en `test_fronteras.py`, con una prueba que avisa cuando deja de hacer falta. Igual ya no toca ningún repositorio: lo verifica una regla nueva sobre el AST de `entradas/`.
> - Cambio visible: si el cobro falla con un error de dominio, `cli pagar` ahora imprime `[x] …` en vez de un traceback.
> - **Pasados a otras fases, para no mover dos veces lo mismo:** llevar `Verificador` a los puertos pasa a la Fase 2, donde de todos modos va a `model/mandato/gateways/`. Partir `enrolar_medio.py` y `autenticacion.py` pasa a la Fase 3, donde cada caso de uso recibe su carpeta.

Las brechas de diseño se corrigen **antes** de mover archivos. Así, si algo se
rompe, se sabe que fue por diseño y no por un import.

1. **Casos de uso de consulta** para lo que los *entry points* hoy leen crudo:
   `ObtenerCarrito`, `ObtenerPropuesta`, `ListarMediosVivos`, `ListarMandatos` y
   `ConsultarConsumo`. La CLI genera un id con `contenedor.ids.nuevo`; eso pasa al
   caso de uso que lo necesita.
2. **Los *entry points* dejan de recibir el `Contenedor`.**
   `crear_app(agente, contenedor)` y `AlmacenDeSesiones(agente, contenedor)`
   reciben los casos de uso que usan y el `ambiente` como valor (hoy leen
   `contenedor.config.ambiente` en 9 lugares).
3. Mover `Verificador(Protocol)` de `dominio/mandato/modelo.py` a `puertos/`.
4. Partir `aplicacion/enrolar_medio.py` (4 clases) y `autenticacion.py` (2).
5. Agregar reglas a `test_fronteras.py`: `entradas` no puede importar
   `composicion` ni los módulos de repositorio.

**Salida:** la regla "los *entry points* solo hablan con casos de uso" ya se cumple
y se verifica, con la estructura de siempre.

### Fase 2: `domain/model` (1,5 a 2 días)

> **✅ Hecha (30 sep 2026).** Queda en 1.189 pruebas, con el flujo de CLI de punta a punta en simulado y los 5 scripts arrancando sin errores. `pip install -e .` también funciona desde fuera del repo.
> - **Cómo se enchufa el módulo:** el código vive en `domain/model/src/agora/model/`, y `agora/__init__.py` agrega esa carpeta a `agora.__path__` (tupla `_MODULOS`: cada fase suma la suya). Así `agora.model.*` se importa igual desde el repo, los scripts, pytest y una instalación editable. Límite: no sirve para un wheel. Si algún día hace falta, se pasa a PEP 420 con un pyproject por módulo (Fase 8).
> - **Sin módulos puente (D6):** las 312 sentencias de import de `agora/`, `tests/` y `scripts/` se reescribieron de una vez con un script que lee el AST. No quedó nada viejo que borrar en la Fase 6.
> - **Gateways:** cada agregado tiene su carpeta `gateways/`, y cada puerto viejo se movió **entero** (con su docstring) al agregado que le corresponde. `puertos/repositorios.py` se partió en cuatro: mandato, pago, catálogo y usuario. `Verificador` salió de la entidad y se fue a `model/mandato/gateways/firma.py`. Los tipos que solo existen como contrato de un puerto (`Reserva`, `TopeAgotado`, `FiltrosDeProducto`, los DTOs de la pasarela, `Mensaje`, `DefinicionDeGrafo`, `PausaRequerida`) se quedaron junto a su gateway, en vez de pasar al archivo de la entidad.
> - **Los puertos del agente** (LLM, orquestación, recuperación) quedaron en `model/agente/gateways/`. Los tipos propios del agente llegan en la Fase 3.
> - **`errores.py` no se partió:** se movió entero a `model/commons/errores.py`. La prueba que congela nombres y `reintentable` sigue en verde.
> - **`test_fronteras.py`** ahora recorre todas las raíces de `agora.__path__` y guarda en caché el AST de cada archivo: en la VM del puente la suite completa bajó de ~110 s a ~45 s. Regla nueva: `model` solo importa `model` y la biblioteca estándar, que equivale al `whitelistedDependencies` de Bancolombia con la lista vacía. La frontera del agente ahora nombra los gateways nuevos, entre ellos los cuatro de repositorios.
> - **Pendiente para la Fase 7:** los docstrings y la documentación todavía citan rutas `dominio/…` y `puertos/…`.

1. Crear el esqueleto `domain/model/src/agora/model/…` y mover con `git mv`
   `dominio/*` → `model/<agregado>/`.
2. Fusionar los puertos: partir `puertos/repositorios.py` por agregado y llevar
   cada `Protocol` a `model/<agregado>/gateways/`. Los tipos que hoy están en los
   puertos (`Reserva`, `TopeAgotado`, `FiltrosDeProducto`, los DTOs de la pasarela,
   `Mensaje`, `DefinicionDeGrafo`, `PausaRequerida`) van al agregado.
3. Partir `errores.py` por familia, **sin cambiar ningún nombre de clase ni la
   jerarquía** (`ErrorDeDominio` sigue siendo la raíz).
4. Dejar puentes en `agora/dominio/*` y `agora/puertos/*` (D6).
5. Actualizar la tabla de capas de `test_fronteras.py`: `model` no importa nada
   fuera de `model` y de la biblioteca estándar (sin `os`, `sqlite3`, `httpx`,
   `fastapi` ni librerías de LLM).

**Salida:** existe `domain/model` y todo lo demás compila contra él a través de
los puentes.

### Fase 3: `domain/usecase`, con el agente (1,5 a 2 días)

> **✅ Hecha (30 sep 2026).** Queda en 1.205 pruebas, con el flujo de CLI de punta a punta en simulado y los 5 scripts arrancando sin errores.
> - **17 casos de uso,** cada uno en `domain/usecase/src/agora/usecase/<caso>/<caso>_use_case.py`, con la clase terminada en `UseCase`. Aquí se hizo lo que la Fase 1 había dejado pendiente: `enrolar_medio.py` se partió en cuatro (`iniciar_enrolamiento`, `consultar_enrolamiento`, `confirmar_enrolamiento` y `enrolar_medio`, que compone a los otros tres) y `autenticacion.py` en dos (`registrar_usuario`, `iniciar_sesion`). `ListarMediosVivos` vive en `listar_medios_vivos/`.
> - **Renombre `…UseCase`:** 324 apariciones en 64 archivos (código, pruebas, scripts y docstrings). La documentación `.md` queda para la Fase 7. Ningún nombre de caso de uso llegaba al modelo de lenguaje ni a la bitácora, así que el agente no ve ningún cambio.
> - **Agente:** `agente/` se movió a `usecase/agente/`. Solo `intencion.py` y `contexto.py`, que son tipos puros, pasaron a `model/agente/`. `pausa.py`, `herramientas.py`, `nodos.py` y `traza.py` se quedaron en `usecase/agente/` porque mezclan tipos con lógica (el texto del aviso, la lista blanca, el enrutado).
> - **Fronteras:** `usecase/agente` es una capa propia ("agente") porque su prefijo es el más largo en `CAPAS`. Así sigue sin poder importar ningún otro caso de uso, adaptador ni gateway de pago, firma o llaves. La regla también quedó en sentido contrario: un caso de uso no puede importar al agente. Lo comprobé poniendo imports prohibidos reales en los dos sentidos: la suite falla con ellos y vuelve a verde sin ellos.
> - **Regla nueva del scaffold:** cada archivo de `usecase/` tiene que llamarse `<caso>/<caso>_use_case.py` y tener exactamente una clase `…UseCase`.
> - Tampoco hubo módulos puente: los imports (228) se reescribieron con el mismo script de la Fase 2.

1. `aplicacion/<caso>.py` → `usecase/<caso>/<caso>_use_case.py`, con la clase
   renombrada a `…UseCase`. Los DTOs de salida (`Recibo`, `EstadoIntencion`,
   `ResultadoConciliacion`, `ItemPedido`, `ComercioGenerado`) van con su caso de
   uso.
2. `agente/**` → `usecase/agente/**`, y sus tipos puros a `model/agente/` (D3).
3. **La regla que sostiene la PoC:** `usecase.agente` no importa `usecase.*` fuera
   de `usecase.agente`, ni gateways de pago, firma o llaves, ni `importlib`. Se
   prueba con el detector sobre un árbol de mentira; la suite tiene que fallar si
   se agrega el import prohibido.
4. Revisar que `PROHIBIDAS` (los nombres de herramienta vedados) y
   `validar_asignacion_por_nodo` siguen corriendo al construir el agente.

**Salida:** `domain/` está completo. La frontera del agente ahora está expresada
con los nombres de Bancolombia y se verifica.

### Fase 4: `infrastructure/driven-adapters` (1 día)

> **✅ Hecha (30 sep 2026).** Queda en 1.353 pruebas, con el flujo de CLI de punta a punta en simulado, los 5 scripts arrancando sin errores y `pip install -e .` probado desde fuera del repo (el catálogo semilla se encuentra).
> - **15 módulos** en `infrastructure/driven-adapters/<modulo>/src/agora/driven_adapters/<paquete>/`: `pasarela-wompi`, `pasarela-simulada`, `selector-pasarelas`, `persistencia-sqlite`, `persistencia-memoria`, `catalogo-semilla` (se lleva su `datos/catalogo.json`), `llm-deepseek`, `embeddings-openai`, `recuperacion-langchain`, `busqueda-semantica-memoria`, `orquestacion-langgraph`, `firma-ed25519` (con `registro_firmantes.py`), `hasher-pbkdf2`, `bitacora-jsonl` y `sistema` (reloj e ids). `driven_adapters` no tiene `__init__.py`: es un paquete de espacio de nombres que reparten los 15 módulos.
> - **`agora/__init__.py` ya no lleva una lista de módulos:** busca las carpetas `domain/*/src/agora` e `infrastructure/*/*/src/agora`, igual que las genera el scaffold. Agregar un adaptador ya no obliga a tocarlo.
> - **El `__init__.py` de `adaptadores/sistema`** reexportaba la firma, el hasher y la bitácora. Ahora solo exporta reloj e ids: lo demás vive en su propio módulo y quien lo usa lo importa de ahí (193 imports reescritos con el mismo script).
> - **Reglas nuevas:**
>   - Un adaptador no importa a otro.
>   - `LIBRERIAS_POR_ADAPTADOR` fija qué módulo puede usar cada librería de infraestructura (httpx, openai, langgraph, langchain, numpy, cryptography y sqlite3). Es lo que en el scaffold declara cada `build.gradle`.
>   - Lo comprobé con imports prohibidos reales: un adaptador importando a otro, y `httpx` fuera de `pasarela-wompi`. La suite falla con ellos y vuelve a verde sin ellos.

1. Un módulo por tecnología (15 módulos, §3.1). `catalogo-semilla` se lleva su
   `datos/catalogo.json`, al que hoy se llega con una ruta relativa al archivo.
2. Regla: un *driven adapter* importa solo `model` (y sus librerías). No importa
   `usecase`, `entry-points` ni **otros adaptadores**. Hoy ninguno lo hace; la
   regla es para que siga así.
3. Regla de familia: `langgraph` solo en `orquestacion-langgraph`,
   `langchain_*` solo en `recuperacion-langchain`, `openai` solo en `llm-deepseek`
   y `embeddings-openai`, `httpx` solo en `pasarela-wompi`. Es la versión por
   módulo de lo que hoy verifican `LIBRERIAS_DE_LLM` y
   `test_langgraph_vive_en_un_solo_modulo_de_agora`.

### Fase 5: `entry-points` y `app-service` (1,5 a 2 días)

1. `entradas/{api,webhooks,cli}` → `entry-points/{api-rest,webhook-wompi,cli}`.
   `estatico/chat.html` se mueve con `api-rest`.
2. `composicion/{contenedor,configuracion,agente}.py` + `utilidades/env.py` →
   `applications/app-service/config/`.
3. Un único `main` con perfiles (D5). `scripts/servir_api.py`,
   `servir_webhook_wompi.py`, `crear_usuario.py` y `generar_catalogo_semilla.py`
   quedan como envoltorios de una línea (o se eliminan) y `cmds.txt` se actualiza.
   **La forma de invocar cambia** (`python -m agora.entradas.cli …` deja de
   existir): actualizar README y el paso a paso.
4. El `Contenedor` deja de exponer repositorios crudos a los *entry points*
   (después de la Fase 1 ya nadie los usa).
5. Las pruebas `test_composicion*` (7 archivos) se mueven a `tests/app_service/`.

### Fase 6: Cierre estructural, el `validateStructure` de `agora` (0,5 a 1 día)

1. Borrar los puentes de D6 y comprobar que nada los importaba.
2. Versión final de `test_fronteras.py`:
   - `model` → solo `model` y la biblioteca estándar
   - `usecase` → `model`
   - `usecase.agente` → `model` + `usecase.agente` (más estricto)
   - `driven-adapters/*` → `model`, sin cruzarse entre ellos
   - `entry-points/*` → `usecase`, `model`, sin cruzarse entre ellos y sin `app-service`
   - `app-service` → todo
3. *(Opcional, D8)* Contratos de `import-linter` equivalentes, para que la
   estructura se pueda revisar sin leer Python.
4. Un script de verificación (`scripts/verificar.ps1` o similar) que corra la suite
   y las reglas en un paso, a falta de CI.

### Fase 7: Documentación y salida a `prod` (1 día)

1. Actualizar `README.md`, `Documentacion.md`, `docs/arquitectura-v2.md` y el
   diagrama `docs/diagramas/01-capas.mermaid`. Hoy hay **91 referencias a rutas
   `agora/…`** en la documentación. `docs/historico/` **no se toca**: es historia.
2. `docs/soporte/` (el corpus RAG) no se mueve; se comprueba que el buscador
   documental lo sigue encontrando.
3. Fusionar a `dev` y probar de punta a punta en sandbox: Wompi sandbox, webhook
   por ngrok y chat web con firma.
4. Recién entonces, fusionar a `prod`. Recomendado: **una transacción real mínima
   supervisada**, con un monto dentro de los topes, antes de dar la rama por
   buena (ver R5).

### Fase 8 (opcional): Multi-módulo real y despliegue (1 a 2 días)

- Un `pyproject.toml` por módulo (workspace uv) que declara sus dependencias.
  Así, que el dominio no pueda importar `fastapi` se sostiene también en la
  instalación, no solo en la prueba.
- `deployment/Dockerfile` por perfil (api y webhook).

---

## 6. Riesgos

| # | Riesgo | Prob. | Impacto | Mitigación |
|---|---|:-:|:-:|---|
| **R1** | **La frontera del agente pasa en verde sin revisar nada.** `_capa()` usa el primer segmento de la ruta y el chequeo de pasarela busca la cadena `"pasarela"` y exceptúa `"puertos"`. Al mover a `model/pago/gateways/pasarela…` la regla puede dar un falso positivo o, peor, dejar de aplicarse | Alta | **Crítico:** es la tesis de la PoC | Fase 0.3: tabla explícita, guardas de cobertura y detector probado sobre ambos layouts, **antes** de mover |
| **R2** | **Mandatos firmados que dejan de verificar.** `Mandato.canonico()` serializa un JSON con los **nombres de los campos**. Si se renombra un campo o el valor de un enum serializado (`Ambiente`, `Proveedor`), cambian los bytes firmados de todo mandato ya guardado en `agora.db` | Media si se traduce a inglés, baja si no | **Crítico:** se pierde evidencia | D2 (el negocio no se traduce) + *fixture* dorado con un mandato real firmado que tiene que seguir verificando en cada fase |
| **R3** | **Cambia lo que el agente ve.** Los errores se serializan con `type(self).__name__` y el LLM decide con ese nombre (reintentar, pedir otro mandato). Además quedan en `recibos.jsonl` | Media | Alto: cambia el comportamiento del agente y se corta la continuidad de la evidencia | No renombrar clases de error (D10); prueba que congele el conjunto de nombres de error |
| **R4** | **Una base de datos vacía en silencio.** Si `RAIZ_REPO` queda mal calculado tras el movimiento, `CREATE TABLE IF NOT EXISTS` crea un `agora.db` **nuevo y vacío** en otra ruta. La app arranca y "funciona", pero sin usuarios, medios ni mandatos. Igual con `secretos/comercios_wompi.json` y el corpus de soporte | Alta sin la Fase 0.4 | Alto | Raíz por marcador + prueba de que las rutas existen; que en `produccion` falle si la base no existe |
| **R5** | **Dinero real.** `prod` mueve dinero de Nequi | Baja | Crítico | Todo el refactor en simulada/sandbox; `prod` solo después de la Fase 7, con una transacción supervisada |
| **R6** | **Conflictos con el trabajo en curso** (pruebas de corrupción al agente, rama de rieles agnósticos). El refactor toca todos los archivos | Alta | Medio | Congelar las features durante la ventana (unos 2 a 3 semanas calendario) **o** hacer primero el refactor y abrir desde ahí la rama agnóstica. Una pasarela simulada nueva es un *driven adapter* más: el refactor la facilita |
| **R7** | **Particularidades de Python:** los *namespace packages* (PEP 420) con varias raíces `src/`, el modo de import de pytest, y el venv de Windows frente a la VM Linux | Media | Medio | `pyproject.toml` + instalación editable en la Fase 0; `--import-mode=importlib`; correr la suite en los dos entornos |
| **R8** | **Se pierde la historia en git** si mover y editar va en el mismo commit, y más con finales de línea mezclados | Media | Bajo/medio | `.gitattributes` (Fase 0.1); commits separados de `git mv` |
| **R9** | **Sobreingeniería:** unos 20 módulos para 12.600 líneas; fricción al agregar features | Media | Medio | D1-A (un solo manifiesto) y la Fase 8 queda opcional |
| **R10** | **Documentación desfasada** (91 rutas) y comandos de arranque que cambian (`cmds.txt`, README, runbook de ngrok) | Alta | Bajo | Fase 7; buscar `agora/` en la documentación como criterio de cierre |
| **R11** | **`sesiones.py` como deuda escondida.** Tiene lógica de aplicación dentro de un *entry point*; alguien que revise contra el estándar de Bancolombia lo va a señalar | Media | Bajo | Se deja registrado en D9 como deuda explícita, con su fase futura |
| **R12** | **Regresión del grafo LangGraph o del retrieval** por rutas de datos o imports perezosos en los adaptadores | Baja | Medio | `test_agente_grafo_equivalencia.py` y `validar_con_modelos_reales.py` como pruebas de humo al cierre de las Fases 4 y 5 |

---

## 7. Criterios de "terminado"

- [ ] La estructura de carpetas es idéntica a la del scaffold (§3.1); no quedan
      `dominio/`, `puertos/`, `aplicacion/`, `agente/`, `adaptadores/`,
      `entradas/` ni `composicion/`.
- [ ] 1.117 pruebas o más en verde, en Windows y en Linux.
- [ ] El `validateStructure` (test de fronteras) verifica las 6 reglas de la Fase
      6.2 y el detector demuestra que atrapa una violación de cada una.
- [ ] El *fixture* dorado del mandato firmado sigue verificando.
- [ ] El conjunto de nombres de error es el mismo que en la línea base.
- [ ] Ningún *entry point* importa `app-service` ni un gateway de repositorio.
- [ ] Un único `main`; la API y el webhook arrancan desde ahí.
- [ ] Flujo de punta a punta: simulada ✔, sandbox Wompi + webhook ✔, una
      transacción supervisada en `prod` ✔.
- [ ] README, `Documentacion.md` y el diagrama de capas actualizados.

---

## 8. Qué queda fuera de este refactor (a propósito)

- Pasar a async/reactivo (sería la opción `reactive` del scaffold).
- Extraer `sesiones.py` a un caso de uso (D9).
- Renombrar errores o enums para quitar el nombre del proveedor (D10); va con la
  rama de rieles agnósticos.
- Portar a Java/Spring con el plugin de Gradle.
- Cambiar el comportamiento de negocio, los topes, los prompts o las
  herramientas del agente.

---

### Anexo A: cómo se midió

- El grafo de dependencias se sacó con `ast`, resolviendo los imports relativos,
  sobre los 123 `.py` de `agora/` en `dev@2e743f1`.
- La línea base de pruebas es `python -m pytest tests -q`: 1.117 aprobadas en 96 s
  (Python 3.10, Linux).
- Los accesos directos a repositorios desde los *entry points* se contaron con
  búsquedas sobre `entradas/`.
- Los archivos modificados sin commit se revisaron con
  `git diff --ignore-cr-at-eol`: solo cambian los finales de línea.
