# Etapa 5 (resto): el agente, la firma y la CLI

**25 de agosto de 2026.** Continúa `docs/catalogo-simulado-deepseek.md`
(el primer módulo de la etapa 5, ya entregado). Esto es todo lo demás que
`docs/arquitectura-v2.md` pone en la fila 5: `aplicacion/navegar_catalogo.py`,
`aplicacion/emitir_mandato.py`, `aplicacion/enrolar_medio.py` +
`revocar_medio.py`, `agente/` completo (herramientas reales, el loop de
turnos, el system prompt), y `entradas/cli/` como primera interfaz para
probar todo esto de punta a punta.

Dos decisiones se tomaron antes de construir, ambas explícitas:

1. **La llave de firma del titular vive en disco, igual que v1**
   (`boveda/secretos/firma.sk`/`firma.pk`) — un par ed25519 sin cifrar, leído
   por el mismo proceso que corre `entradas/cli/`. `agente/` nunca la toca:
   no importa el módulo que la carga, ni siquiera indirectamente
   (`test_fronteras.py` lo verifica).
2. **`entradas/cli/` primero, `entradas/api/` + SSE queda para después.** La
   API con streaming es bastante más trabajo que una CLI y no cambia ninguna
   decisión de diseño de fondo (las reglas de dependencia, los seis nombres
   de herramienta, el loop de turnos son los mismos debajo de cualquier
   interfaz) — mejor tener el flujo completo probable hoy que la mitad de
   dos interfaces.

412 pruebas en verde (289 previas + 48 del catálogo + 75 nuevas de esta
entrega), incluidas las 155 de `test_fronteras.py`.

## Qué se construyó

| Paquete | Qué hace |
|---|---|
| `puertos/firma.py` | `Firmante`: `firma(carga) -> bytes`, `llave_publica() -> bytes`. Separado de `Verificador` (que sigue en `dominio/mandato/modelo.py`) porque firmar y verificar los necesitan lados distintos: `EjecutarIntencion` nunca firma, `EmitirMandato` nunca verifica sin firmar antes |
| `adaptadores/sistema/firma_ed25519.py` | `FirmanteEd25519` + `cargar_o_generar_firmante(ruta_sk, ruta_pk)` — si las llaves no existen, las genera; si existen, las lee. Sin cifrar, mismo alcance que las credenciales de Wompi en `.env` |
| `puertos/repositorios.py` | `RepositorioCarritos` (`guardar`/`obtener`, levanta `CarritoDesconocido`) y `RegistroDeEstados` (`fijar`/`obtener` — resuelve un vacío real: `LibroDeConsumo.reserva_pendiente_de` no distingue "nunca existió" de "ya se resolvió", y `consultar_estado` sí necesita esa distinción) |
| `adaptadores/persistencia/memoria/` | `RepositorioCarritosEnMemoria`, `RegistroDeEstadosEnMemoria` |
| `adaptadores/persistencia/sqlite/` | `RepositorioCarritosSQLite` (tabla `carrito` nueva) — hace falta para que `entradas/cli/` (donde "armar y firmar" y "pagar" son comandos separados, cada uno su propio proceso) pueda completar una compra con `AGORA_PERSISTENCIA=sqlite`. `RegistroDeEstados` se queda en memoria a propósito — ver más abajo |
| `aplicacion/navegar_catalogo.py` | `NavegarCatalogo`: `buscar_comercios`/`buscar_productos`/`ver_producto` delegan tal cual; `armar_carrito` es donde vive la regla — un carrito es de un solo comercio, y nada `AGOTADO` puede entrar |
| `aplicacion/emitir_mandato.py` | `EmitirMandato`: `PropuestaDeMandato` + `titular_id` → `Mandato` firmado. Vuelve a buscar el carrito por `carrito_id` (nunca confía en uno que llegue de afuera) para calcular `carrito_hash` desde la fuente autoritativa |
| `aplicacion/enrolar_medio.py` / `revocar_medio.py` | Mismo flujo que `boveda/enrolamiento.py` (token → push → sondeo → fuente), pero contra el puerto `PasarelaDePagos` en vez de Wompi directo — funciona igual con la simulada (aprueba de inmediato) que con Wompi real |
| `aplicacion/consultar_estado.py` | `ConsultarEstado`, envoltorio delgado sobre `RegistroDeEstados` |
| `puertos/modelo_lenguaje.py` | Se amplía: `responder(mensajes, herramientas) -> RespuestaModelo`, con `Mensaje`/`LlamadaHerramienta`/`DefinicionHerramienta`/`RespuestaModelo` — el tool-calling que el docstring original dejó pendiente hasta que existiera un llamador real |
| `adaptadores/llm/deepseek/adaptador.py` | `AdaptadorDeepSeek.responder()`: traduce hacia y desde el formato de Chat Completions con `tools` |
| `agente/herramientas.py` | `construir_herramientas(...)`: arma las seis `Herramienta` del catálogo autorizado (esquemas JSON incluidos) atadas a funciones ya cerradas sobre sus casos de uso — nunca importa `aplicacion/` |
| `agente/conversacion.py` | `Agente`/`Conversacion`: el loop de turnos, hasta `MAX_TURNOS_POR_CONVERSACION` |
| `agente/politica.py` | El system prompt y el límite de turnos |
| `composicion/agente.py` | El único lugar que conoce `aplicacion/` y `agente/` a la vez: cierra las seis funciones reales y arma el `Agente` |
| `composicion/contenedor.py` / `configuracion.py` | `Contenedor` crece: `carritos`, `estados`, `firmante`, `navegar_catalogo`, `emitir_mandato`, `enrolar_medio`, `revocar_medio`, `consultar_estado`, `modelo_lenguaje` (`None` sin `DEEPSEEK_API_KEY`) |
| `entradas/cli/` | `python -m agora.entradas.cli <comando>`: `enrolar`, `fuentes`, `revocar`, `comercios`, `productos`, `producto`, `emitir`, `pagar`, `retomar`, `estado`, `mandatos`, `chat` |

## Decisiones de diseño

**Por qué `EjecutarIntencion` gana un parámetro `carrito_hash`.** Es un
hallazgo real de esta entrega, no un plan original: `Mandato.carrito_hash`
existía desde antes (el Cart Mandate de AP2), pero nada lo llenaba nunca —
ningún mandato de prueba lo traía. En cuanto `EmitirMandato` empezó a
firmarlo, la primera prueba de punta a punta bloqueó todo con
`carrito_alterado`, porque `EjecutarIntencion.__call__`/`retomar` nunca
pasaban un `carrito_hash` a `evaluar()`. Ahora ambos aceptan
`carrito_hash: str | None = None` (opcional, no rompe ninguna prueba
anterior) y quien llame — `composicion/agente.py:pagar` o
`entradas/cli/:cmd_pagar` — lo recalcula desde el carrito recién obtenido,
nunca desde un dato que el agente pueda inventar.

**Por qué `pagar()` casi siempre devuelve `esperando_confirmacion_humana`.**
`EmitirMandato` corta el mandato exacto al carrito: `monto_max` igual al
total, un solo uso. Eso dispara casi siempre las señales blandas de
`dominio/mandato/politica.py` ("agota el mandato de una sola vez", "es el
último uso") — no es un error de esta entrega, es la consecuencia esperada
de firmar mandatos angostos a propósito (la v1 ya defendía esos defaults
estrechos). `entradas/cli/ retomar` es como un humano lo resuelve; el agente
nunca tiene esa herramienta — resolver un `CONFIRMAR` es una decisión
humana, igual que firmar.

**Por qué `RegistroDeEstados` se queda en memoria, sin equivalente SQLite.**
A diferencia de `carritos` (que si necesitó una versión SQLite: sin ella,
`pagar` en un proceso y `estado`/`retomar` en otro fallarían por completo),
`RegistroDeEstados` es el vocabulario que el agente usa para preguntarse a
sí mismo dentro de UNA conversación (`consultar_estado` después de `pagar`,
en el mismo proceso de `chat`). Que no sobreviva entre invocaciones
separadas de la CLI es una limitación real y documentada (ver el docstring
del comando `estado`), no una decisión de dejarlo a medias: agregar una
cuarta tabla SQLite por una herramienta de depuración manual no valía el
costo frente a construir la pieza que sí mueve dinero.

**Por qué `agente/herramientas.py` nunca importa `aplicacion/`.** Es la
frontera dura, hecha estructural: `construir_herramientas` recibe seis
funciones (`Callable[..., Any]`) ya cerradas sobre sus dependencias reales.
Quien las cierra es `composicion/agente.py` — el único paquete al que se le
permite importar tanto `aplicacion/` como `agente/`. `agente/` nunca ve un
`EjecutarIntencion` ni un `NavegarCatalogo`; ve seis funciones con nombre y
forma, nada más. `test_fronteras.py` lo verifica con AST, no por
convención.

**Por qué `DefinicionHerramienta` no es la misma `Herramienta` de
`agente/herramientas.py`.** `puertos/modelo_lenguaje.py` no puede importar
`agente/` (la regla de dependencia es al revés). `DefinicionHerramienta`
lleva solo `nombre`/`descripcion`/`esquema` — lo que un proveedor de LLM
necesita para anunciar la herramienta — sin el `Callable` de `ejecutar`.
`agente/conversacion.py` traduce entre las dos formas.

**Por qué `entradas/cli/` construye "armar y firmar" como un solo comando
(`emitir`).** En `docs/arquitectura-v2.md` (sección 5), "el agente propone,
el humano firma" son dos pasos separados porque quien propone es un modelo
de lenguaje. En la CLI, quien escribe el comando YA es el humano — separar
`armar_carrito` de `emitir_mandato` en dos invocaciones no agregaría ninguna
garantía, solo fricción. La separación sigue existiendo donde importa: el
agente (`agente/herramientas.py`) nunca tiene acceso a `emitir_mandato`, ni
puede tenerlo.

## Qué no se tocó a propósito

- **`entradas/api/` + SSE** — la decisión de esta entrega fue CLI primero.
- **El motor de riesgo** que `dominio/mandato/politica.py` menciona como
  alternativa a `CONFIRMAR` — sigue siendo heurísticas fijas en código, no
  un modelo.
- **`retomar` como herramienta del agente** — deliberado, no un olvido: es
  una decisión humana, igual que firmar.

## Cómo probarlo

```bash
export AGORA_PERSISTENCIA=sqlite
export AGORA_SQLITE_PATH=agora_datos/agora.db
export PAGADOR_EMAIL=tu.correo.real@dominio.com

python -m agora.entradas.cli enrolar --telefono 3001234567 --titular tit_1
python -m agora.entradas.cli comercios
python -m agora.entradas.cli productos com_placeholder_librosur
python -m agora.entradas.cli emitir com_placeholder_librosur tit_1 \
    --item prd_placeholder_libreta
# copiar el mandato_id/carrito_id que imprime:
python -m agora.entradas.cli pagar <mandato_id> <carrito_id>
python -m agora.entradas.cli retomar <intencion_id> <mandato_id> <carrito_id>
python -m agora.entradas.cli mandatos

# con DEEPSEEK_API_KEY configurada:
python -m agora.entradas.cli chat
```

`AGORA_PERSISTENCIA=sqlite` no es opcional para probar `emitir`/`pagar`
como comandos separados: con `memoria` (el default), cada invocación de la
CLI es un proceso nuevo con un `RepositorioMedios`/`RepositorioCarritos` en
RAM vacío, y `pagar` no va a encontrar el carrito que `emitir` armó en la
corrida anterior.

## Pendiente inmediato

1. Confirmar que los archivos nuevos están en disco y correr la suite
   completa (`pytest`) desde la raíz del repo.
2. `git add` + commit desde tu terminal.
3. Cuando quieras un catálogo de verdad (no el placeholder): exportar
   `DEEPSEEK_API_KEY` y correr `scripts/generar_catalogo_semilla.py`, y
   después `python -m agora.entradas.cli chat` para conversar con el
   agente sobre ese catálogo.
4. **Siguiente:** `entradas/api/` + SSE, cuando haga falta un chat en vivo
   por HTTP en vez de una terminal.
