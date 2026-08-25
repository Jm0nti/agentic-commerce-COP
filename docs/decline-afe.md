# El primer cobro real lo detuvo el antifraude

**19 de agosto de 2026** · transacción `1509872-1787154512-67009` · `environment: prod`

---

## 1. Son dos fallas distintas, y solo una importa

El debugger muestra un cuadro rojo que dice `Error`. Eso **no** es el cobro
fallando: es Wompi intentando avisarte del resultado y no logrando entregarlo.

| | Qué falló | Consecuencia |
|---|---|---|
| **El cobro** | El antifraude de Wompi lo rechazó | `DECLINED`. No se movió dinero |
| **El webhook** | Tu URL de eventos no responde | Te quedaste sin la notificación |

*"No se obtuvo respuesta del servidor del comercio en la URL de eventos
especificada"* apunta a
`https://comercioagenticoprueba.co/pagos/wompi/transacciones`, un dominio que no
contesta. Wompi reintenta hasta 3 veces en 24 horas y se rinde. **El webhook no
tiene nada que ver con el rechazo** — se dispara después, para contarte lo que
ya pasó. Se arregla aparte (sección 6).

---

## 2. El diagnóstico

Dos campos lo dicen sin ambigüedad:

```json
"status_message": "Por motivos de seguridad no pudimos procesar tu pago..."
"payment_method": { "afe_decision": "DECLINE" }
```

**AFE = el motor antifraude de Wompi.** Su propia página de seguridad lo
describe como protección *"24/7 aplicando todas las reglas antifraude y
prevención de riesgo"*. Las reglas **no son visibles ni configurables por el
comercio**.

Lo que esto descarta:

- **No fue Nequi.** La transacción nunca llegó allá.
- **No fue saldo insuficiente.** Ese caso da otro mensaje.
- **No fue el mandato.** La verificación estaba encendida y no reportó ninguna
  violación: la bóveda dejó pasar el cobro y llamó a Wompi.
- **No fue el monto.** 2.000 COP está sobre el mínimo.

Y una aclaración sobre lo que esperabas: **en Fase B no llega ningún push a
Nequi.** El push existe una sola vez, al enrolar. Desde que la fuente queda
`AVAILABLE`, el titular no se entera de ningún cobro. Eso no es una falla —
es exactamente el hueco que la PoC estudia.

---

## 3. Por qué saltó, probablemente

No se puede saber con certeza desde afuera. Pero el payload que enviamos es,
visto por un motor de riesgo, indistinguible de un fraude automatizado:

| Señal | Valor enviado | Cómo lo lee un motor de riesgo |
|---|---|---|
| `customer_email` | `boveda+poc@example.com` | Dominio reservado por la **RFC 2606**. No existe, no entrega, nunca va a entregar |
| `customer_data` | `null` | Sin nombre, sin teléfono, sin documento |
| `redirect_url` | `null` | Sin origen de navegador |
| `origin` | `null` | Sin canal identificable |
| `is_three_ds` | `false` | Sin autenticación fuerte |
| Monto | 2.000 COP | Micro-monto, patrón clásico de prueba de credencial |
| Antigüedad | Fuente y comercio recién creados | Primera transacción de la historia de la cuenta |
| Circuito | Comercio y pagador son la misma persona | Patrón de autocompra |

**Lo predijiste en tu propio README:**

> *Avisarle al equipo de Wompi. Un comercio cobrándose a sí mismo en bucle es el
> patrón que dispara monitoreo antifraude.*

Eso fue. La nota estaba escrita antes de que pasara.

---

## 4. El hallazgo — y es mejor que una aprobación

Esta corrida produce un resultado más interesante que si hubiera dado
`APPROVED`. Mira qué controles había en el camino y cuál actuó:

| Control | ¿Actuó? | ¿Quién lo controla? |
|---|---|---|
| Mandato firmado ed25519 | **No** — la intención cabía dentro | El comercio (nosotros) |
| Consentimiento del titular | **No** — no hay push en Fase B | Nadie, por diseño del riel |
| Topes duros de la bóveda | **No** — 2.000 < 20.000 | El comercio |
| 3DS / autenticación fuerte | **No existe** para Nequi | — |
| **Antifraude de la pasarela** | **Sí** | **Wompi. Opaco al comercio y al titular** |

> **Lo único que detuvo un cobro iniciado por un agente sobre rieles
> colombianos fue una caja negra que el comercio no puede ver, no puede
> configurar, no puede auditar y no puede explicarle al titular.**

Las implicaciones para el informe:

1. **La capa de mandato no fue el control efectivo.** Fue *correcta* — no había
   violación que reportar — pero no fue lo que evitó nada. Un mandato bien hecho
   y una ausencia total de mandato habrían dado el mismo resultado.
2. **El brazo de comparación se contamina.** Correr `--sin-mandato` esperando ver
   la diferencia no la va a mostrar mientras el AFE rechace ambos brazos. Hay que
   llegar a que el AFE apruebe **antes** de que el experimento mida algo.
3. **Es un control que no se puede razonar.** Si mañana aprueba, no sabremos por
   qué; si rechaza, tampoco. Para una PoC sobre gobernanza de pagos agénticos,
   que el único control efectivo sea inauditable es el resultado.
4. **El titular no tiene forma de enterarse.** Sin push en Fase B y con el webhook
   roto, ni el que paga ni el que cobra sabe qué pasó. Solo Wompi.

---

## 5. Qué cambió en el código

**El bug real:** `nucleo.py` construía el `Recibo` con `motivo=estado` y
descartaba `status_message` y `afe_decision`. La API ya había contestado el
diagnóstico y lo estábamos tirando — por eso hubo que abrir el debugger del
dashboard para leer algo que ya teníamos.

```
boveda/nucleo.py       Recibo captura status_message y afe_decision;
                       propiedad detenido_por_antifraude;
                       cobrar() acepta customer_data e ip;
                       perfil_pagador() lee el .env;
                       ClienteWompi.consultar()
boveda/cli.py          ejecutar imprime mensaje y antifraude;
                       preflight audita el perfil del pagador;
                       recibos marca los detenidos por AFE;
                       comando nuevo: diagnostico
boveda/eventos.py      receptor FastAPI con validacion de X-Event-Checksum
tests/test_eventos.py  11 pruebas sobre el checksum, con el evento real
.env.ejemplo           las variables nuevas
```

Ahora el mismo rechazo se lee sin salir de la terminal:

```
  ejecutado    False
  motivo       DECLINED
  transaccion  1509872-1787154512-67009
  estado       DECLINED
  antifraude   DECLINE
  mensaje      Por motivos de seguridad no pudimos procesar tu pago...

  Lo detuvo el motor antifraude de la pasarela (AFE), no el mandato.
  El mandato se cumplio: no hubo violaciones y la boveda dejo pasar el
  cobro. El unico control que actuo es el que el comercio no puede ver,
  ni configurar, ni explicarle al titular.
```

Y para cualquier transacción pasada:

```bash
python -m boveda.cli --modo produccion diagnostico 1509872-1787154512-67009
```

---

## 6. Qué hacer, en orden

### Primero: no reintentar en bucle

Wompi lista los *"múltiples intentos fallidos de compra"* entre las señales que
vigila. Cada reintento empeora el perfil. **Para hasta haber cambiado algo.**

### 1. Llenar el perfil del pagador

Copia `.env.ejemplo` y llena:

```
PAGADOR_EMAIL=tu.correo.real@dominio.com
PAGADOR_NOMBRE=Nombre Apellido
PAGADOR_TELEFONO=3232014944
PAGADOR_DOCUMENTO=1020304050
PAGADOR_TIPO_DOC=CC
```

Verifica con `preflight`, que ahora audita este perfil.

Esto **no es maquillar la transacción**: es enviar lo que envía cualquier
integración real. Lo anómalo era el `null`. Aun así, **no garantiza que el AFE
apruebe** — es quitar las señales obvias, no negociar con el motor.

> **Nota sobre `customer_data`:** los nombres exactos de los subcampos
> (`full_name`, `phone_number`, `legal_id`, `legal_id_type`) siguen la convención
> del checkout de Wompi, pero la documentación pública del endpoint solo dice
> *"datos adicionales del cliente (nombre, teléfono, dirección, etc.)"* sin
> especificarlos. Si Wompi devuelve 422, ese es el sitio a ajustar.

### 2. Escribirle a Wompi — esto es lo que de verdad desbloquea

El AFE no es configurable por el comercio. Solo ellos pueden decir qué regla
saltó y autorizar el patrón de prueba. Texto sugerido:

> Asunto: Transacción declinada por antifraude en integración de pruebas — `1509872-1787154512-67009`
>
> Buen día,
>
> Soy comercio persona natural en plan Avanzado Agregador. Estoy desarrollando
> una prueba de concepto técnica sobre pagos iniciados por agentes de software,
> con foco en controles de fraude.
>
> La transacción `1509872-1787154512-67009` (2.000 COP, NEQUI, fuente de pago
> 22620436) quedó `DECLINED` con `afe_decision: "DECLINE"` y el mensaje "Por
> motivos de seguridad no pudimos procesar tu pago".
>
> Entiendo que el patrón es atípico y lo declaro por adelantado: es un circuito
> cerrado, yo soy el comercio y el pagador, montos entre 1.000 y 20.000 COP,
> baja frecuencia, con topes duros en el código. No hay intención comercial.
>
> Quisiera saber:
>
> 1. ¿Qué señal disparó el rechazo? ¿Fue el `customer_data` vacío, el correo en
>    dominio de ejemplo, el monto, o el patrón de autocompra?
> 2. ¿Hay forma de registrar este comercio como entorno de pruebas con dinero
>    real, o alguna lista de excepción para un caso declarado?
> 3. ¿Enviar `customer_data` completo e `ip` cambia la evaluación en cobros
>    contra fuente de pago?
> 4. ¿Existe algún indicador para declarar que la transacción fue **iniciada por
>    un agente** en nombre del titular? (En AP2 sería el *Payment Mandate*.)
>
> Gracias,

La pregunta 4 casi seguro tiene respuesta negativa — y esa ausencia es un
hallazgo del informe, no un problema del trámite.

### 3. Arreglar la URL de eventos

Dos opciones. **Quitarla del dashboard** si no la vas a usar todavía, o
**levantar el receptor** que ya quedó escrito:

```bash
uvicorn boveda.eventos:app --port 8000
# exponerlo con ngrok / cloudflared y poner esa URL publica en
# Dashboard > Desarrolladores > Eventos
```

Valida el `X-Event-Checksum` con la fórmula que Wompi especifica:
`SHA256(valores de signature.properties + timestamp + secreto)`. Necesita
`WOMPI_EVENTS_SECRET` en el `.env`.

**Validarlo no es opcional.** Sin verificación, cualquiera que conozca la URL
puede POSTear un `transaction.updated` con `status: APPROVED` y hacerle creer a
la bóveda que un cobro pasó. Es la superficie de ataque más barata del sistema:
no hay que robar credenciales, basta con adivinar un endpoint. Hay pruebas
dedicadas a los dos ataques útiles — alterar el monto y alterar el estado.

### 4. Recién entonces, reintentar

Un solo cobro. Si vuelve a dar `DECLINE`, es Wompi quien tiene la respuesta, no
el código.

---

## 7. Lo que no sé

- **Qué regla del AFE saltó.** No es público y no es inferible desde afuera. Todo
  lo de la sección 3 son hipótesis ordenadas por verosimilitud.
- **Si `afe_decision` aparece siempre** o solo cuando el motor interviene. Con una
  sola transacción no se distingue.
- **Si llenar `customer_data` cambia algo.** Es la hipótesis más razonable y la
  más barata de probar, pero es una hipótesis.
- **Los nombres exactos de los subcampos de `customer_data`** (ver nota arriba).
- **Si el enrolamiento quedó bien.** La fuente `22620436` existe y el cobro llegó
  a evaluarse, así que sí. Pero conviene confirmar que sigue `AVAILABLE`:
  `python -m boveda.cli --modo produccion fuentes`

---

## Fuentes

- [Seguridad para negocios — Wompi](https://wompi.com/es/co/beneficios/seguridad)
- [Eventos — Wompi Docs](https://docs.wompi.co/en/docs/colombia/eventos/)
- [Seguimiento de transacciones — Wompi Docs](https://docs.wompi.co/en/docs/colombia/seguimiento-de-transacciones/)
- [Transacciones — Wompi Docs](https://docs.wompi.co/en/docs/colombia/transacciones/)
- [Errores transaccionales — Wompi](https://soporte.wompi.co/hc/es-419/articles/36482482930707-Cuales-son-los-errores-transaccionales-que-pueden-ocurrir)
- [RFC 2606 — Reserved Top Level DNS Names](https://www.rfc-editor.org/rfc/rfc2606)
