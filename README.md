# agora — comercio agéntico sobre rieles colombianos

agora es una herramienta para estudiar qué pasa cuando un agente de IA compra
en nombre de una persona. Una persona chatea con un agente, el agente le arma
una compra en un comercio, y el dinero sale de una cuenta Nequi real a través
de Wompi. Lo que agora mide es lo que pasa en el medio: qué autoriza el
titular, qué intenta ejecutar el agente, y cuánto de la diferencia entre esas
dos cosas se detiene antes de que se mueva un peso.

## La idea en una frase

> **El agente propone. El humano firma. El motor de pagos ejecuta.**
> Ninguno de los tres puede hacer el trabajo de otro.

En la práctica: el agente busca productos, arma un carrito y *propone* una
autorización de pago (un **mandato**) — nunca la firma, porque no tiene la
llave. La persona ve exactamente qué se le pide autorizar (comercio, monto
máximo, vigencia, usos) y la firma con un clic, desde su sesión. Recién
entonces el agente puede pedir el cobro, y el motor de pagos vuelve a revisar
todo (firma, vigencia, monto, comercio, que el carrito no haya cambiado)
antes de llamar a la pasarela.

Por encima del mandato hay **topes duros** que nunca se pueden desactivar:
20.000 COP por transacción y 100.000 COP por día, constantes en el código.
Protegen el dinero real aunque el mandato falle o se manipule.

## Qué hay en agora

- Un **agente conversacional** (DeepSeek) organizado como grafo: un
  orquestador clasifica cada mensaje y lo enruta a uno de siete agentes
  especializados, cada uno con solo las herramientas de su dominio. Seis
  herramientas en total; ninguna firma, enrola ni ve un medio de pago.
- Una **página web de chat** con inicio de sesión, firma y confirmación en un
  popup, y gestión de medios de pago — más una **CLI** completa.
- **Mandatos firmados con ed25519**, una llave por usuario, verificados en cada
  cobro contra nueve controles.
- **Multi-comercio**: varios comercios reales de Wompi en el mismo proceso,
  cada uno con sus credenciales.
- Un **catálogo simulado** generado con IA (Dulcería La Golosina y Papelería
  El Lápiz Feliz, 24 productos).
- **Persistencia SQLite** con reserva y confirmación atómica del consumo, y un
  **webhook** de Wompi que cierra cada cobro.
- Una **pasarela simulada** que reproduce los cuatro desenlaces de Wompi sin
  gastar un peso. Se cambia a Wompi real con una variable de entorno.

## Arquitectura, de un vistazo

agora sigue la **Clean Architecture de Bancolombia**: cada pieza es un módulo
del scaffold y las dependencias apuntan siempre hacia el dominio.

```
applications/app-service          python -m agora <perfil>: arma todo y arranca
infrastructure/entry-points       api-rest · webhook-wompi · cli
infrastructure/driven-adapters    pasarela-wompi · pasarela-simulada · persistencia-sqlite
                                  llm-deepseek · orquestacion-langgraph · firma-ed25519 · …
domain/usecase                    casos de uso (un caso por carpeta) + agente/ (frontera dura)
domain/model                      entidades y gateways · solo biblioteca estándar
```

El agente vive en `domain/usecase/agente/` y no puede importar ningún otro
caso de uso, adaptador ni gateway de pago o firma: lo que puede hacer le llega
como seis funciones ya armadas. `tests/arquitectura/test_fronteras.py` rompe
el build si alguien lo intenta. Detalle en
[`docs/arquitectura.md`](docs/arquitectura.md).

## Cómo correrlo

### 1. Instalar

Python 3.10 o superior.

```bash
pip install -r requirements.txt
```

Instala agora en modo editable (`pip install -e .[dev]`), que es lo que hace
disponible `python -m agora`. Si mueves el repositorio de carpeta, vuelve a
correrlo.

### 2. Configurar

Crea un `.env` en la raíz (está en `.gitignore`) con la plantilla de
[`docs/variables-de-entorno.md`](docs/variables-de-entorno.md). Para empezar
sin tocar dinero real alcanza con:

```dotenv
AGORA_AMBIENTE=sandbox
AGORA_PASARELA=simulada
AGORA_PERSISTENCIA=sqlite
DEEPSEEK_API_KEY=sk-...        # para el chat
```

### 3. Probar

```bash
python -m pytest -q
```

Corre la suite completa, incluidas las reglas de arquitectura.

### 4. Crear un usuario

Los usuarios se crean por consola (no hay registro público). Cada usuario
nace con su propia llave de firma:

```bash
python -m agora crear-usuario --nombre-usuario juan
```

Muestra el `titular_id` del usuario, que es el que usa la CLI.

### 5. Chatear con el agente (recomendado para una demo)

```bash
python -m agora api
```

Abre `http://localhost:8002`, inicia sesión, y en **Medios de pago** enrola
uno (teléfono + correo) para el comercio donde vas a comprar. Después pídele
algo al agente: cuando haya una propuesta que firmar o un cobro que
confirmar, aparece un popup para resolverlo ahí mismo.

### 6. Operar desde la terminal

```bash
python -m agora cli comercios
python -m agora cli productos <comercio_id>
python -m agora cli enrolar --telefono 3001234567 --titular <titular_id> --comercio <comercio_id>
python -m agora cli emitir <comercio_id> <titular_id> --item <producto_id>:1
python -m agora cli pagar <mandato_id> <carrito_id>
python -m agora cli retomar <intencion_id> <mandato_id> <carrito_id>
python -m agora cli chat
python -m agora cli trazas --seguir
```

`emitir` arma el carrito y firma en un paso (la misma persona opera la
terminal). Si un cobro queda esperando confirmación humana —habitual con un
mandato cortado exacto al carrito— la terminal muestra el `retomar` exacto.
`python -m agora cli --help` lista todos los comandos.

### 7. Con Wompi real: recibir la confirmación

Contra Wompi los cobros no se confirman al instante: llegan por webhook. Sin
este paso, una compra por Nequi se queda en "pendiente" en el chat aunque el
banco ya la haya aprobado. Hacen falta tres terminales:

```bash
python -m agora api                          # 1. chat (puerto 8002)
python -m agora webhook                      # 2. receptor de eventos (puerto 8001)
ngrok http 8001                              # 3. túnel público (o cloudflared)
```

En el panel de Wompi de **cada** comercio (Desarrolladores → Eventos) pega la
URL del túnel seguida de `/pagos/wompi/transacciones/<comercio_id>`. Un solo
túnel sirve para todos los comercios. El recorrido completo, con el
enrolamiento real y lo que responde Wompi en cada paso, está en
[`docs/flujo-operativo-de-punta-a-punta.md`](docs/flujo-operativo-de-punta-a-punta.md).

## El experimento

La pregunta no es "¿el agente puede pagar?" sino "¿cuánto detiene el mandato
cuando algo sale mal?". Por eso existe un brazo de comparación: el motor de
pagos puede correr sin exigir el mandato (`exigir_mandato=False`) y registrar
igual las violaciones. La diferencia entre las dos corridas es el efecto real
del control — y el primer resultado fue un cobro de 15.000 COP aprobado por
la pasarela contra un mandato que autorizaba 8.000. La bitácora de cobros
(`agora_datos/recibos.jsonl`) es esa evidencia: nunca se sobreescribe.

Los topes duros nunca se apagan por parámetro: si se pudiera, apagar el
control que se está midiendo apagaría también la protección del dinero real.

## Qué prueba esto, y qué no

Prueba que un agente puede completar una compra sobre infraestructura de
pagos colombiana real, dentro de límites que una persona autorizó y que un
sistema aparte hace cumplir — y que ese sistema detiene los casos donde el
agente pide más de lo autorizado. Con dos comercios reales de Wompi en el
mismo proceso, también muestra que un mandato firmado para un comercio cobra
con las credenciales de ese comercio y no de otro.

No prueba una separación criptográfica completa entre comercios: la
correspondencia medio↔comercio la garantiza `EmitirMandatoUseCase` al firmar,
pero no viaja dentro de la firma ni se reverifica al cobrar — deuda técnica
documentada a propósito (ADR-8 en [`docs/arquitectura.md`](docs/arquitectura.md)).

## Datos y configuración

| Archivo | Qué es |
|---|---|
| `.env` (no versionado) | Modo de arranque y credenciales. Plantilla en `docs/variables-de-entorno.md`. |
| `agora_datos/agora.db` (no versionado) | SQLite: usuarios y sus llaves, medios de pago, mandatos, consumo, carritos, propuestas y estados. |
| `agora_datos/recibos.jsonl` · `trazas.jsonl` | Bitácora de cobros (evidencia del experimento) y trazas de cada turno del agente. |
| `agora_datos/secretos/comercios_wompi.json` | Credenciales de Wompi por comercio (`AGORA_WOMPI_COMERCIOS`). |
| `model/pago/topes.py` | Los topes duros. Constantes a propósito. |
| `app_service/config/configuracion.py` | Lee y valida el entorno; impide arrancar con combinaciones inseguras (Wompi en producción con persistencia en memoria). |

## Documentos

- [`Documentacion.md`](Documentacion.md) — referencia técnica: cada módulo,
  la API, la CLI, el modelo de mandato, la persistencia y las variables de
  entorno.
- [`docs/arquitectura.md`](docs/arquitectura.md) — la forma del sistema y las
  decisiones (ADRs).
- [`docs/arquitectura-agentes/`](docs/arquitectura-agentes/) — el módulo de
  agentes: grafo del turno, agentes especializados, búsqueda en tres peldaños,
  pausa humana y validación contra modelos reales.
- [`docs/flujo-propuesta-mandato.md`](docs/flujo-propuesta-mandato.md) — el
  sistema de mandatos por dentro: dónde vive cada cosa, la criptografía y cómo
  firma la persona.
- [`docs/flujo-operativo-de-punta-a-punta.md`](docs/flujo-operativo-de-punta-a-punta.md)
  — qué tener corriendo, y en qué orden, para una compra real.
- [`docs/variables-de-entorno.md`](docs/variables-de-entorno.md) — la
  plantilla comentada del `.env`.
- [`docs/diagramas/`](docs/diagramas/) — los diagramas en Mermaid.
- [`docs/utils/`](docs/utils/) — investigación de rieles de pago, el hallazgo
  del antifraude de Wompi y la viabilidad multi-comercio.
- [`evolucion-refactor/`](evolucion-refactor/) — la migración a la Clean
  Architecture de Bancolombia, fase por fase.
