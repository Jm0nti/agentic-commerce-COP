# Variables de entorno

El puente remoto no deja escribir archivos que empiecen por `.env`, asi que
esto va como documento. Copie el bloque a un `.env` en la raiz del proyecto
(ya esta en el `.gitignore`).

```dotenv
# Copiar a `.env` en la raiz. El .env real esta en el .gitignore.

# --- Wompi ----------------------------------------------------------------- #
# El modo del CLI y el prefijo de la llave tienen que coincidir. `nucleo.py`
# se niega a arrancar si no.
WOMPI_PUBLIC_KEY=pub_prod_...
WOMPI_PRIVATE_KEY=prv_prod_...
WOMPI_INTEGRITY_SECRET=prod_integrity_...

# Secreto de eventos, para validar el X-Event-Checksum de los webhooks.
# Dashboard > Desarrolladores > Eventos. Sin esto, `boveda.eventos` marca
# todos los eventos como invalidos -- que es el comportamiento correcto:
# un webhook sin verificar es una via para inventarle a la boveda que un
# cobro paso.
WOMPI_EVENTS_SECRET=prod_events_...

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
```
