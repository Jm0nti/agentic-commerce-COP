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
# sqlite para cualquier uso real. `memoria` sigue siendo un valor valido (lo usan
# muchas pruebas y sirve para una demo de un solo proceso), pero se pierde al
# reiniciar y `app_service/config/configuracion.py` ya prohibe combinarlo con
# AGORA_PASARELA=wompi + AGORA_AMBIENTE=produccion.
AGORA_PERSISTENCIA=sqlite           # memoria (default) | sqlite
# AGORA_SQLITE_PATH=agora_datos/agora.db   # opcional, ese es el default

# --- Wompi, MULTI-COMERCIO  ------------------------ #
# Desde que `agora/` soporta varios comercios reales de Wompi en el mismo
# proceso, las credenciales YA NO viven en variables `WOMPI_*` sueltas --
# esas solo alcanzan para UN comercio, y el puente remoto tampoco deja
# escribir un `.env` con una entrada por comercio de forma practica. En su
# lugar, `AGORA_PASARELA=wompi` lee un registro JSON, uno por comercio,
# indexado por el mismo `comercio_id` que usa el catalogo
# (`driven_adapters/catalogo_semilla/datos/catalogo.json`):
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
# comercio queda operativo para cobrar pero `ConciliarEventoUseCase` marca sus
# eventos como invalidos -- webhook sin verificar es una via para
# inventarle a la app que un cobro paso.
#
# Cada comercio real tiene que apuntar su webhook a
# `<tu-URL-publica>/pagos/wompi/transacciones/<ese comercio_id>` -- un solo
# tunel, un solo puerto (8001), un segmento de URL por comercio. Ver
# `docs/utils/viabilidad-multi-comercio-wompi.md` y el docstring de
# `entry_points/webhook_wompi/wompi.py`.
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
# No uses un correo en `example.com` ni en otro dominio reservado por la
# RFC 2606: no existe, nunca entrega correo, y el antifraude lo lee como
# fraude (`docs/utils/decline-afe.md`).
PAGADOR_EMAIL=tu.correo.real@dominio.com
PAGADOR_NOMBRE=Nombre Apellido
PAGADOR_TELEFONO=3001234567
PAGADOR_DOCUMENTO=1020304050
PAGADOR_TIPO_DOC=CC

# LLM de Inferencia
DEEPSEEK_API_KEY=sk-...

# --- Embeddings
OPENAI_API_KEY=sk-...
# AGORA_EMBEDDINGS_MODELO=text-embedding-3-small   # opcional
# AGORA_SOPORTE_DOCUMENTOS=docs/soporte             # opcional
# AGORA_ORQUESTACION=grafo        # opcional, default grafo
```
