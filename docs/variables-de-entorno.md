# Variables de entorno

El puente remoto no deja escribir archivos que empiecen por `.env`, asi que
esto va como documento. Copie el bloque a un `.env` en la raiz del proyecto
(ya esta en el `.gitignore`).

```dotenv
# Copiar a `.env` en la raiz. El .env real esta en el .gitignore.

# --- Pasarela y ambiente ---------------------------------------------------- #
AGORA_PASARELA=wompi        # simulada (default) | wompi
AGORA_AMBIENTE=produccion   # sandbox (default) | produccion

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

# --- Firma del titular (etapa 5) -------------------------------------------- #
# El par ed25519 que firma los mandatos, "igual que v1": si los archivos no
# existen, `composicion/contenedor.py` los genera la primera vez que arma un
# Contenedor. Sin cifrar en disco -- mismo alcance de PoC que las llaves de
# Wompi de arriba. No hace falta ponerlas en el .env para una demo: los
# defaults (agora_datos/secretos/firma.sk y firma.pk) alcanzan.
# AGORA_LLAVE_FIRMA_SK=agora_datos/secretos/firma.sk
# AGORA_LLAVE_FIRMA_PK=agora_datos/secretos/firma.pk
```
