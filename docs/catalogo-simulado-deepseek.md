# Catálogo de comercios simulados, fabricado con DeepSeek

**25 de agosto de 2026.** Primer módulo de la etapa 5
(`docs/arquitectura-v2.md`, fila 5: "Agente y app — `agente/`, `entradas/
api/`, catálogo semilla, adaptador DeepSeek"). Solo la parte de **fabricar**
el catálogo -- `agente/`, `navegar_catalogo.py` y el resto de la etapa 5 se
construyeron después, ver `docs/etapa-5-agente-y-cli.md`.

Antes de construir esto se investigó qué proponen hoy los protocolos de
comercio agéntico (ACP de OpenAI+Stripe+Meta, AP2 y UCP de Google, NLWeb de
Microsoft) para que un comercio exponga su catálogo a un LLM — ver la
conversación previa a este documento. Conclusión: ninguno encaja tal cual
(ACP es un feed en lote, pensado para que ChatGPT indexe; AP2 deja el
catálogo fuera de su alcance a propósito). Lo que sí se tomó prestado es el
**vocabulario de campos** del product feed de ACP (`availability`,
`gtin`/`mpn`, etc.), adaptado a lo mínimo que esta demo necesita, servido
como llamadas en vivo (`buscar_comercios`/`buscar_productos`/`ver_producto`)
en vez de un archivo que alguien más indexa — el patrón de NLWeb/MCP, no el
de ACP.

## Qué se construyó

| Paquete | Qué hace |
|---|---|
| `dominio/catalogo/modelo.py` | `Disponibilidad` (en_stock / agotado / pedido_anticipado — el vocabulario de ACP, sin `unknown`), `Comercio.descripcion`, `Producto.disponibilidad` |
| `puertos/catalogo.py` | `RepositorioCatalogo`: `buscar_comercios`, `buscar_productos`, `ver_producto` — tres métodos separados, no uno solo, para que el agente primero elija un comercio y después busque adentro |
| `puertos/modelo_lenguaje.py` | `ModeloDeLenguaje.generar(sistema, instruccion) -> str`. Deliberadamente más chico que el `responder(mensajes, herramientas)` que `arquitectura-v2.md` prevé para el agente vivo — ver "Qué no se tocó" |
| `adaptadores/llm/deepseek/` | `AdaptadorDeepSeek`, vía el SDK `openai` apuntado a la API de DeepSeek (compatible con Chat Completions). Cliente inyectable, igual que `ClienteWompi` |
| `aplicacion/generar_catalogo_semilla.py` | `GenerarCatalogoSemilla`: le pide al modelo un comercio + N productos, parsea el JSON y lo valida campo por campo contra el dominio. Nunca acepta una respuesta a medias — JSON inválido, un campo faltante, un precio negativo o una disponibilidad que no existe hacen que se descarte la respuesta entera, no que se rellene con un default |
| `adaptadores/catalogo/semilla/` | `RepositorioCatalogoSemilla`: lee `datos/catalogo.json` — sin red, sin base de datos — e implementa `RepositorioCatalogo`. Simétrico a como la pasarela simulada resuelve pagos sin hablar con Wompi |
| `scripts/generar_catalogo_semilla.py` | El composition root de este comando: lee `DEEPSEEK_API_KEY`, corre `GenerarCatalogoSemilla` por cada categoría pedida, escribe `catalogo.json` con backup automático del anterior |
| `composicion/contenedor.py` | `Contenedor.catalogo`, armado sin depender de `pasarela`/`persistencia` — mismo precedente que `RepositorioMediosSQLite` en la etapa 3: el adaptador está listo antes de que exista el caso de uso que lo llame |

337 pruebas en verde (289 + 48 nuevas), incluida `test_fronteras.py`. Ninguna
prueba nueva toca la red real ni una llave de DeepSeek de verdad —
`AdaptadorDeepSeek` se prueba con un cliente doble que solo imita la forma
que el adaptador usa (`.chat.completions.create(...)`), y
`GenerarCatalogoSemilla` con un `ModeloDeLenguaje` que devuelve texto fijo.

## El `catalogo.json` que se entrega es un placeholder

`adaptadores/catalogo/semilla/datos/catalogo.json` trae dos comercios de
ejemplo (TecnoX, LibroSur) escritos a mano con el propio código de
serialización del proyecto — **no** se generaron con DeepSeek todavía,
porque esta sesión no tiene una llave de DeepSeek configurada. Están ahí
únicamente para que `RepositorioCatalogoSemilla` (y `Contenedor.construir()`,
que ahora lo arma siempre) tengan un archivo real que leer desde el primer
momento — sin esto, cualquier prueba o script que arme un `Contenedor`
fallaría por un `catalogo.json` inexistente.

Para reemplazarlo por un catálogo de verdad:

```
export DEEPSEEK_API_KEY=sk-...
python scripts/generar_catalogo_semilla.py
```

Por defecto genera un comercio por cada una de cinco categorías
(tecnología, moda, hogar, restaurantes, libros); `--categorias`,
`--por-categoria` y `--productos` lo ajustan. La corrida anterior queda
respaldada (`catalogo.bak-<fecha>.json`) antes de sobrescribirse.

## Decisiones de diseño

**Por qué `ModeloDeLenguaje` no es todavía el puerto completo que
`arquitectura-v2.md` describe.** La arquitectura documenta
`responder(mensajes, herramientas) -> RespuestaModelo` — el loop de turnos
con tool-calling que el agente conversacional va a necesitar. Construir esa
forma ahora, sin un `agente/conversacion.py` real que la llame, sería
diseñar a ciegas cómo se ve una respuesta parcial de herramientas o un
reintento — exactamente la abstracción especulativa que la sección 9 de
`arquitectura-v2.md` pide evitar. `generar(sistema, instruccion) -> str` es
la porción mínima que `GenerarCatalogoSemilla` de verdad usa; se amplía
cuando exista un segundo llamador real.

**Por qué `RepositorioCatalogo` tiene tres métodos y no uno.** Refleja la
forma en que `arquitectura-v2.md` (sección 5) le da herramientas al agente:
`buscar_comercios`, `buscar_productos`, `ver_producto` por separado, para
que el agente elija un comercio antes de buscar dentro de él — preguntas más
chicas y más auditables que una búsqueda sobre todo el catálogo a la vez.

**Por qué la generación es un caso de uso (`aplicacion/`) y no solo lógica
del script.** Validar lo que DeepSeek contesta es una regla de negocio
("un comercio simulado necesita nombre, categoría, y al menos un producto
con precio positivo"), no ceremonia de arranque. Vive detrás del puerto
`ModeloDeLenguaje`, igual que `EjecutarIntencion` vive detrás de
`PasarelaDePagos` — se puede probar sin red y sin CLI de por medio.

## Qué no se tocó a propósito

- **`entradas/api/`** — FastAPI + SSE para un chat en vivo por HTTP. Se
  eligió `entradas/cli/` primero (ver `docs/etapa-5-agente-y-cli.md`);
  `api/` queda para una entrega posterior.
- **`Comercio`/`Producto` no tienen imagen ni identificadores tipo
  `gtin`/`mpn`** — el vocabulario de ACP los define, pero esta demo no
  muestra fotos ni necesita reconciliar contra un catálogo real; se
  agregan si en algún momento hacen falta de verdad.

`agente/`, `aplicacion/navegar_catalogo.py` y el `ModeloDeLenguaje` completo
(`responder` con tool-calling) que este documento marcaba como pendiente ya
se construyeron -- ver `docs/etapa-5-agente-y-cli.md`.

## Variables de entorno nuevas

```dotenv
# --- DeepSeek (solo para scripts/generar_catalogo_semilla.py) ------------- #
DEEPSEEK_API_KEY=sk-...
# DEEPSEEK_MODELO=deepseek-chat   # opcional, default deepseek-chat
```

A diferencia de `WOMPI_*`/`PAGADOR_*`, estas NO las lee
`composicion/configuracion.py` ni `ConfiguracionAgora` — `Contenedor` nunca
necesita una llave de DeepSeek para arrancar, solo el script de generación
las usa, leídas directo de `os.environ` (mismo patrón que
`scripts/migrar_fuentes_a_sqlite.py`).

## Pendiente inmediato

1. Confirmar que los archivos nuevos están en disco.
2. `git add` + commit desde tu terminal.
3. Cuando tengas una llave de DeepSeek: correr
   `scripts/generar_catalogo_semilla.py` para reemplazar el catálogo
   placeholder por uno generado de verdad, y exportar esa misma
   `DEEPSEEK_API_KEY` para que `entradas/cli/ chat` (`docs/
   etapa-5-agente-y-cli.md`) tenga con qué conversar.
4. **Siguiente:** `entradas/api/` + SSE (chat por HTTP en vivo) -- todo lo
   demás de la etapa 5 ya está construido.
