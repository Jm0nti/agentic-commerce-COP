# Variables de entorno

El puente remoto no deja escribir archivos que empiecen por `.env`, asi que
esto va como documento. Copie el bloque a un `.env` en la raiz del proyecto
(ya esta en el `.gitignore`).

```dotenv
# Copiar a `.env` en la raiz. El .env real esta en el .gitignore.

# --- Pasarela y ambiente ---------------------------------------------------- #
AGORA_PASARELA=wompi        # simulada (default) | wompi
AGORA_AMBIENTE=produccion   # sandbox (default) | produccion

# --- Persistencia ------------------------------------------------------------ #
# De aca en adelante, sqlite para cualquier uso real -- ver
# `docs/limpieza-v1-boveda.md`. `memoria` sigue siendo un valor valido (lo usan
# muchas pruebas y sirve para una demo de un solo proceso), pero se pierde al
# reiniciar y `composicion/configuracion.py` ya prohibe combinarlo con
# AGORA_PASARELA=wompi + AGORA_AMBIENTE=produccion.
AGORA_PERSISTENCIA=sqlite           # memoria (default) | sqlite
# AGORA_SQLITE_PATH=agora_datos/agora.db   # opcional, ese es el default

# --- Wompi, MULTI-COMERCIO (1 de septiembre de 2026) ------------------------ #
# Desde que `agora/` soporta varios comercios reales de Wompi en el mismo
# proceso, las credenciales YA NO viven en variables `WOMPI_*` sueltas --
# esas solo alcanzan para UN comercio, y el puente remoto tampoco deja
# escribir un `.env` con una entrada por comercio de forma practica. En su
# lugar, `AGORA_PASARELA=wompi` lee un registro JSON, uno por comercio,
# indexado por el mismo `comercio_id` que usa el catalogo
# (`agora/adaptadores/catalogo/semilla/datos/catalogo.json`):
#
#   agora_datos/secretos/comercios_wompi.json   (default; ya en .gitignore
#                                                 via `agora_datos/`)
#
#     {
#       "com_xxxxxxxxxxxx": {
#         "public_key": "pub_prod_...",
#         "private_key": "prv_prod_...",
#         "integrity_secret": "prod_integrity_...",
#         "events_secret": "prod_events_..."
#       },
#       "com_yyyyyyyyyyyy": { ... }
#     }
#
# `events_secret` es el que valida el X-Event-Checksum de los webhooks
# (Dashboard > Desarrolladores > Eventos, uno por comercio). Sin el, el
# comercio queda operativo para cobrar pero `ConciliarEvento` marca sus
# eventos como invalidos -- webhook sin verificar es una via para
# inventarle a la app que un cobro paso.
#
# Cada comercio real tiene que apuntar su webhook a
# `<tu-URL-publica>/pagos/wompi/transacciones/<ese comercio_id>` -- un solo
# tunel, un solo puerto (8001), un segmento de URL por comercio. Ver
# `docs/viabilidad-multi-comercio-wompi.md` y el docstring de
# `entradas/webhooks/wompi.py`.
#
# Para apuntar el registro a otro archivo (por ejemplo, para separar
# sandbox de produccion):
# AGORA_WOMPI_COMERCIOS=agora_datos/secretos/comercios_wompi.sandbox.json

# --- Perfil del pagador ---------------------------------------------------- #
# Esto no es cosmetico. En un cobro contra fuente de pago no hay navegador, no
# hay IP del comprador, no hay 3DS y no hay push: `customer_data` es casi lo
# unico que el motor antifraude de Wompi tiene para decidir si el cobro es
# legitimo. Vacio, decide a ciegas.
#
# El valor por defecto era `boveda+poc@example.com`. `example.com` esta
# reservado por la RFC 2606: no existe y nunca va a entregar correo.
PAGADOR_EMAIL=tu.correo.real@dominio.com
PAGADOR_NOMBRE=Nombre Apellido
PAGADOR_TELEFONO=3001234567
PAGADOR_DOCUMENTO=1020304050
PAGADOR_TIPO_DOC=CC

# --- DeepSeek --------------------------------------------------------------- #
# Etapa 5: a diferencia de la version anterior de este documento, SI la lee
# `composicion/configuracion.py` ahora -- es lo que arma `contenedor.
# modelo_lenguaje` para el chat en vivo (`entradas/cli/ chat`). Sigue siendo
# opcional: sin ella, `contenedor.modelo_lenguaje` queda en `None` y el resto
# de la app (enrolar, emitir, pagar, navegar el catalogo) funciona igual --
# solo el comando `chat` avisa que falta y no arranca. Ver
# docs/etapa-5-agente-y-cli.md.
DEEPSEEK_API_KEY=sk-...
# DEEPSEEK_MODELO=deepseek-chat   # opcional, default deepseek-chat

# --- Clasificador de intencion (migracion a agentes, etapa 1) --------------- #
# Como decide el agente a que dominio pertenece cada mensaje antes de ejecutar
# el turno. Ver docs/etapa-1-agentes-clasificador-de-intencion.md.
#   hibrido  reglas primero; si se abstienen, una llamada extra a DeepSeek
#   reglas   solo reglas; lo dudoso va con las seis herramientas, como antes
#   apagado  sin clasificador: el agente de la etapa 7 tal cual
# AGORA_CLASIFICADOR=hibrido      # opcional, default hibrido

# --- Embeddings: soporte y catalogo (migracion a agentes, etapas 2 y 4) ----- #
# Embeddings de OpenAI, para DOS indices que nunca se mezclan:
#   - la documentacion de soporte (docs/soporte/), etapa 2;
#   - el catalogo de productos, etapa 4, como tercer peldano de
#     buscar_productos cuando el match por nombre no encuentra nada
#     ("algo para piel reseca").
# Opcional y sin variable propia para cada uno: sin la llave, soporte contesta
# sin documentacion y el catalogo se navega con el match estructurado de
# siempre -- el resto de la app no cambia. El chat sigue siendo DeepSeek; esta
# llave solo embebe documentacion, productos y consultas. Ver
# docs/etapa-2-agentes-soporte-rag-documental.md y
# docs/etapa-4-agentes-especializados-retrieval-hibrido.md.
OPENAI_API_KEY=sk-...
# AGORA_EMBEDDINGS_MODELO=text-embedding-3-small   # opcional
# AGORA_SOPORTE_DOCUMENTOS=docs/soporte             # opcional; tiene que existir si hay llave

# --- Trazabilidad del agente ------------------------------------------------ #
# Una linea .jsonl por cada turno de chat, con la cadena completa de decisiones:
# que clasifico el orquestador y con que confianza, que agente atendio, que
# herramientas se le ofrecieron al modelo, cuales pidio, cuales se le RECHAZARON
# por estar fuera de ruta, que documentacion se le inyecto y de que archivos,
# cuantas rondas dio el loop y cuanto tardo.
# Por defecto va al lado de AGORA_BITACORA (agora_datos/trazas.jsonl), en un
# archivo APARTE de recibos.jsonl: ese es la evidencia del experimento de dinero
# y no se mezcla con transcripciones de chat.
# Se lee desde otra terminal:  python -m agora.entradas.cli trazas --seguir
# Contiene lo que escribio la persona: tratarlo como transcripcion.
# AGORA_TRAZAS=agora_datos/trazas.jsonl   # opcional

# --- Orquestacion del turno (migracion a agentes, etapa 3) ------------------ #
# Si el turno corre como grafo de LangGraph (orquestador -> trabajador -> fin)
# o derecho, como en las etapas 1-2. Los dos modos hacen exactamente lo mismo:
# los nodos del grafo llaman a los mismos metodos del agente, y hay una prueba
# de equivalencia que lo verifica. Ver docs/etapa-3-agentes-grafo-langgraph.md.
#   grafo    por el grafo. Exige `langgraph` instalado
#            (pip install -r requirements.txt).
#   directo  el agente de las etapas 1-2, sin grafo ni dependencia de
#            LangGraph. El interruptor para una demo, o para un venv que
#            todavia no instalo langgraph.
# AGORA_ORQUESTACION=grafo        # opcional, default grafo

# --- Firma del titular (etapa 5) -------------------------------------------- #
# El par ed25519 que firma los mandatos, "igual que v1": si los archivos no
# existen, `composicion/contenedor.py` los genera la primera vez que arma un
# Contenedor. Sin cifrar en disco -- mismo alcance de PoC que las llaves de
# Wompi de arriba. No hace falta ponerlas en el .env para una demo: los
# defaults (agora_datos/secretos/firma.sk y firma.pk) alcanzan.
# AGORA_LLAVE_FIRMA_SK=agora_datos/secretos/firma.sk
# AGORA_LLAVE_FIRMA_PK=agora_datos/secretos/firma.pk
```
