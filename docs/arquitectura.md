# Arquitectura de agora

agora sigue la **Clean Architecture de Bancolombia**
([Clean Architecture — Aislando los detalles](https://medium.com/bancolombia-tech/clean-architecture-aislando-los-detalles-4f9530f35d7a))
llevada a Python. Este documento explica la forma del sistema y las decisiones
(ADRs) detrás de cada pieza. El detalle de cada módulo está en
[`../Documentacion.md`](../Documentacion.md); los diagramas, en
[`diagramas/`](diagramas/).

---

## 1. El principio rector

Todo lo demás sale de aquí:

> **El agente propone. El humano firma. El motor de pagos ejecuta.**
> Ninguno de los tres puede hacer el trabajo de otro.

- **El agente** (`usecase/agente/`) navega el catálogo, arma un carrito y
  *propone* un mandato. No tiene la llave de firma ni ve un medio de pago.
- **El humano** firma esa propuesta con su propia llave ed25519, desde el chat
  web o la CLI (`EmitirMandatoUseCase`).
- **El motor de pagos** (`EjecutarIntencionUseCase` + `TopesDuros` + la
  pasarela) revisa el mandato firmado antes de mover un peso.

No es una convención: `tests/arquitectura/test_fronteras.py` lee el AST de
cada módulo y falla el build si el agente puede alcanzar una pasarela, una
llave o un caso de uso que no le corresponde. Si la separación dependiera de
que nadie se equivoque escribiendo un `import`, no sería un argumento — sería
una promesa.

---

## 2. Los módulos y la regla de dependencia

Las flechas apuntan siempre hacia adentro: el dominio no sabe que existe el
mundo exterior.

```
        applications/app-service           el único que conoce a todos:
        (main + config)                    lee el entorno, arma e inyecta
                 │
     ┌───────────┼────────────────────────────┐
     ▼           ▼                            ▼
 infrastructure/entry-points       infrastructure/driven-adapters
 (api-rest, webhook-wompi, cli)    (wompi, simulada, sqlite, deepseek…)
     │ delegan en                         │ implementan
     ▼                                    ▼
 ┌──────────────────────────────┐   ┌──────────────────────────────┐
 │ domain/usecase               │──►│ domain/model                 │
 │ casos de uso + agente/       │   │ entidades + gateways         │
 └──────────────────────────────┘   └──────────────────────────────┘
```

| Módulo | Puede depender de | Nunca depende de |
|---|---|---|
| `domain/model` | solo `model` y la biblioteca estándar | todo lo demás |
| `domain/usecase` | `model` | adaptadores, entry points, app-service, **el agente** |
| `domain/usecase/agente` | `model` y el propio agente | **cualquier otro caso de uso**, adaptadores, gateways de pago, firma o llaves, `importlib` |
| `infrastructure/driven-adapters/*` | `model` y su propia librería | casos de uso, el agente, otros adaptadores, entry points |
| `infrastructure/entry-points/*` | `usecase` y `model` | adaptadores, otros entry points, app-service, repositorios |
| `applications/app-service` | todo | — |

Las filas del agente y de los entry points son las que hacen defendible la
PoC. `tests/arquitectura/test_fronteras.py` es el `validateStructure` del
proyecto: verifica cada fila, confina cada librería de infraestructura a su
módulo (`httpx` solo en `pasarela-wompi`, `langgraph` solo en
`orquestacion-langgraph`…) y prueba, con un árbol de mentira por regla, que
detecta las violaciones.

---

## 3. Estructura de carpetas

```
applications/app-service/src/agora/
├── __init__.py          el paquete `agora`: enchufa los demás módulos a agora.__path__
├── __main__.py          python -m agora <perfil>
└── app_service/
    ├── main.py          perfiles: api | webhook | cli | crear-usuario | generar-catalogo
    ├── servir_api.py · servir_webhook_wompi.py · crear_usuario.py · generar_catalogo_semilla.py
    └── config/          configuracion.py (el .env) · contenedor.py · agente.py

domain/model/src/agora/model/            entidades, objetos de valor y gateways
├── commons/             Dinero, identidades, errores · gateways: Reloj, GeneradorIds, Bitacora
├── mandato/             Mandato, PropuestaDeMandato, Intencion, Dictamen
│   └── gateways/        repositorios (mandatos, propuestas, LibroDeConsumo) · firma
├── pago/                MedioDePagoRef, OrdenDeCobro, ResultadoCobro, TopesDuros
│   └── gateways/        pasarela (PasarelaDePagos, SelectorDePasarela) · repositorios
├── catalogo/            Comercio, Producto, Carrito
│   └── gateways/        catalogo · busqueda_productos · repositorios (carritos)
├── usuario/             Usuario
│   └── gateways/        autenticacion · repositorios (usuarios, llaves)
└── agente/              TipoDeIntencion, ContextoInyectado
    └── gateways/        modelo_lenguaje · orquestacion · recuperacion

domain/usecase/src/agora/usecase/        un caso de uso por carpeta: <caso>/<caso>_use_case.py
├── ejecutar_intencion/  el motor de pagos
├── pagar_carrito/ · emitir_mandato/ · rechazar_propuesta/ · conciliar_evento/ · consultar_estado/
├── iniciar_enrolamiento/ · consultar_enrolamiento/ · confirmar_enrolamiento/ · enrolar_medio/ · revocar_medio/
├── registrar_usuario/ · iniciar_sesion/ · navegar_catalogo/ · generar_catalogo_semilla/
├── listar_mandatos/ · listar_medios_vivos/
└── agente/              FRONTERA DURA: conversación, grafo del turno, herramientas, pausa, traza

infrastructure/driven-adapters/<modulo>/src/agora/driven_adapters/<paquete>/
    pasarela-wompi · pasarela-simulada · selector-pasarelas
    persistencia-sqlite · persistencia-memoria · catalogo-semilla
    llm-deepseek · embeddings-openai · recuperacion-langchain
    busqueda-semantica-memoria · orquestacion-langgraph
    firma-ed25519 · hasher-pbkdf2 · bitacora-jsonl · sistema

infrastructure/entry-points/<modulo>/src/agora/entry_points/<paquete>/
    api-rest (+ estatico/chat.html) · webhook-wompi · cli

tests/   arquitectura · model · usecase · usecase/agente · driven_adapters · entry_points · app_service
```

Cada módulo del scaffold tiene su código en `src/agora/` y todos aportan
subpaquetes al mismo paquete `agora` (`agora.model`, `agora.usecase`,
`agora.driven_adapters.*`…). El `__init__.py` del app-service los encuentra
solos: agregar un adaptador no obliga a tocar ninguna lista.

---

## 4. Los gateways

Las interfaces son `typing.Protocol`: ningún adaptador hereda de nada.

```python
# model/pago/gateways/pasarela.py
class PasarelaDePagos(Protocol):
    def preparar_medio(self, solicitud: SolicitudEnrolamiento) -> MedioEnProceso: ...
    def estado_medio_por_token(self, token: str) -> EstadoMedio: ...
    def confirmar_medio(self, token: str, correo: str) -> EstadoMedio: ...
    def revocar_medio(self, ref: MedioDePagoRef) -> EstadoMedio: ...
    def cobrar(self, orden: OrdenDeCobro) -> ResultadoCobro: ...
    def consultar_cobro(self, id_externo: str) -> ResultadoCobro: ...

class SelectorDePasarela(Protocol):
    def para(self, comercio_id: str) -> PasarelaDePagos: ...
```

Ningún método bloquea esperando un estado final: el cobro devuelve
`PENDING` y el desenlace llega por webhook. Hay dos implementaciones,
`pasarela-wompi` (dinero real, credenciales por comercio) y
`pasarela-simulada`, y `selector-pasarelas` resuelve cuál corresponde a cada
comercio (ADR-8).

```python
# model/mandato/gateways/repositorios.py
class LibroDeConsumo(Protocol):
    def reservar(self, mandato, intencion_id, monto: Dinero, tope_dia: Dinero) -> Reserva: ...
    def confirmar(self, reserva: Reserva) -> None: ...
    def liberar(self, reserva: Reserva) -> None: ...
```

**El consumo se reserva antes de cobrar y se confirma después.** La reserva es
una escritura condicional atómica: si dos cobros compiten por el último tramo
del tope diario, uno gana y el otro recibe `TopeAgotado`. Con
"leer → sumar → escribir" pasarían los dos.

```python
# model/agente/gateways/modelo_lenguaje.py
class ModeloDeLenguaje(Protocol):
    def generar(self, sistema: str, instruccion: str) -> str: ...
    def responder(self, mensajes, herramientas) -> RespuestaModelo: ...
```

DeepSeek entra detrás de un gateway, no importado directo: se puede cambiar
de modelo sin tocar el agente, y probar el agente sin llamar a nadie. Lo mismo
vale para LangGraph (`CompiladorDeGrafos`), los embeddings
(`ProveedorDeEmbeddings`) y la búsqueda documental (`BuscadorDocumental`).

---

## 5. Lo que el agente puede hacer, y lo que no

**Herramientas que recibe** (`usecase/agente/herramientas.py`):

| Herramienta | Devuelve |
|---|---|
| `buscar_comercios(consulta)` | lista de comercios |
| `buscar_productos(comercio_id, consulta, filtros)` | lista de productos |
| `ver_producto(producto_id)` | detalle y precio |
| `armar_carrito(comercio_id, items)` | `carrito_id` + **propuesta de mandato sin firmar** |
| `pagar(mandato_id, carrito_id)` | resultado del cobro (puede quedar pendiente) |
| `consultar_estado(intencion_id)` | pendiente / aprobado / rechazado + motivo |

**Lo que no recibe, y por qué:**

- **Nada que firme.** La llave del titular no está a su alcance.
- **Nada que revele el medio de pago.** Maneja `mandato_id` opacos; nunca ve
  un `payment_source_id`.
- **Nada que enrole, revoque o toque credenciales de identidad.** Son actos del
  titular. `PROHIBIDAS` se valida al arrancar el proceso.
- **Nada que cree un mandato.** Puede *proponerlo*; firmarlo es del humano.

`pagar()` sí está, y es deliberado: el agente actúa, pero solo dentro de un
límite que otra persona firmó. Las seis herramientas son funciones que arma
`app_service/config/agente.py` cerrando sobre los casos de uso reales; el
agente nunca importa un caso de uso.

### El paso que no puede automatizarse

```
agente → armar_carrito(...) → propuesta_de_mandato
                                      │
                              ╔═══════▼═══════╗
                              ║  EL HUMANO    ║   ← el turno se DETIENE aquí
                              ║    FIRMA      ║      (pausa tipada, popup)
                              ╚═══════╤═══════╝
                                      │
                                 mandato_id
                                      │
agente → pagar(mandato_id, carrito_id) → PagarCarritoUseCase → motor de pagos
```

Es el **Cart Mandate** de AP2: lo que el agente propuso, al lado de lo que el
humano firmó, al lado de lo que la pasarela hizo. Cuando no coinciden, ahí
está el hallazgo. El grafo del turno se detiene en un nodo dedicado
(`espera_humana`) y no se sale de ahí sin que una persona haga clic — ver
[`arquitectura-agentes/`](arquitectura-agentes/README.md).

---

## 6. El flujo completo

```
1. El titular inicia sesión           → IniciarSesionUseCase (usuario + contraseña)
2. Enrola su Nequi para un comercio   → Iniciar/Consultar/ConfirmarEnrolamiento → MedioDePagoRef
3. Chatea con el agente               → grafo del turno + ModeloDeLenguaje
4. El agente navega el catálogo       → NavegarCatalogoUseCase (tres peldaños)
5. El agente arma un carrito          → Carrito + PropuestaDeMandato (sin firmar)
6. El turno se detiene; popup         → la persona revisa ítems, monto y vigencia
7. El titular firma                   → EmitirMandatoUseCase → Mandato (ed25519)
8. El agente pide pagar               → PagarCarritoUseCase → EjecutarIntencionUseCase
     8a. TopesDuros                   → nunca se apagan
     8b. LibroDeConsumo.reservar      → atómico
     8c. Política de mandato          → PERMITIR / CONFIRMAR / BLOQUEAR
     8d. Pasarela.cobrar              → PENDING, devuelve ya
9. Wompi manda transaction.updated    → webhook → ConciliarEventoUseCase → confirma o libera
10. El chat se entera                 → sondeo de pendientes + SSE → el agente cuenta el desenlace
```

Si 8c da `CONFIRMAR`, la reserva queda viva hasta que una persona decide
(popup web o `cli retomar`), y al decidir se vuelven a evaluar todos los
controles.

---

## 7. Decisiones y su porqué

**ADR-1 · Un solo proceso de aplicación, frontera verificada por prueba.**
Un servicio separado para el motor de pagos daría una frontera más fuerte,
pero duplica despliegue, autenticación y observabilidad para una demo. La
prueba de fronteras da la mayor parte de la garantía a una fracción del
costo. *Revisar si la demo pasa a piloto con usuarios reales.*

**ADR-2 · La pasarela simulada es ciudadana de primera, no un mock.**
`pasarela-simulada` se elige por configuración y reproduce los cuatro
desenlaces de Wompi (aprobado, declinado, declinado por antifraude,
pendiente). Permite demostrar sin gastar y reproducir el rechazo del
antifraude de Wompi a voluntad.

**ADR-3 · SQLite, no archivos JSON ni Postgres.**
Un archivo JSON no sobrevive concurrencia. Postgres es infraestructura que la
demo no necesita. SQLite en modo WAL da transacciones reales y cero operación;
los gateways permiten migrar sin tocar los casos de uso.

**ADR-4 · Mandato con referencia de medio de pago opaca y versionado.**
El mandato referencia el medio como `MedioDePagoRef(proveedor, ambiente,
id_externo)` y lleva su `version` dentro de la carga firmada: una carga
firmada nunca se reinterpreta bajo otras reglas. Un cambio en la carga exige
una versión nueva y conservar el verificador de la anterior, porque los
mandatos ya firmados son evidencia y tienen que poder reverificarse
(`tests/arquitectura/test_invariantes_del_refactor.py` lo cuida).

**ADR-5 · `Dinero` en vez de `int`.**
Centavos y moneda explícitos, en un tipo inmutable. Elimina una clase entera
de errores (mezclar pesos con centavos) en el punto donde más caros son.

**ADR-6 · Idempotencia derivada de la intención.**
La referencia del cobro sale de `intencion_id`, no de un uuid nuevo por
intento. Reintentar no puede duplicar un cobro.

**ADR-7 · Los topes duros son constantes en código.**
20.000 COP por transacción y 100.000 COP por día (`model/pago/topes.py`). Si
fueran configurables, apagar el mandato para medir su efecto apagaría también
la protección del dinero real.

**ADR-8 · Multi-comercio: vinculación medio↔comercio procedimental.**
Un `payment_source_id` de Wompi queda atado al comercio que lo creó.
`RepositorioMedios` guarda con qué `comercio_id` se vinculó cada medio y
`EmitirMandatoUseCase` exige ese vínculo antes de firmar. La alternativa —
meter el `comercio_id` dentro de `MedioDePagoRef`, es decir, dentro de la
carga firmada— exigiría una versión nueva del mandato (ADR-4). Se eligió la
opción liviana porque `EmitirMandatoUseCase` es el único punto que construye
un `Mandato` de verdad. Es deuda técnica consciente: la correspondencia no
viaja dentro de la firma ni se reverifica al cobrar (ver
[`flujo-propuesta-mandato.md`](flujo-propuesta-mandato.md), sección 6).

**ADR-9 · Clean Architecture de Bancolombia, en Python.**
La estructura de módulos, la nomenclatura (`model`, `gateways`, `usecase`,
`driven-adapters`, `entry-points`, `app-service`) y las reglas de dependencia
siguen el scaffold de la organización; el lenguaje de negocio se queda en
español porque viaja dentro de la firma y de lo que ve el agente. El
`validateStructure` es `tests/arquitectura/test_fronteras.py`, con una regla
más estricta que la del scaffold para el agente (no puede llamar a ningún
otro caso de uso).

---

## 8. Cómo se verifica

```bash
python -m pytest -q
```

Corre la suite completa y, con ella, `tests/arquitectura/`:

- `test_fronteras.py` — la regla de dependencia de la sección 2, la frontera
  del agente, una librería por módulo, la convención
  `usecase/<caso>/<caso>_use_case.py`, y un detector probado para cada regla.
- `test_invariantes_del_refactor.py` — lo que ninguna reorganización puede
  cambiar: que un mandato firmado y guardado siga verificando, que los errores
  que lee el agente mantengan nombre y `reintentable`, y que las rutas de datos
  (`agora_datos/agora.db`, el corpus de soporte) se resuelvan desde la raíz
  del repositorio.

---

## 9. Lo que no se hace, a propósito

- **No hay ORM.** Los repositorios son unas pocas tablas; SQLAlchemy agregaría
  más concepto del que quita a esta escala.
- **El agente no es asíncrono.** Un turno de chat es secuencial por
  naturaleza. La asincronía que hace falta es en el cobro (webhook), no en el
  modelo.
- **La pasarela no se abstrae más allá de lo que existe.** Con Wompi y la
  simulada el gateway está justificado; una tercera hipotética lo volvería
  especulativo.
- **Los topes duros no se mueven a configuración.** Ver ADR-7.
- **La bitácora de cobros no se borra ni se "migra".** `agora_datos/recibos.jsonl`
  es el resultado experimental, no un log de aplicación.
