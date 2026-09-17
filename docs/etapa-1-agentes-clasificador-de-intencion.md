# Migración a agentes — etapa 1: el clasificador de intención

**16 de septiembre de 2026.** Primera de las cinco etapas de
[`arquitectura-agentes-langgraph.md`](arquitectura-agentes-langgraph.md):
*"Extraer el clasificador de intención como paso explícito delante del loop
actual, sin LangGraph todavía — valida separar 'decidir' de 'ejecutar' antes
de reescribir nada."*

No hay grafo, ni LangChain, ni LangGraph en esta etapa. Hay un solo loop de
turnos (el de siempre, `agente/conversacion.py`) que ahora, antes de
ejecutar, **decide** a qué dominio pertenece el mensaje y, con eso, qué
herramientas puede ver y ejecutar el modelo en ese turno.

El principio no cambia: *el agente propone, el humano firma, la bóveda
ejecuta*. `PROHIBIDAS` no se tocó; ninguna ruta puede habilitar algo fuera
del catálogo autorizado; `pagar` sigue exigiendo un `mandato_id` que firmó
una persona.

## Qué se construyó

```
agora/agente/
  intencion.py             TipoDeIntencion (6 valores), ClasificacionDeIntencion
                           (con schema), protocolo ClasificadorDeIntencion
  nodos.py                 RUTAS intención -> nodos, instrucciones por nodo,
                           RUTA_DE_RESPALDO, Ruta
  clasificacion/
    reglas.py              ClasificadorPorReglas: determinístico, se abstiene si duda
    modelo.py              ClasificadorConModelo: DeepSeek vía ModeloDeLenguaje.generar
    cadena.py              ClasificadorEnCadena: el primero que decide, gana
  herramientas.py          + HERRAMIENTAS_POR_NODO, validar_catalogo(..., nodo=),
                           validar_asignacion_por_nodo, herramientas_para_nodo
  conversacion.py          Agente.turno = _decidir + _ejecutar_turno;
                           Conversacion.clasificaciones
agora/composicion/
  agente.py                + construir_clasificador(modo, modelo)
  configuracion.py         + AGORA_CLASIFICADOR = hibrido | reglas | apagado
agora/entradas/cli/
  __main__.py              + chat --mostrar-intencion
```

### El turno, en dos pasos

```
persona escribe
     │
     ▼
1. DECIDIR    ClasificadorEnCadena
               ├─ ClasificadorPorReglas   (gratis; se abstiene ante la duda)
               └─ ClasificadorConModelo   (1 llamada extra; lee historial)
     │        → ClasificacionDeIntencion {intencion, origen, confianza, motivo}
     │        → Ruta (nodos → herramientas habilitadas + instrucción del turno)
     ▼
2. EJECUTAR   el loop de siempre, pero:
               · anuncia SOLO las herramientas de la ruta
               · agrega la instrucción del orquestador al mensaje de sistema
                 (en la vista del modelo, no en el historial)
               · rechaza al ejecutar cualquier llamada fuera de la ruta,
                 aunque la herramienta exista en el agente
```

### Rutas

| Intención | Nodos | Herramientas habilitadas |
|---|---|---|
| `catalogo` | catalogo | buscar_comercios, buscar_productos, ver_producto |
| `carrito_pago` | catalogo + carrito_pago | las tres de catálogo + armar_carrito, pagar |
| `medios_de_pago` | medios_de_pago | ninguna |
| `estado` | estado | consultar_estado |
| `soporte` | soporte | ninguna |
| `fuera_de_alcance` | orquestador | ninguna |
| *(respaldo)* | catalogo + carrito_pago + estado | las seis — el agente de antes |

## Decisiones

**1. La lista blanca vive en `herramientas.py`, junto a `PROHIBIDAS`.**
`HERRAMIENTAS_POR_NODO` es la tabla de la decisión 3 del documento, dicha en
código, con los siete nodos (incluido `riesgo`, que ninguna ruta usa todavía).
`validar_asignacion_por_nodo` exige que cada herramienta tenga **un solo nodo
dueño** y que `armar_carrito`/`pagar` solo puedan ser de `carrito_pago`.
`validar_catalogo(herramientas, nodo=...)` mantiene intacta la validación
global de antes y agrega la del nodo. El `Agente` corre las dos al
construirse: si la tabla se rompe, el proceso no levanta.

**2. `armar_carrito` y `pagar` siguen juntas** en `carrito_pago` (decisión 5).
Hay una prueba que falla si alguien las separa.

**3. Una ruta puede combinar nodos, y eso es transitorio.** La ruta de
`carrito_pago` habilita también las herramientas de catálogo: "quiero comprar
los audífonos baratos" necesita buscar el producto *y* armar el carrito en el
mismo turno, y sin grafo no hay forma de pasar de un nodo a otro dentro de un
turno. La propiedad que no se negocia se mantiene: cada herramienta sigue
teniendo un solo dueño. En la etapa 4 esa fila de `RUTAS` pasa a ser una
arista `catalogo → carrito_pago` de LangGraph.

**4. Ante la duda, respaldo — y respaldo es exactamente el agente de antes.**
Sin clasificador, con reglas ambiguas y sin modelo, con el modelo caído, con
una respuesta del modelo que no calza con el contrato, o con confianza menor
a 0,6: el turno va por la ruta de respaldo (las seis herramientas, sin
instrucción extra). Clasificar es una optimización del turno, no un requisito
para que exista; su falla nunca tumba la charla. La decisión queda igual
registrada, con el motivo (`Conversacion.clasificaciones`).

**5. Enrutar solo puede angostar, nunca ampliar.** Toda ruta es un
subconjunto del catálogo autorizado. Por eso una inyección de prompt que
logre "elegir" la intención (escribiendo `consultar_estado` a propósito, o
convenciendo al clasificador con modelo) no le da al turno nada que el agente
no tuviera ya en la etapa 7. Lo que escribe la persona entra al prompt del
clasificador como dato delimitado (`<<< >>>`), y la salida es un enum cerrado.

**6. Reglas primero, modelo después (riesgo de latencia/costo del documento).**
Las reglas resuelven lo inequívoco sin gastar una llamada — incluidos **todos
los avisos que el propio sistema le manda a la conversación** (después de
firmar o retomar desde el popup, y cuando llega un webhook), que siempre
traen marcas como `pagar()` o `consultar_estado`. Las reglas se abstienen si
un mensaje activa más de una intención; la única excepción explícita es
compra + catálogo → compra, porque esa ruta ya incluye catálogo. Un "sí,
dale" nunca lo deciden las reglas: solo se entiende con historial.

**7. Sin puerto nuevo en esta etapa.** Ninguna librería externa entra todavía:
el clasificador con modelo usa el puerto que ya existía
(`ModeloDeLenguaje.generar`, el mismo de `GenerarCatalogoSemilla`), y el
`ClasificadorDeIntencion` es una estrategia interna del agente. El puerto que
aísle LangGraph llega con LangGraph, en la etapa 3. Una intención
conversacional tampoco es un concepto de `dominio/` (un `Mandato` existe
igual sin chat), por eso vive en `agente/`.

**8. La instrucción del orquestador no se guarda en el historial.** Se
agrega al mensaje de sistema de la vista que recibe el modelo y se descarta al
terminar el turno. Si se guardara, cada turno viejo arrastraría la
instrucción de una ruta que ya no aplica. Va pegada al sistema inicial, no
como un mensaje `"system"` suelto justo antes del mensaje de la persona
(que era la primera versión de esta etapa): no todo proveedor compatible con
Chat Completions acepta un `"system"` a mitad del historial, y como no se pudo
probar contra DeepSeek real, un 400 del proveedor habría tumbado cada turno
enrutado. Se cambió recencia por robustez.

**9. `AGORA_CLASIFICADOR` es el interruptor.** `hibrido` (default), `reglas`
(sin costo extra de API) o `apagado` (el agente de la etapa 7 tal cual). Para
una demo en vivo donde el enrutamiento moleste, basta con `apagado`.

**10. `requirements.txt` no cambia en esta etapa.** Ninguna dependencia nueva
se importa todavía, y agregar LangChain/LangGraph sin un `import` real sería
una dependencia muerta (y decenas de paquetes transitivos más en el venv de
Windows). Cada una entra en la etapa que la usa por primera vez: embeddings y
LangChain en la etapa 2, LangGraph en la 3. Ver "Qué falta" para la
recomendación de embeddings.

## Hallazgos reales

**`test_fronteras.py` no verificaba la frontera que el proyecto dice
verificar.** El principio documentado es que el build falla si `agente/`
importa `aplicacion/`, pero la tabla `REGLAS` para la capa `agente` solo
prohibía `adaptadores` y `composicion`. Se comprobó con un experimento: un
módulo `agora/agente/_intruso.py` con
`from ..aplicacion.ejecutar_intencion import EjecutarIntencion` (el caso de
uso que cobra) más `importlib.import_module("agora.adaptadores.pasarelas.wompi")`
**pasaba la suite en verde**, incluida `test_el_agente_no_alcanza_ninguna_pasarela`.
Nada del código actual lo explotaba — es un hueco de la red, no una violación
existente. Corregido:

- `REGLAS["agente"]` ahora prohíbe también `aplicacion` y `entradas`.
- `importlib` queda prohibido en `agente/`, y hay una prueba nueva contra
  `__import__(...)`: las dos formas de importar por nombre en un string que el
  AST no ve como `import`.
- Con el archivo nuevo, el mismo intruso falla en dos pruebas.

## Cómo se probó

**Pruebas nuevas:**

| Archivo | Qué cubre |
|---|---|
| `tests/test_agente_nodos.py` | tabla coherente; un solo dueño por herramienta; dinero solo en `carrito_pago`; `validar_catalogo` por nodo; **soporte nunca puede tener `armar_carrito` ni `pagar`**; rutas ⊆ catálogo; respaldo = agente de antes |
| `tests/test_agente_enrutado.py` | `Agente.turno` con clasificador: anuncia solo la ruta; **en soporte, un `pagar` alucinado se rechaza y la función real nunca corre** (espía); instrucción en el único mensaje de sistema, en cada ronda, y fuera del historial; historial correcto al clasificador |
| `tests/test_clasificador_reglas.py` | casos inequívocos, avisos del sistema, abstención ante la duda |
| `tests/test_clasificador_modelo.py` | contrato cerrado (10 formas de respuesta inválida → respaldo); proveedor caído → respaldo; un bug que no es `ErrorDeDominio` no se esconde; umbral; qué entra y qué no al prompt |
| `tests/test_clasificador_cadena.py` | el primero que decide gana y el siguiente no se consulta; motivos acumulados |
| `tests/test_composicion_clasificador.py` | `AGORA_CLASIFICADOR` de punta a punta con contenedor real: híbrido no gasta llamada si las reglas deciden, sí la gasta si se abstienen; `reglas` y `apagado` |
| `tests/test_cli_chat_intencion.py` | `chat --mostrar-intencion` |
| `tests/test_fronteras.py` (extendido) | reglas corregidas del agente; LangChain/LangGraph/SDKs de LLM solo en `adaptadores/`; `__import__` dinámico; los seis módulos nuevos explícitamente bajo la regla del agente; **pruebas del detector** con un `agora/` de mentira que exigen que atrape las violaciones conocidas |

**Pruebas existentes sin tocar:** `tests/test_api_app.py` corre ahora con el
clasificador `hibrido` por defecto, y su `_ModeloProgramable.generar` levanta
`AssertionError`. Que siga en verde demuestra que el flujo completo por HTTP
(armar → firmar → pagar → confirmar → webhook) se enruta entero por reglas,
sin tocar el clasificador con modelo, con las herramientas correctas en cada
turno.

**Resultado:** 795 pruebas en verde (línea base de esta sesión: 521), mismas
6 fallas preexistentes y no relacionadas de `tests/test_migracion_fuentes.py`
(buscan `scripts/migrar_fuentes_a_sqlite.py`, que no existe en este checkout).

**Dónde corrió, y qué no se pudo verificar:**

- El puente a la carpeta de Juan no pudo montar la carpeta en esta sesión (un
  problema conocido de una actualización de Windows del 8 de septiembre), así
  que la suite corrió en el entorno en la nube de la sesión (Python 3.11), sobre una
  copia de los archivos, no en el venv de Windows. **Juan debería correr la
  suite de su lado antes de avanzar.**
- **El clasificador con modelo no se probó contra DeepSeek real.** El `.env`
  sí tiene `DEEPSEEK_API_KEY`, pero la salida de red de ese entorno hacia
  `api.deepseek.com` fue rechazada (403 del proxy). El prompt del clasificador
  y la calidad de sus decisiones con mensajes reales quedan sin validar; lo
  que sí está probado es que cualquier respuesta fuera de contrato, o la falta
  de respuesta, termina en respaldo. Prueba a mano sugerida:
  `python -m agora.entradas.cli chat --mostrar-intencion` con mensajes como
  "sí, dale" después de ver un producto.

## Qué no cambia

- `PROHIBIDAS`, `CATALOGO_DE_HERRAMIENTAS` y los esquemas de las seis
  herramientas: idénticos.
- `entradas/api/` (rutas, SSE, popups) y `sesiones.py`: sin cambios. Los
  eventos `propuesta_pendiente`/`confirmacion_pendiente` se siguen detectando
  igual, porque los mensajes de rol `"tool"` del historial no cambiaron de
  forma.
- El `SYSTEM_PROMPT` general (`politica.py`) sigue siendo uno solo; lo que se
  agrega por turno es una instrucción corta de los nodos de la ruta.

## Qué falta para la etapa 2 (agente de soporte/FAQ con RAG documental)

1. **Decidir el proveedor de embeddings** — no hay ninguna llave de embeddings
   en el `.env`. Recomendación, a confirmar con Juan: **FastEmbed** con
   `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384
   dimensiones, ~0,22 GB, multilingüe). Se verificó que `fastembed` 0.8.0 lo
   lista entre sus modelos soportados; no se verificó descargarlo ni su
   calidad con los documentos reales. Por qué: corre local con ONNX, sin
   torch (liviano para el venv de Windows), sin llave ni costo por consulta,
   y la documentación del proyecto no sale hacia un tercero — relevante en un
   contexto bancario. Alternativas: `intfloat/multilingual-e5-large` (mejor
   calidad, ~2,2 GB) o una API (OpenAI `text-embedding-3-small`, necesita
   llave y manda los textos afuera).
2. Puerto nuevo `puertos/recuperacion.py` (p. ej. `BuscadorDocumental`) con
   tipos propios del proyecto, y su adaptador en `adaptadores/recuperacion/`
   con LangChain (text splitter + vector store en memoria) detrás.
   `test_fronteras.py` ya falla si `langchain*` aparece fuera de
   `adaptadores/`.
3. Índice **separado** del catálogo, sobre `docs/` y la explicación de los
   ocho controles del mandato. Ningún número exacto sale de ahí (topes,
   `monto_max`): la instrucción del nodo `soporte` ya lo prohíbe en prosa, y
   la etapa 2 debería probarlo.
4. Darle al nodo `soporte` su recuperación **sin** convertirla en una
   herramienta del catálogo de dinero: `HERRAMIENTAS_POR_NODO["soporte"]`
   debe seguir sin `armar_carrito`/`pagar` (la prueba ya existe). Si la
   recuperación entra como herramienta del modelo, hay que agregarla a
   `CATALOGO_DE_HERRAMIENTAS` con dueño único `soporte`; si entra como
   contexto inyectado por el nodo, no hace falta tocar el catálogo.
5. Agregar a `requirements.txt` lo que la etapa 2 importe de verdad.
