# PoC de comercio agéntico sobre rieles colombianos

Un agente conversacional le compra algo a una persona. El dinero sale de una
cuenta Nequi real, sobre Wompi. Lo que este repositorio estudia es lo que pasa
en el medio: qué autoriza el titular, qué intenta ejecutar el agente, y cuánto
de la diferencia entre esas dos cosas alcanza a detenerse antes de que se mueva
un peso.

## La idea en una frase

> **El agente propone. El humano firma. La bóveda ejecuta.**
> Ninguno de los tres puede hacer el trabajo de otro.

En la práctica: una persona chatea con un agente de IA para comprarle algo a uno
de los comercios (simulados, para esta demo). El agente busca productos, arma un
carrito y *propone* una autorización de pago — nunca la firma él mismo, porque
no tiene la llave para hacerlo. La persona ve exactamente qué se le pide
autorizar (qué comercio, qué monto máximo, por cuánto tiempo, para cuántos
usos) y firma esa autorización con un clic o un comando, en su propio
dispositivo. Solo entonces el agente puede pedirle a la "bóveda" que cobre —y
la bóveda vuelve a revisar todo (firma, vigencia, monto, comercio, que el
carrito no haya cambiado) antes de llamar a la pasarela de pagos real.

Además de esa autorización específica (el "mandato"), existen **topes duros**
que nunca se pueden desactivar, ni siquiera para experimentar: protegen el
dinero real independientemente de que el mandato falle o se manipule.

## Qué hay hoy en este repositorio

Conviven dos árboles de código con roles distintos:

| | `boveda/` (v1) | `agora/` (v2) |
|---|---|---|
| Qué es | El experimento original, mínimo | La aplicación demostrativa completa |
| Estado | Ya movió dinero real en producción (Fase A + Fase B) | Arquitectura completa y probada (dominio, adaptadores, agente, CLI, API web, webhook) |
| Interfaz | Solo línea de comandos | CLI **y** una página web de chat con firma integrada |
| Agente de IA | No tiene | Sí — DeepSeek, con seis herramientas y una frontera dura verificada por pruebas |
| Catálogo de comercios | No tiene | Sí, simulado y generado con IA (2 comercios: Dulcería La Golosina, Papelería El Lápiz Feliz) |
| Se recomienda para | Referencia histórica del primer hallazgo (ver más abajo) | Usar y extender de acá en adelante |

`agora/` es la reescritura ordenada de la misma idea de `boveda/`, siguiendo
una arquitectura por capas (`docs/arquitectura-v2.md`). Está construida en
seis etapas, todas completas a la fecha de este documento, con 478
pruebas automatizadas en verde. La diferencia importante frente a `boveda/`:
**se puede correr contra la pasarela simulada sin gastar un peso**, o contra
Wompi real cambiando una sola variable de entorno.

`wompi_lab/` es un banco de pruebas antiguo, congelado — se conserva solo
porque tiene el único código del repo que sabe hacer dispersiones (payouts)
por Bre-B.

## Arquitectura, de un vistazo

```
        entradas/            composicion/
     (cli, api web,          (el único que arma
      webhook)                 todo y lee el .env)
           │                        │
           ▼                        ▼
   ┌─────────────────────────────────────┐
   │            aplicacion/               │  casos de uso
   │   EjecutarIntencion, EmitirMandato…  │
   └─────────────────────────────────────┘
           │                        ▲
           ▼                        │ implementan
   ┌───────────┐             ┌──────────────┐
   │ puertos/  │◄────────────│ adaptadores/ │  wompi, simulada,
   │(interfaces)│             │              │  sqlite, deepseek
   └───────────┘             └──────────────┘
           │
           ▼
   ┌─────────────────────────────────────┐
   │              dominio/                │  reglas puras, sin red
   │   Mandato, Intención, Dinero…        │
   └─────────────────────────────────────┘

   agente/  →  solo ve dominio/ y puertos/. Nunca puede importar
               una pasarela de pagos ni la llave de firma — una
               prueba (tests/test_fronteras.py) rompe el build si
               alguien lo intenta.
```

El detalle completo de cada módulo está en **`Documentacion.md`**, en la raíz
del repositorio.

## Cómo correrlo, paso a paso

### 0. Requisitos

Python 3.10 o superior y `pip`.

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 2. Crear el archivo de configuración

Copiar la plantilla de `docs/variables-de-entorno.md` a un archivo `.env` en
la raíz del repositorio (ya está en `.gitignore`: nunca se sube a control de
versiones). Como mínimo, para empezar sin tocar dinero real, alcanza con:

```dotenv
AGORA_AMBIENTE=sandbox
AGORA_PASARELA=simulada
AGORA_PERSISTENCIA=sqlite
```

Ver la sección **Archivos de configuración** más abajo para el resto de las
variables (Wompi, el perfil del pagador, DeepSeek).

### 3. Correr las pruebas

```bash
python -m pytest tests/ -q
```

Deberían quedar las 478 en verde.

### 4. Explorar el catálogo simulado

```bash
python -m agora.entradas.cli comercios
python -m agora.entradas.cli productos <comercio_id>
python -m agora.entradas.cli producto <producto_id>
```

### 5. Autorizar un medio de pago (una sola vez, "Fase A")

Con `AGORA_PASARELA=simulada` esto no toca ninguna cuenta real — genera un
medio de pago de mentiras al instante. Con `AGORA_PASARELA=wompi` en
producción, esto le manda un push de verdad a la app Nequi del titular.
Multi-comercio: `--comercio` es obligatorio — el medio queda vinculado a ESE
comercio, no a "cualquiera" (ver `docs/flujo-propuesta-mandato.md`, sección 6):

```bash
python -m agora.entradas.cli enrolar --telefono 3001234567 --titular tit_demo --comercio <comercio_id>
python -m agora.entradas.cli fuentes tit_demo
```

**También se puede hacer sin la terminal**, desde el navegador: con el
servidor web corriendo (paso 7), abrí `http://localhost:8002`, poné el
`titular_id` arriba a la derecha y hacé clic en "Medios de pago". Ahí mismo
se enrola un medio nuevo (teléfono + correo) y se ven los que ya están
enrolados para ese titular — funciona igual con `AGORA_PASARELA=simulada`
que con `wompi` (sandbox o producción, según `AGORA_AMBIENTE`).

### 6. Comprar a mano, desde la terminal

Cuando la misma persona opera la terminal de punta a punta, un solo comando
arma el carrito y firma el mandato:

```bash
python -m agora.entradas.cli emitir <comercio_id> tit_demo --item <producto_id>:1
python -m agora.entradas.cli pagar <mandato_id> <carrito_id>
```

Si el pago queda "esperando confirmación humana" (es habitual: un mandato
cortado exacto al carrito dispara una señal de revisión), la terminal muestra
el comando exacto para resolverlo:

```bash
python -m agora.entradas.cli retomar <intencion_id> <mandato_id> <carrito_id>
python -m agora.entradas.cli estado <intencion_id>
```

### 7. Chatear con el agente de IA

Necesita una llave de DeepSeek (`DEEPSEEK_API_KEY` en el `.env`). Hay dos
formas de probarlo:

**Por terminal:**

```bash
python -m agora.entradas.cli chat
```

El agente puede buscar comercios y productos, armar un carrito y pedirte que
lo pagues — pero cuando llega el momento de autorizar, te va a pasar un
comando exacto (`firmar <propuesta_id> <titular>`) para que lo corras vos
mismo, en otra terminal. El agente nunca puede firmar nada.

**Por navegador (recomendado para una demo):**

```bash
python scripts/servir_api.py
```

Y abrir `http://localhost:8002` en el navegador. Es una sola página: se
chatea con el agente y, cuando hay algo que firmar o confirmar, aparece un
recuadro emergente para que la persona lo resuelva ahí mismo, sin cambiar de
ventana ni de terminal. El botón "Medios de pago" del encabezado (ver paso 5)
también vive en esta misma página.

### 8. (Solo en producción) Recibir la confirmación de Wompi

Los cobros contra Wompi real no se confirman al instante: llegan por webhook.
**Sin este paso, cualquier compra por Nequi se queda mostrando "pendiente"
para siempre en el chat**, aunque Wompi ya la haya aprobado del lado del
banco — el dinero sale igual, pero esta app nunca se entera. Es un proceso
aparte del chat (paso 7), así que hacen falta dos terminales corriendo al
mismo tiempo:

**Terminal 2 — arrancar el receptor:**

```bash
python scripts/servir_webhook_wompi.py
```

Confirmá que responde con `curl http://localhost:8001/salud`.

**Terminal 3 — exponerlo a internet** (elegí una opción; ninguna requiere
tocar el código):

```bash
# Opción A: cloudflared (no pide cuenta para un tunel rapido)
cloudflared tunnel --url http://localhost:8001

# Opción B: ngrok (pide una cuenta gratuita y un authtoken una sola vez)
ngrok http 8001
```

Cualquiera de las dos imprime una URL pública (`https://algo.trycloudflare.com`
o `https://algo.ngrok-free.app`).

**Panel de Wompi:** Desarrolladores → Dashboard general, pegar la URL completa
**con la ruta incluida, terminada en el `comercio_id` de ESE comercio**
(multi-comercio: un solo túnel y un solo puerto sirven para todos los
comercios, pero cada uno tiene su propia entrada en el panel de Wompi, con
su propio segmento de URL — ver `AGORA_WOMPI_COMERCIOS` en
`docs/variables-de-entorno.md`):

```
https://algo-al-azar.trycloudflare.com/pagos/wompi/transacciones/<comercio_id>
```

Con las tres terminales corriendo (chat, webhook, túnel), la consola de
`servir_webhook_wompi.py` va a mostrar `[ok ] APPROVED intencion=...` en
cuanto Wompi confirme un cobro, y el chat va a mostrar el resultado solo,
sin que haga falta volver a preguntarle al agente (etapa 9, ver
`Documentacion.md`).

Con un túnel gratuito la URL cambia cada vez que lo reiniciás — hay que
volver a pegarla en el panel de Wompi cada vez. Si esto va a quedar
corriendo por más tiempo, conviene un dominio fijo (ngrok con plan pago, o
un túnel nombrado de Cloudflare) para no repetir ese paso.

### 9. La CLI del sistema original (`boveda/`)

Se conserva porque ya hizo transferencias reales y es donde está documentado
el primer hallazgo del proyecto (ver más abajo). No hace falta para usar
`agora/`:

```bash
python -m boveda.cli --modo produccion preflight
python -m boveda.cli --modo produccion enrolar --telefono 3001234567
python -m boveda.cli --modo produccion emitir --monto 8000
python -m boveda.cli --modo produccion ejecutar <mandato_id> -m 8000
```

## El experimento

La pregunta que dio origen al proyecto no es "¿el agente puede pagar?" sino
"¿cuánto detiene el mandato cuando algo sale mal?". Por eso existe un brazo de
comparación: se puede pedir que la bóveda **no** exija el mandato
(`--sin-mandato` en `boveda.cli`, o `exigir_mandato=False` en el motor de
`agora/`) y ver si la pasarela deja pasar igual un cobro que el mandato habría
bloqueado. La diferencia entre las dos corridas es el efecto real del control.

Los **topes duros** (ver la tabla de configuración abajo) nunca se pueden
apagar por parámetro. Si se pudieran, apagar el control que se está midiendo
apagaría también la protección del dinero real.

## Archivos de configuración

| Archivo | Qué controla |
|---|---|
| `.env` (raíz, no versionado) | Todas las credenciales y el modo de arranque. Plantilla completa y comentada en `docs/variables-de-entorno.md`. |
| `agora_datos/secretos/comercios_wompi.json` (no versionado, ruta en `AGORA_WOMPI_COMERCIOS`) | Multi-comercio: credenciales de Wompi por comercio (`public_key`, `private_key`, `integrity_secret`, `events_secret`), indexadas por el mismo `comercio_id` del catálogo — reemplaza las variables `WOMPI_*` sueltas de un solo comercio. Plantilla en `docs/variables-de-entorno.md`. |
| `agora/composicion/configuracion.py` | Lee y valida esas variables para `agora/`: valores por defecto, y reglas que impiden arrancar con una combinación insegura (por ejemplo, Wompi real con persistencia en memoria). |
| `agora/dominio/pago/topes.py` | Los topes duros de `agora/`: **20.000 COP por transacción, 100.000 COP por día**. Son constantes en el código a propósito — si se volvieran configurables, dejarían de ser la protección que permite estudiar el mandato apagándolo. |
| `boveda/nucleo.py` (líneas 46-47) | Los topes duros del sistema original (v1). **Advertencia:** hoy dicen `2.000.000` COP por transacción y `100.000` COP por día — no coincide con los `20.000` que describen este documento y `docs/flujo.md`. Ver el detalle en `Documentacion.md`, sección "Hallazgos", antes de operar `boveda.cli` contra producción. |
| `.gitignore` | Qué queda fuera del control de versiones: el `.env`, toda la carpeta `boveda/secretos/`, la carpeta `agora_datos/` (bitácora + base SQLite + llave de firma), y los archivos sueltos de fuentes de pago o recibos. |
| `requirements.txt` | Dependencias de Python (`fastapi`, `httpx`, `uvicorn`, `cryptography`, `pytest`, `python-dotenv`, `openai`). |

## Antes de tocar producción

- **Avisar al equipo de Wompi.** Un comercio cobrándose a sí mismo en bucle es
  el patrón que dispara su monitoreo antifraude; que congelen la cuenta a
  mitad del experimento cuesta semanas.
- **Presupuestar la comisión** (2,65 % + $700 + IVA por transacción aprobada).
  En un circuito cerrado, cada vuelta pierde el fee — con cobros de pocos
  miles de pesos, la comisión puede superar el monto.
- **Nequi antes que tarjeta**: cero superficie de datos de tarjeta,
  consentimiento observable por push, revocación en un comando.
- El primer cobro real de este proyecto (2.000-2.050 COP) fue **rechazado por
  el motor antifraude de Wompi**, no por el mandato ni por falta de fondos —
  ver `docs/decline-afe.md` y la sección "Hallazgos" de `Documentacion.md`.

## Qué prueba esto, y qué no

Prueba que un agente conversacional puede completar una compra sobre
infraestructura de pagos colombiana real, dentro de límites que una persona
autorizó explícitamente y que un sistema aparte hace cumplir — y que ese
sistema efectivamente detiene los casos donde el agente pide más de lo
autorizado. Con dos comercios reales de Wompi conviviendo en el mismo
proceso (`AGORA_WOMPI_COMERCIOS`), también ejercita que un mandato firmado
para un comercio cobra contra las credenciales de ESE comercio, y no las de
otro.

No prueba una separación criptográfica completa entre comercios: la
correspondencia entre el medio de pago y el comercio la garantiza
`EmitirMandato` al firmar (`RepositorioMedios.vinculado_con`), pero no viaja
dentro de la firma del mandato ni se reverifica al cobrar — una deuda
técnica documentada a propósito, no un descuido (ver
`docs/flujo-propuesta-mandato.md`, sección 6).

## Documentos

- **`Documentacion.md`** (raíz del repo) — el detalle técnico completo: cada
  módulo, cada capa, el modelo de mandato, las variables de entorno, y los
  hallazgos encontrados hasta ahora.
- `docs/arquitectura-v2.md` (y su resumen visual, `docs/arquitectura-v2.html`)
  — la arquitectura objetivo y las decisiones detrás de cada una (ADRs).
- `docs/flujo-propuesta-mandato.md` — el recorrido completo del sistema de
  mandatos: dónde se guarda cada cosa, la criptografía detrás de la firma,
  cómo firma la persona, y por qué el agente nunca puede hacerlo él mismo.
- `docs/flujo-operativo-de-punta-a-punta.md` — que hay que tener
  corriendo y en que orden para una compra real: los tres procesos, el
  tunel, el login multiusuario, el enrolamiento, y como responde Wompi
  (sincrono y por webhook) para cada comercio.
- `docs/variables-de-entorno.md` — la plantilla comentada del `.env`.

