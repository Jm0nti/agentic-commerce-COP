# El módulo de agentes, de un vistazo

Esta carpeta documenta `usecase/agente/` — cómo un mensaje escrito por una
persona se convierte en una respuesta, y qué puede y qué no puede hacer el
modelo en el medio. 

Los tres diagramas de
abajo estan en orden: el primero dice **qué es**, el segundo **quién decide qué**,
y el tercero explica el único mecanismo que no se adivina mirando el código.

El principio que ordena todo lo demás, y que ninguna etapa tocó:

> **El agente propone. El humano firma. El motor de pagos ejecuta.**

No es una consigna: está verificado estructuralmente. `tests/arquitectura/test_fronteras.py`
lee el AST de cada módulo y falla el build si `usecase/agente/` importa `usecase/`,
`driven_adapters/` o `entry_points/`, o si nombra `langgraph` o `langchain`. El agente
no tiene forma de alcanzar una credencial ni una pasarela, aunque alucine.

---

## 1. El turno como grafo

Un mensaje entra, el **orquestador** clasifica su intención y lo manda a uno
de siete agentes. Cada agente ve **solo** las herramientas de su dominio: el
de soporte no tiene ninguna, el de catálogo no puede cobrar, y solo
`agente_carrito_pago` —en rojo— toca dinero.

Si el turno dejó algo esperando a una persona (una propuesta sin firmar, un
cobro sin confirmar), el grafo se detiene en un nodo dedicado que no hace
nada más que detenerse.

```mermaid
---
title: El turno como grafo · migracion a agentes, etapas 3-5
---
flowchart LR
    IN(["persona<br/>escribe"]) --> ORQ

    ORQ{{"orquestador<br/><i>clasifica la intencion,<br/>arma ruta y contexto</i>"}}

    A1["agente_catalogo<br/><small>buscar_comercios · buscar_productos<br/>ver_producto</small>"]
    A2["agente_carrito_pago<br/><small>las tres de catalogo<br/>+ armar_carrito + pagar</small>"]
    A3["agente_estado<br/><small>consultar_estado</small>"]
    A4["agente_soporte<br/><small>sin herramientas<br/>+ contexto documental</small>"]
    A5["agente_medios_de_pago<br/><small>sin herramientas</small>"]
    A6["agente_fuera_de_alcance<br/><small>sin herramientas</small>"]
    A7["agente_respaldo<br/><small>las seis · el agente de antes</small>"]

    ORQ -->|catalogo| A1
    ORQ -->|carrito_pago| A2
    ORQ -->|estado| A3
    ORQ -->|soporte| A4
    ORQ -->|medios_de_pago| A5
    ORQ -->|fuera_de_alcance| A6
    ORQ -->|"sin certeza"| A7

    A1 --> DEC
    A2 --> DEC
    A3 --> DEC
    A4 --> DEC
    A5 --> DEC
    A6 --> DEC
    A7 --> DEC

    DEC{"¿el turno dejo algo<br/>esperando a una persona?"}
    DEC -->|no| FIN(["FIN"])
    DEC -->|si| ESP

    ESP["<b>espera_humana</b><br/><i>no hace nada mas que detenerse</i><br/>levanta PausaRequerida"]
    ESP --> POP(["popup: la PERSONA<br/>firma o rechaza"])

    classDef orq fill:#3d2f5c,stroke:#9b7fc4,color:#f0e8f8
    classDef dinero fill:#5c2f3d,stroke:#d96f8f,color:#f8e8ee
    classDef agente fill:#5c3d2f,stroke:#d99a6f,color:#f8f0e8
    classDef humano fill:#1e3a5f,stroke:#4a90d9,color:#e8f0f8
    classDef borde fill:#4a4a4a,stroke:#999,color:#eee

    class ORQ orq
    class A2 dinero
    class A1,A3,A4,A5,A6,A7 agente
    class ESP,POP humano
    class IN,FIN,DEC borde
```

Tres cosas que el diagrama no dice y conviene saber:

- **Un agente que recibe la ruta de otro la rechaza.** No es solo que no
  tenga la herramienta: si el grafo lo despacha fuera de su dominio, levanta
  `RutaDeOtroAgente`. Hay una prueba por intención.
- **Una herramienta alucinada se rechaza al ejecutar**, no al ofrecerla. Si
  el modelo inventa un `pagar()` en un turno de soporte, la función real
  nunca corre y queda escrito en la traza con `"fuera_de_ruta": true`.
- **`agente_respaldo` es literalmente el agente anterior a la etapa 1**, con
  las seis herramientas. Cuando el clasificador se abstiene, el turno corre
  como corría antes de toda esta migración. Ese es el piso de seguridad: la
  migración nunca deja al sistema peor que antes de empezar.

## 2. Un turno de punta a punta: quién decide qué

El mismo turno, ahora en el tiempo y con todos los actores. Las tres bandas
de color son las tres frases del principio.

Lo importante está en la banda del medio: **el turno se detiene ahí**. No es
una convención de prompt ni una nota de texto que el modelo tiene que
obedecer — es un punto del grafo del que no se sale sin que una persona haga
clic.

```mermaid
---
title: Un turno de compra de punta a punta · quien decide que
---
sequenceDiagram
    autonumber
    actor T as Titular
    participant UI as Chat web<br/>entry_points/api
    participant GR as Grafo del turno<br/>usecase/agente/grafo.py
    participant MO as DeepSeek<br/>ModeloDeLenguaje
    participant AP as usecase/<br/>casos de uso
    participant BV as Motor de pagos<br/>EjecutarIntencionUseCase
    participant TZ as trazas.jsonl

    rect rgb(253, 245, 235)
    Note over T,TZ: EL AGENTE PROPONE · nunca toca una credencial
    T->>UI: "quiero comprar las gomitas"
    UI->>GR: turno(conversacion, texto)
    GR->>MO: clasificar intencion
    MO-->>GR: carrito_pago · confianza 0.92
    Note right of GR: enruta a agente_carrito_pago:<br/>catalogo + armar_carrito + pagar<br/>y NADA mas
    GR->>MO: responder(historial, SOLO esas herramientas)
    MO-->>GR: armar_carrito(comercio, items)
    GR->>AP: NavegarCatalogoUseCase.armar_carrito
    AP-->>GR: Carrito + PropuestaDeMandato SIN FIRMAR
    MO-->>GR: "te arme la propuesta"
    end

    rect rgb(232, 244, 253)
    Note over T,TZ: EL HUMANO FIRMA · el turno se detiene aqui
    GR->>GR: detectar_pausa -> PausaDelTurno
    GR-xGR: espera_humana levanta PausaRequerida
    GR->>TZ: traza del turno + "pausa": firma_de_propuesta
    GR-->>UI: respuesta + pausa tipada
    UI-->>T: popup con items, monto y justificacion
    Note over T: aqui, y solo aqui,<br/>se decide gastar plata
    T->>UI: click en "Firmar"
    UI->>AP: EmitirMandatoUseCase(propuesta_id, titular_id)
    AP-->>UI: Mandato firmado con la llave del titular
    end

    rect rgb(235, 250, 240)
    Note over T,TZ: EL MOTOR DE PAGOS EJECUTA · contra el mandato, nunca contra el chat
    UI->>GR: reanudar(conversacion, DecisionHumana)
    GR->>MO: responder(+ aviso tipado con mandato_id y carrito_id)
    MO-->>GR: pagar(mandato_id, carrito_id)
    GR->>AP: EjecutarIntencionUseCase
    AP->>BV: verificar los nueve controles del mandato
    BV-->>AP: Dictamen: PERMITIR / CONFIRMAR / BLOQUEAR
    AP-->>GR: Recibo
    GR->>TZ: traza del segundo turno
    GR-->>UI: "listo, ya cobre" (o "quedo esperando confirmacion")
    UI-->>T: resultado
    end

    Note over T,TZ: Si el modelo alucina "pagar" en un turno de soporte,<br/>se rechaza AL EJECUTAR y queda escrito: "fuera_de_ruta": true
```

Notar que **el agente nunca firma**. `PROHIBIDAS` (`usecase/agente/herramientas.py`)
le niega `firmar`, `enrolar`, `revocar` y todo lo que suene a credencial, y
esa lista se valida al arrancar. El modelo pide `pagar(mandato_id, ...)` con
un id que solo existe porque una persona hizo clic; si el mandato no está,
`pagar` no tiene nada que ejecutar.

## 3. Cómo se busca en el catálogo: tres peldaños, no un RAG

El único mecanismo del módulo que no se entiende leyendo una función. Cuando
el modelo llama a `buscar_productos`, la búsqueda baja por tres peldaños y
**para en el primero que encuentra algo**.

```mermaid
---
title: Los tres peldanos de la recuperacion de catalogo · decision 1, etapa 4
---
flowchart LR
    Q(["buscar_productos<br/>(comercio, consulta, filtros)"]) --> P1

    P1["<b>1 · ESTRUCTURADO</b><br/>RepositorioCatalogo.buscar_productos<br/><i>match por substring · auditable<br/>no puede inventar un producto</i>"]
    P1 --> P2
    P2["<b>2 · REGLAS DURAS</b><br/>FiltrosDeProducto.aplicar<br/><i>disponibilidad · rango de precio</i><br/>argumentos de la herramienta,<br/>no prosa del prompt"]
    P2 --> D1{"¿encontro<br/>algo?"}

    D1 -->|si| OUT(["productos"])
    D1 -->|no| D2{"¿hay buscador<br/>semantico?"}
    D2 -->|"no · sin OPENAI_API_KEY"| VACIO(["lista vacia"])
    D2 -->|si| CAND

    CAND["candidatos = TODO el comercio,<br/>ya pasado por las reglas duras"]
    CAND --> P3
    P3["<b>3 · SEMANTICO</b><br/>BuscadorSemanticoDeProductos<br/><i>coseno con numpy · piso 0,31 medido</i><br/><b>solo ordena y recorta</b><br/>no lee el catalogo, no consulta stock"]
    P3 --> OUT

    classDef estructurado fill:#2f4f3d,stroke:#6fbf8f,color:#e8f8ee
    classDef duro fill:#5c2f3d,stroke:#d96f8f,color:#f8e8ee
    classDef semantico fill:#3d2f5c,stroke:#9b7fc4,color:#f0e8f8
    classDef borde fill:#4a4a4a,stroke:#999,color:#eee

    class P1 estructurado
    class P2,CAND duro
    class P3 semantico
    class Q,OUT,VACIO,D1,D2 borde
```

El orden importa y es deliberado. El peldaño 1 es **auditable y no puede
inventar** un producto que no existe; el 3 es el que "entiende" pero también
el que puede equivocarse. Así que el semántico solo corre cuando el
estructurado ya falló, solo ve candidatos que las reglas duras ya
aprobaron, y **solo ordena y recorta** — no puede devolver nada que no
estuviera en la lista que recibió. Hay una prueba de exactamente eso.


## Dónde vive cada cosa

Todo esto es `usecase/agente/`, que no importa `usecase/`, `driven_adapters/`
ni `entry_points/`. Para la vista de capas completa del proyecto, ver
[`../diagramas/01-capas.mermaid`](../diagramas/01-capas.mermaid).

| Módulo | Qué hace | Etapa |
|---|---|---|
| `clasificacion/` (`reglas`, `modelo`, `cadena`) | decide la intención; las reglas primero porque son gratis | 1 |
| `nodos.py`, `intencion.py` | la lista blanca de herramientas por ruta | 1 |
| `contexto_documental.py` | inyecta documentación en turnos de soporte, sin una sola cifra | 2 |
| `grafo.py` | `EstadoDelTurno`, la definición del grafo y `AgenteEnGrafo` | 3 |
| `agentes.py` | los siete agentes especializados y su validación por nodo | 4 |
| `pausa.py` | `PausaDelTurno`, `DecisionHumana` y el aviso tipado | 5 |
| `traza.py` | un evento por turno en `trazas.jsonl` | — |
| `herramientas.py`, `politica.py`, `conversacion.py` | el catálogo, `PROHIBIDAS`, el system prompt y el loop | previas |

Los puertos que el módulo usa (`CompiladorDeGrafos`, `BuscadorDocumental`,
`BuscadorSemanticoDeProductos`, `ModeloDeLenguaje`) viven en `model/<agregado>/gateways/`, y sus
implementaciones —LangGraph, LangChain, OpenAI, numpy— en `driven_adapters/`.
`driven_adapters/orquestacion_langgraph/compilador.py` es el **único**
módulo del proyecto que importa `langgraph`.

## Los documentos

| Documento | De qué trata |
|---|---|
| [`arquitectura-agentes-langgraph.md`](arquitectura-agentes-langgraph.md) | El diseño: las ocho decisiones y el plan de cinco etapas |
| [`validacion-con-modelos-reales.md`](validacion-con-modelos-reales.md) | **La medición contra DeepSeek y OpenAI reales**, y lo que reveló |
| [`etapa-1-agentes-clasificador-de-intencion.md`](etapa-1-agentes-clasificador-de-intencion.md) | Clasificar antes de ejecutar, sin LangGraph todavía |
| [`etapa-2-agentes-soporte-rag-documental.md`](etapa-2-agentes-soporte-rag-documental.md) | El corpus de soporte y por qué no es `docs/` |
| [`etapa-3-agentes-grafo-langgraph.md`](etapa-3-agentes-grafo-langgraph.md) | El loop de turnos envuelto como nodo de un grafo |
| [`etapa-4-agentes-especializados-retrieval-hibrido.md`](etapa-4-agentes-especializados-retrieval-hibrido.md) | Los siete agentes y los tres peldaños |
| [`etapa-5-pausa-humana.md`](etapa-5-pausa-humana.md) | La pausa tipada, y por qué **no** usa `interrupt()` |

---

Los tres diagramas de arriba están además como archivo suelto en
[`../diagramas/`](../diagramas/) —`05-grafo-del-turno`,
`06-turno-con-firma-humana`, `07-retrieval-hibrido`— siguiendo la convención
que ya usan los cuatro diagramas del proyecto, para que se puedan renderizar
sueltos:

```
mmdc -i docs/diagramas/05-grafo-del-turno.mermaid -o grafo.png -b white -w 1700
```

**El archivo `.mermaid` es la copia canónica.** Si cambiás un diagrama,
cambialo ahí y pegá el resultado acá — son dos copias a propósito, para que
este documento se lea renderizado en GitHub y el diagrama siga estando donde
el resto del proyecto los busca.
