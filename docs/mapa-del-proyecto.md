# Mapa del proyecto tras la etapa 1

Qué corre dónde, qué se guarda dónde, y qué sobra.

---

## 1. ¿Todo el código corre dentro de `agora/`?

**Todavía no, y a propósito.**

Hoy conviven dos árboles con papeles distintos:

| | `boveda/` | `agora/` |
|---|---|---|
| Qué es | Lo que **corre y mueve dinero real** | La casa nueva, en construcción |
| Estado | Estable, verificado en producción | Dominio completo y probado; el resto son interfaces |
| Se usa desde | `python -m boveda.cli ...` | Todavía nada lo invoca |
| Cuándo desaparece | Al final de la etapa 5 | — |

La etapa 1 **no tocó una sola línea de `boveda/`**. Eso fue deliberado: es el
código que ya hizo una transferencia real y no hay ninguna razón para arriesgarlo
mientras se construye su reemplazo.

El puente entre los dos es `tests/test_compat_v1.py`, que genera mandatos con el
código v1 **de verdad** y comprueba que el lector v2 produce el mismo veredicto
en los mismos escenarios. Sin esa prueba, la etapa 2 sería un acto de fe.

**Después de la etapa 5:** todo vive en `agora/`, `boveda/` desaparece, y el CLI
pasa a ser `agora/entradas/cli/`.

### Sobre el verificador (tu punto 3)

Dijiste "mantener el verificador de mandato v2 de aquí en adelante". Quiero
asegurarme de que quedamos en lo mismo, porque son dos cosas distintas:

- **Mandatos nuevos: siempre v2.** Sí, de acuerdo. Nada emite v1 nunca más.
- **Mandatos viejos: se siguen pudiendo verificar con las reglas v1.**

Lo segundo no es opcional aunque no vuelvas a emitir un v1. Los mandatos que ya
están en `boveda/secretos/estado.json` se firmaron sobre una carga canónica
distinta; con el verificador v2 **no validan**, no porque estén mal sino porque
son otro documento. Y ese es el mandato del experimento del que salió tu
resultado de los 15.000 COP.

Una evidencia que no se puede reverificar deja de ser evidencia. Por eso
`compat.py` existe y por eso **no** tiene una función que "migre" un v1 a v2:
reescribir la carga rompería la firma, y una función que ofreciera eso estaría
mintiendo.

Si prefieres cortar por lo sano y declarar que los mandatos v1 ya no valen como
evidencia, se puede — pero es una decisión que conviene tomar a propósito, no
por omisión. Dime y borro `compat.py`.

---

## 2. ¿Qué se guarda en la bóveda?

"Bóveda" son dos cosas y conviene separarlas.

### `boveda/` — el paquete de código

```
__init__.py        exports
cli.py             las dos fases desde la terminal
enrolamiento.py    Fase A: push de Nequi, fuente de pago, revocacion
mandato.py         el modelo v1 firmado
nucleo.py          Fase B: cobro contra Wompi, topes duros
eventos.py         receptor de webhooks
```

### `boveda/secretos/` — lo que no se versiona

Ya está en tu `.gitignore`. Es lo que de verdad hay que cuidar:

| Archivo | Qué guarda | Si se pierde | Si se filtra |
|---|---|---|---|
| `firma.sk` | Llave privada ed25519 del titular | Ningún mandato existente vuelve a validar. **La evidencia se cae.** | Alguien puede firmar mandatos a tu nombre |
| `firma.pk` | Llave pública | Se deriva de `.sk` | Nada, es pública |
| `estado.json` | Mandatos firmados, consumo por mandato, gasto del día, modo de cada mandato | Se pierden los topes acumulados: un mandato agotado vuelve a estar fresco | Se ve tu `payment_source_id` |
| `fuentes.json` | Fuentes de pago vivas, separadas por modo | Hay que re-enrolar | **Lo peor de todo.** El `payment_source_id` es la credencial que permite cobrar |

### `boveda/` — evidencia, no logs

| Archivo | Qué es |
|---|---|
| `recibos.jsonl` | **El resultado experimental.** Cada decisión de la bóveda con lo que el mandato decía al lado. Aquí está la corrida de los 15.000 aprobados con tres violaciones |
| `eventos.jsonl` | Webhooks recibidos, con si el checksum validó |

`recibos.jsonl` no es un log de aplicación. No se rota, no se trunca, y si algún
día se migra a la base **el original se conserva igual**.

### A dónde va todo esto en la v2

| Hoy | Etapa | Mañana |
|---|---|---|
| `secretos/firma.sk` | 5 | Se queda ahí, o pasa al dispositivo del titular / un HSM |
| `secretos/estado.json` | 3 | SQLite: tablas `mandato`, `reserva`, `consumo` |
| `secretos/fuentes.json` | 3 | SQLite: tabla `medio_de_pago` |
| `recibos.jsonl` | — | **Se queda como está.** Es el registro histórico |
| `eventos.jsonl` | 4 | SQLite: tabla `evento_pasarela`, conservando el cuerpo crudo |

---

## 3. Qué ya no hace falta

Cuatro categorías. Sólo la primera se borra hoy.

### Borrar ya

| Ruta | Por qué |
|---|---|
| `boveda/ledger_mandatos.jsonl` | Lo escribía el módulo `mandato/` que ya borraste. Huérfano |
| `boveda/mnd-b32152348c904617.json` | Un mandato suelto de esa misma entrega. Está duplicado dentro de `estado.json` |
| `data/private/wompi_source.json` | Caché de fuente de pago anterior a `secretos/fuentes.json`. Superado, y **contiene un `payment_source_id`** |
| `data/private/LEER.md` | Habla de `agora/eval/`, `world/`, `shopper/`, `risk/` — es del otro proyecto AGORA. Confunde el mapa, sobre todo ahora que el paquete nuevo también se llama `agora` |
| `wompi_lab/source.json` | Fuente de pago de sandbox, superada por `fuentes.json` |
| `.pytest_cache/`, `__pycache__/` | Regenerables |

`data/` queda vacía y se puede borrar entera.

### Congelar, no borrar

| Ruta | Por qué |
|---|---|
| `wompi_lab/payouts.py` | Es el **único** sitio del repo con la ruta de dispersión Bre-B. No corre en el flujo, pero rehacerlo costaría un día. Mover a `docs/referencia/` o dejar quieto con un aviso en el encabezado |
| `wompi_lab/ledger.jsonl` | Registro de las corridas de sandbox. Evidencia temprana |

### Se va sola en su etapa

| Ruta | Etapa |
|---|---|
| `wompi_lab/lab.py` | 2 — lo reemplaza el adaptador Wompi |
| `boveda/mandato.py` | 2 — ya está en `agora/dominio/mandato/` |
| `boveda/nucleo.py` | 2 y 3 — se parte en caso de uso + adaptador + repositorios |
| `boveda/enrolamiento.py` | 2 |
| `boveda/eventos.py` | 4 |
| `boveda/cli.py` | 5 — pasa a `agora/entradas/cli/` |

No borres nada de esta lista todavía. Es lo que corre.

### Tú decides

| Ruta | Comentario |
|---|---|
| `Plantilla Informe de tendencias 2026.pdf` | 2,8 MB, no es código y no lo referencia nada. Si es la plantilla para reportar resultados, quizá va mejor fuera del repo |
| `.agentic-fraud-venv/` | Ya está en `.gitignore`. Ocupa disco, se recrea con `requirements.txt` |

---

## Cómo borrar

El puente hacia tu máquina **puede escribir pero no borrar**, así que esto lo
tienes que correr tú. `scripts/limpiar.ps1` hace la primera categoría:

```powershell
.\scripts\limpiar.ps1          # muestra lo que haria, sin tocar nada
.\scripts\limpiar.ps1 -Aplicar # borra
```

Mueve todo a `_a_borrar/` con marca de tiempo en vez de destruirlo, para que
puedas mirar antes de vaciar la papelera.

---

## El árbol tras la limpieza

```
poc-agentic-commerce-fraud/
├── agora/                    la casa nueva
│   ├── dominio/                PURO — completo y probado (etapa 1)
│   │   ├── comun/                dinero, identidad, errores
│   │   ├── mandato/              modelo v2, politica, compat v1
│   │   ├── catalogo/             comercio, producto, carrito
│   │   └── pago/                 MedioDePagoRef, orden, topes duros
│   ├── puertos/                interfaces (etapa 1)
│   ├── aplicacion/             EjecutarIntencion (esqueleto)
│   ├── adaptadores/            vacio — etapas 2 y 3
│   ├── agente/                 herramientas + frontera (esqueleto)
│   ├── entradas/               vacio — etapa 5
│   └── composicion/            vacio — etapa 2
│
├── boveda/                   lo que corre hoy y mueve dinero
│   ├── secretos/               NO se versiona
│   └── recibos.jsonl           la evidencia
│
├── wompi_lab/                congelado (payouts.py: Bre-B)
├── docs/
├── tests/                    125 pruebas
├── scripts/
├── README.md
└── requirements.txt
```

---

## Qué sigue

La etapa 2 parte `Boveda` en un caso de uso y un adaptador, y escribe la pasarela
simulada con los cuatro desenlaces —incluido el rechazo por antifraude—. Al
terminarla, `boveda/nucleo.py` deja de ser el camino y pasa a ser el respaldo.

Es la primera etapa que toca el código que mueve dinero. Con las 125 pruebas y la
equivalencia v1 probada, el riesgo está acotado; sin ellas, no lo estaría.
