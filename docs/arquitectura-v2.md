# Arquitectura v2 — de PoC a app demostrativa

**Propuesta de refactorización** · 19 de agosto de 2026

Objetivo: una app donde un agente con DeepSeek V4 navega comercios simulados por
chat y el pago final sale de una cuenta Nequi real vía mandatos firmados.

Diagramas: `docs/diagramas/`. Análisis del código actual: `docs/analisis-codigo.md`.

---

## 1. El principio rector

Todo lo demás sale de aquí:

> **El agente propone. El humano firma. La bóveda ejecuta.**
> Ninguno de los tres puede hacer el trabajo de otro.

Tu código ya lo dice como intención (`nucleo.py:3-7`). La refactorización lo
vuelve **estructural**: el paquete del agente no puede ni siquiera importar el
módulo que habla con Wompi, y hay una prueba que falla el build si alguien lo
intenta.

Eso importa más que la limpieza. El argumento central de la PoC es que la
separación existe y es verificable. Si depende de que nadie se equivoque
escribiendo un `import`, no es un argumento — es una promesa.

---

## 2. Las capas y la regla de dependencia

Las flechas apuntan siempre hacia adentro. Nada del núcleo sabe que existe el
mundo exterior.

```
        entradas/          composicion/
       (cli, api, web,     (composition root:
        webhooks)           el unico que arma todo)
              │                    │
              ▼                    ▼
        ┌──────────────────────────────────┐
        │          aplicacion/             │  casos de uso
        │   EjecutarIntencion, Enrolar...  │
        └──────────────────────────────────┘
              │                    ▲
              ▼                    │ implementan
        ┌───────────┐        ┌──────────────┐
        │ puertos/  │◄───────│ adaptadores/ │  wompi, simulada,
        │ (Protocol)│        │              │  sqlite, deepseek
        └───────────┘        └──────────────┘
              │
              ▼
        ┌──────────────────────────────────┐
        │           dominio/               │  puro. sin IO.
        │  Mandato, Intencion, Dinero...   │
        └──────────────────────────────────┘
```

| Paquete | Puede importar | Nunca importa |
|---|---|---|
| `dominio/` | sólo `dominio/` | todo lo demás |
| `puertos/` | `dominio/` | `aplicacion/`, `adaptadores/` |
| `aplicacion/` | `dominio/`, `puertos/` | **`adaptadores/`** |
| `adaptadores/` | `dominio/`, `puertos/` | `aplicacion/`, `entradas/` |
| `agente/` | `dominio/` (tipos), `puertos/` | **`adaptadores/pasarelas/`**, todo lo que tenga credenciales |
| `entradas/` | `aplicacion/`, `dominio/` | `adaptadores/` (los recibe armados) |
| `composicion/` | todo | — |

Las dos filas en negrita son las que hacen la PoC defendible. `tests/test_fronteras.py`
las verifica con AST — no con convención.

---

## 3. Estructura de carpetas

```
agora/
├── dominio/                     PURO — sin httpx, sin fastapi, sin os.environ
│   ├── comun/
│   │   ├── dinero.py            Dinero: centavos + moneda. Nunca un int suelto
│   │   ├── identidad.py         MandatoId, IntencionId, ComercioId (NewType)
│   │   └── errores.py           jerarquia de errores del dominio
│   ├── mandato/
│   │   ├── modelo.py            Mandato, Intencion, Consumo, Violacion
│   │   ├── politica.py          evaluar() -> Dictamen
│   │   └── canonico.py          serializacion firmable, versionada
│   ├── catalogo/
│   │   └── modelo.py            Comercio, Producto, Carrito, ItemCarrito
│   └── pago/
│       ├── modelo.py            MedioDePagoRef, OrdenDeCobro, ResultadoCobro
│       └── topes.py             TopesDuros — el guardarrail no configurable
│
├── puertos/                     interfaces. typing.Protocol, sin implementacion
│   ├── pasarela.py              PasarelaDePagos
│   ├── repositorios.py          RepositorioMandatos, RepositorioMedios, LibroDeConsumo
│   ├── catalogo.py              RepositorioCatalogo
│   ├── modelo_lenguaje.py       ModeloDeLenguaje
│   ├── firma.py                 Firmante, Verificador
│   └── sistema.py               Reloj, GeneradorIds, Bitacora
│
├── aplicacion/                  casos de uso. orquestan, no deciden reglas
│   ├── enrolar_medio.py
│   ├── emitir_mandato.py
│   ├── ejecutar_intencion.py    el corazon
│   ├── revocar_medio.py
│   ├── conciliar_evento.py      webhook -> estado
│   └── navegar_catalogo.py
│
├── adaptadores/
│   ├── pasarelas/
│   │   ├── wompi/               dinero real
│   │   └── simulada/            demos y pruebas. ciudadano de primera
│   ├── persistencia/
│   │   ├── sqlite/              con transacciones de verdad
│   │   └── memoria/             pruebas
│   ├── llm/
│   │   └── deepseek/            V4-Pro / V4-Flash, API compatible con OpenAI
│   ├── catalogo/
│   │   └── semilla/             comercios simulados
│   └── sistema/                 reloj real, uuid real, bitacora
│
├── agente/                      FRONTERA DURA — sin credenciales, sin pasarelas
│   ├── herramientas.py          las tool defs que ve el LLM
│   ├── conversacion.py          el loop de turnos
│   └── politica.py              system prompt y limites
│
├── entradas/
│   ├── cli/                     lo que hoy es boveda/cli.py
│   ├── api/                     FastAPI: REST + SSE para el chat
│   └── webhooks/                lo que hoy es boveda/eventos.py
│
└── composicion/
    └── contenedor.py            el unico sitio que lee el entorno y arma todo
```

---

## 4. Los puertos

Cinco interfaces sostienen el diseño. Con `typing.Protocol` no hace falta que los
adaptadores hereden de nada.

```python
# puertos/pasarela.py
class PasarelaDePagos(Protocol):
    def preparar_medio(self, solicitud: SolicitudEnrolamiento) -> MedioEnProceso: ...
    def estado_medio(self, ref: MedioDePagoRef) -> EstadoMedio: ...
    def revocar_medio(self, ref: MedioDePagoRef) -> EstadoMedio: ...
    def cobrar(self, orden: OrdenDeCobro) -> ResultadoCobro: ...
    def consultar_cobro(self, id_externo: str) -> ResultadoCobro: ...
```

Dos implementaciones desde el día uno: `wompi/` y `simulada/`. La simulada no es
un mock de pruebas — es un adaptador de producción para el modo demo, y por eso
tiene que soportar los mismos desenlaces: aprobado, declinado, **declinado por
antifraude** y pendiente.

Esa última capacidad es la que te deja demostrar el hallazgo del AFE en una
presentación sin depender de que Wompi coopere ese día.

```python
# puertos/repositorios.py
class LibroDeConsumo(Protocol):
    def reservar(self, mandato_id, monto: Dinero, tope_dia: Dinero) -> Reserva: ...
    def confirmar(self, reserva: Reserva) -> None: ...
    def liberar(self, reserva: Reserva) -> None: ...
```

**El consumo se reserva antes de cobrar y se confirma después.** No es
ceremonia: es lo que arregla el problema 2 del análisis. La reserva es una
escritura condicional atómica; si dos cobros concurrentes compiten por el último
tramo del tope diario, uno gana y el otro recibe `TopeAgotado`. Con
`leer → sumar → escribir` los dos pasan.

```python
# puertos/modelo_lenguaje.py
class ModeloDeLenguaje(Protocol):
    def responder(
        self, mensajes: list[Mensaje], herramientas: list[Herramienta]
    ) -> RespuestaModelo: ...
```

DeepSeek detrás de un puerto, no importado directo. Su API es compatible con
ChatCompletions de OpenAI, así que el adaptador es fino — pero el puerto te deja
cambiar de modelo sin tocar el agente, y probar el agente sin llamar a nadie.

---

## 5. La decisión central: qué puede y qué no puede el agente

Esto es lo que hay que diseñar con cuidado. Todo lo demás es acomodo de carpetas.

**Herramientas que el agente recibe:**

| Herramienta | Devuelve |
|---|---|
| `buscar_comercios(consulta)` | lista de comercios |
| `buscar_productos(comercio_id, consulta)` | lista de productos |
| `ver_producto(producto_id)` | detalle y precio |
| `armar_carrito(items)` | `carrito_id` + **propuesta de mandato sin firmar** |
| `consultar_estado(intencion_id)` | pendiente / aprobado / rechazado + motivo |
| `pagar(mandato_id, carrito_id)` | resultado del cobro |

**Herramientas que el agente NO recibe, y por qué:**

- **Nada que firme.** La llave del titular no está en su proceso.
- **Nada que revele el medio de pago.** El agente maneja `mandato_id` opacos y
  nunca ve un `payment_source_id`.
- **Nada que enrole ni revoque.** Son actos del titular.
- **Nada que cree un mandato.** Puede *proponer* uno; firmarlo es del humano.

`pagar()` sí está en la lista, y es deliberado: el agente **puede** disparar el
cobro, pero sólo contra un mandato que un humano firmó. Si le quitáramos esa
herramienta, la PoC dejaría de medir lo que quiere medir — el punto es que el
agente actúe solo dentro de un límite, no que no actúe.

### El paso que no puede automatizarse

```
agente → armar_carrito(...) → propuesta_de_mandato
                                      │
                              ╔═══════▼═══════╗
                              ║  EL HUMANO    ║   ← frontera dura
                              ║    FIRMA      ║      UI + llave del titular
                              ╚═══════╤═══════╝
                                      │
                                 mandato_id
                                      │
agente → pagar(mandato_id, carrito_id) → EjecutarIntencion
```

Es el **Cart Mandate** de AP2. Y es lo que hace que la demo se entienda sin
explicarla: en pantalla se ve lo que el agente propuso, al lado de lo que el
humano firmó, al lado de lo que la pasarela hizo. Las tres columnas casi siempre
coinciden — y cuando no, ahí está el hallazgo.

Para el modo experimento se puede exponer un botón que **degrada** el mandato o
salta su verificación, igual que hoy hace `--sin-mandato`. Es el brazo de
comparación y tiene que seguir existiendo.

---

## 6. El flujo completo

```
1. El titular enrola su Nequi          → EnrolarMedio → push → MedioDePagoRef
2. Chatea con el agente                → ModeloDeLenguaje + herramientas
3. El agente navega el catalogo        → RepositorioCatalogo (comercios simulados)
4. El agente arma un carrito           → Carrito + PropuestaDeMandato
5. La app le muestra la propuesta      → UI
6. El titular firma                    → Firmante → Mandato (ed25519)
7. El agente pide pagar                → EjecutarIntencion
     7a. TopesDuros                    → nunca se apagan
     7b. LibroDeConsumo.reservar       → atomico
     7c. PoliticaDeMandato → Dictamen  → PERMITIR / CONFIRMAR / BLOQUEAR
     7d. Pasarela.cobrar               → PENDIENTE, devuelve ya
8. Wompi manda transaction.updated     → ConciliarEvento → confirma o libera
9. El chat se entera por SSE           → el agente cuenta el desenlace
```

Los pasos 7d y 8 son el cambio grande frente a hoy: nada bloquea 60 segundos, y
el webhook —que ya recibes y no lees— pasa a ser el camino principal.

---

## 7. Decisiones y su porqué

**ADR-1 · Un solo proceso, frontera verificada por prueba.**
Un servicio separado para la bóveda daría una frontera más fuerte, pero duplica
despliegue, autenticación y observabilidad para una demo. La prueba de fronteras
da el 80% de la garantía al 5% del costo. *Revisar si la demo pasa a piloto con
usuarios reales.*

**ADR-2 · La pasarela simulada es ciudadano de primera, no un mock.**
Vive en `adaptadores/pasarelas/simulada/` y se elige por configuración. Permite
demostrar sin gastar, reproducir el rechazo del AFE a voluntad, y correr pruebas
de integración sin red.

**ADR-3 · SQLite, no un JSON, y no Postgres todavía.**
El JSON no sobrevive concurrencia. Postgres es infraestructura que la demo no
necesita. SQLite en modo WAL da transacciones reales y cero operación. La
interfaz `LibroDeConsumo` deja migrar sin tocar los casos de uso.

**ADR-4 · Mandato v2 con referencia de medio de pago opaca.**
`fuente_pago: int` se vuelve `medio: MedioDePagoRef(proveedor, id_externo)`.
Cambia la carga firmada, así que el mandato se versiona y **el verificador de v1
se conserva** — los mandatos ya firmados tienen que seguir validando. Esa
compatibilidad no es cortesía: `recibos.jsonl` es evidencia y debe poder
reverificarse.

**ADR-5 · `Dinero` en vez de `int`.**
Hoy conviven pesos (`monto_cop`) y centavos (`amount_in_cents`) con
multiplicaciones sueltas en la frontera. Un tipo con moneda y unidad explícitas
elimina una clase entera de errores en el punto donde más caros son.

**ADR-6 · Idempotencia derivada de la intención.**
La referencia sale de `intencion_id`, no de un uuid nuevo. Reintentar deja de
poder duplicar un cobro.

**ADR-7 · Los topes duros siguen siendo constantes en código.**
Se pueden mover de archivo, no de naturaleza. Si se vuelven configurables, dejan
de ser el guardarraíl que permite estudiar el mandato apagándolo.

---

## 8. Plan de migración

Cinco etapas. Cada una deja el repo funcionando y las pruebas en verde.

| # | Etapa | Qué se toca | Riesgo |
|---|---|---|---|
| 1 | **Sacar el dominio** | `mandato.py` → `dominio/mandato/`, agregar `Dinero`. Sin cambiar comportamiento | Bajo |
| 2 | **Definir puertos y partir `Boveda`** | `PasarelaDePagos`, `LibroDeConsumo`. `Boveda` → `EjecutarIntencion` + adaptador Wompi | Medio |
| 3 | **Persistencia real** | SQLite con reserva/confirmación. Migrar `estado.json` | Medio — hay datos reales |
| 4 | **Async y webhook vivo** | `ConciliarEvento`, quitar el long-polling del camino principal | Medio |
| 5 | **Agente y app** | `agente/`, `entradas/api/`, catálogo semilla, adaptador DeepSeek | Bajo — todo nuevo |

**La etapa 1 se puede hacer hoy y no rompe nada.** La 3 es la única que toca
datos existentes: `boveda/secretos/estado.json` tiene mandatos y consumo reales,
y `recibos.jsonl` es evidencia del experimento. Migración con script y respaldo,
no a mano.

Antes de empezar: **congelar `wompi_lab/` y borrar `mandato/`.** El segundo es
código muerto duplicado; el primero es scratch que vale conservar sólo por la
parte de Bre-B. Juntos son el 45% de las líneas del repo y ninguna se ejecuta en
el flujo real.

---

## 9. Lo que yo no haría

- **No metas un ORM.** Los repositorios son cuatro tablas. SQLAlchemy agrega más
  concepto del que quita a esta escala.
- **No hagas el agente asíncrono todavía.** Un turno de chat es secuencial por
  naturaleza. La asincronía que hace falta es en el cobro, no en el modelo.
- **No abstraigas la pasarela más allá de dos implementaciones.** Con Wompi y la
  simulada el puerto está justificado. Una tercera hipotética lo volvería
  especulativo.
- **No muevas los topes duros a configuración.** Ver ADR-7.
- **No borres `recibos.jsonl` ni lo "migres" a la base sin conservar el original.**
  Es el resultado experimental, no un log de aplicación.
