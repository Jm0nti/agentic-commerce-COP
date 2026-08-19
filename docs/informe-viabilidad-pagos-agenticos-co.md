# Pagos en comercio agéntico sobre rieles colombianos

**Viabilidad de una primera iteración con dinero real**
Consulta: 18 de agosto de 2026 · PoC `poc-agentic-commerce-fraud`

---

## 1. Respuesta corta

**Sí es posible, pero no por donde lo estás buscando.**

El API de Bancolombia —el catálogo público del API Market— **no tiene el primitivo que necesitas**. Ninguno de sus productos de pago permite que un tercero cobre contra una cuenta sin que el titular esté frente a la interfaz del banco en ese momento. El Botón Bancolombia redirige, siempre, y exige clave dinámica en cada transacción. Eso es incompatible por diseño con un agente que compra solo.

El primitivo que sí necesitas —**autorización una vez, cobro N veces después, sin el titular presente**— existe en Colombia en tres lugares:

| Riel | Producto | Estado para ti |
|---|---|---|
| Nequi directo | API de Suscripciones (débito automático) | Existe. Requiere contrato con Nequi para Negocios. Meses. |
| Wompi | Fuentes de pago (`payment_sources`) | Existe. **Sandbox ya lo probaste.** Producción en semanas. |
| Bancolombia directo | — | No existe en el catálogo público. |

La ruta con dinero real más corta es **Wompi en producción**, que es de Bancolombia y te expone Nequi, Transferencia Bancolombia y tarjetas detrás de una sola API. Con figura de persona natural el registro es autoservicio: RUT + cuenta bancaria.

**El matiz que define tu PoC:** una vez creada la fuente de pago, Wompi te deja cobrar sin tope, sin vencimiento y sin ligadura a un monto, un producto ni un comercio. Tu propio `lab.py` ya lo anota en el comentario de `cmd_source`. Ese hueco *es* el objeto de estudio: el riel colombiano entrega la llave completa y no entrega ningún mecanismo para limitarla. La capa de mandato la tienes que construir tú, y ahí es donde vive la investigación de fraude.

---

## 2. Qué hay realmente en el API de Bancolombia

Catálogo del API Market (`developer.bancolombia.com`), productos publicados:

**Pagos y transacciones**

- **Payment Button** (Botón Bancolombia) — recibir transferencias desde cuentas Bancolombia
- **QR Code** — pagos por código QR
- **BancolombiaPay** — billetera digital
- **Buy Now Pay Later (BNPL)** — 4 cuotas
- **Cash Withdrawal Management** — retiro por código

**Información financiera**

- Transactional Information, Economic Performance Data, Account Receivable

**Crédito y otros**

- Consumer Loan, Mortgage Loan Study, Leasing, Consignments (remesas), Control List Compliance, Security, Open Banking Use Cases

### 2.1 Por qué el Botón Bancolombia no sirve para la iteración 1

El flujo, según el SDK oficial de Placetopay y la documentación del sandbox:

1. El comercio crea la intención de pago con `clientId`, `clientSecret` y `commerceTransferButtonId`, enviando referencia, descripción, monto, `returnURL` y `confirmationURL`.
2. La respuesta trae un **`processUrl`**, un `transferCode` y un `transactionId`.
3. **El usuario es redirigido a la interfaz de Bancolombia** y autoriza allí con su clave dinámica.
4. Bancolombia hace POST al `confirmationURL`.

Los requisitos que publica el banco lo confirman: *"tanto el cliente como el negocio deben tener una cuenta activa que permita créditos y débitos"* y el usuario debe estar **inscrito en el servicio de clave dinámica**.

El paso 3 es un muro. No hay modo `TOKEN`, no hay credential-on-file, no hay mandato almacenado. Cada pago exige la presencia interactiva del titular en un dominio que tú no controlas. Un agente solo puede llegar hasta el paso 2 y entregarle el link a un humano.

> **Y no intentes rodearlo.** El Decreto 1297 de 2022, que regula los servicios de iniciación de pago en Colombia, obliga a que el proveedor obtenga autorización previa del pagador, lo autentique **en todos los casos**, y explícitamente **prohíbe solicitar contraseñas o claves**. Cualquier diseño donde el agente maneje la clave dinámica del usuario para automatizar el Botón queda fuera del marco. No es un problema técnico, es un problema de licencia.

### 2.2 Qué cuesta y qué exige llegar a producción

- **Sandbox:** se pide `Client-Id` y `Client-Secret` por el formulario de soporte. Es relativamente accesible.
- **Producción:** exige cuenta de ahorros o corriente **activa** en Bancolombia, negociación con ejecutivo de cuenta asignado, y firma del *Reglamento de APIs Bancolombia*. Las credenciales productivas se entregan al representante técnico designado **después de cerrar la negociación**.
- **Contrato:** SLA de 99.95%, rotación de llaves en 8 días calendario cuando se solicite, disponibilidad del 99.95% de tu aplicación, auditoría del banco sobre tu operación, destrucción de datos en 15 días hábiles al terminar. Para APIs de pago y transferencia, Bancolombia debita comisión diaria de **1.5% por transacción con tope de $3.000 COP** antes de remitir el neto.

Traducción para tu cronograma: el API directo de Bancolombia es una conversación comercial, no una integración autoservicio. No es el camino de la iteración 1.

---

## 3. Nequi directo (Nequi Conecta): el primitivo correcto, la puerta cerrada

Nequi sí publica exactamente lo que necesitas.

### 3.1 API de Suscripciones / débito automático

El modelo, en palabras de Nequi:

- El cliente vincula su cuenta Nequi al comercio mediante **una autorización única por notificación push en la app**.
- A partir de ahí, **el comercio decide cuándo y cuánto cobrar**. Monto variable, frecuencia definida por el comercio.
- Ningún cobro se ejecuta automáticamente: cada uno requiere acción explícita del comercio. (Es decir: el agente es quien dispara.)
- Confirmación por **webhook solo para pagos exitosos**, más `getStatus` para todos los estados.
- El usuario ve y cancela sus suscripciones activas desde la app Nequi.
- Solo funciona con usuarios Nequi. Sin interoperabilidad.

Esto es, literalmente, un mandato de pago delegado sobre dinero real colombiano. Es el mejor riel del país para comercio agéntico hoy.

### 3.2 Las otras APIs

- **Pagos con notificación Push** (`unregisteredPayments`) — el usuario aprueba **cada** pago en la app. Sirve como escalón de control, no como delegación.
- **Depósitos y retiros** (cash in / cash out).

**Autenticación:** hoy JWS sobre AWS Signature Version 4; la documentación anuncia migración a **OAuth 2.0 a partir del 1 de octubre**. Si integras directo, arranca contra OAuth 2.0.

### 3.3 El obstáculo

El acceso a Nequi Conecta pasa por ser cliente de **Nequi para Negocios** y firmar contrato. No hay sandbox de autoservicio equivalente al de Wompi. Para una persona natural que quiere probar en tres semanas, esto no llega a tiempo.

**Pero:** Wompi te da acceso a Nequi como fuente de pago con el mismo comportamiento de delegación, con una fricción comercial mucho menor. Ese es el atajo.

---

## 4. Wompi: el camino real

Wompi es de Bancolombia. Es, en la práctica, "el API de pagos de Bancolombia" para un comercio que no es una corporación.

### 4.1 Métodos y cuáles admiten fuente de pago

| Método | Type ID | ¿Fuente de pago? |
|---|---|---|
| Tarjetas | `CARD` | **Sí** (con 3DS obligatorio) |
| Nequi | `NEQUI` | **Sí** (token + aprobación en app) |
| Transferencia Bancolombia | `BANCOLOMBIA_TRANSFER` | **Sí** (modo TOKEN, recurrente) |
| DaviPlata | `DAVIPLATA` | **Sí** (OTP por SMS) |
| PSE | `PSE` | No |
| Bancolombia QR | `BANCOLOMBIA_QR` | No |
| Bancolombia Efectivo | `BANCOLOMBIA_COLLECT` | No |
| BNPL Bancolombia | `BANCOLOMBIA_BNPL` | No (mín. $100.000) |
| SU+ Pay | `SU_PLUS` | No ($35.000–$5.000.000) |
| PCOL | `PCOL` | Parcial |

Nota: la tabla de "Métodos de pago" de Wompi marca NEQUI sin tokenización, mientras que la página de "Fuentes de pago & Tokenización" documenta `/v1/tokens/nequi` explícitamente —y tu `lab.py` ya lo ejerció en sandbox. La documentación se contradice. **Confirma por escrito con soporte Wompi si las fuentes de pago Nequi están habilitadas en producción para tu comercio** antes de comprometer el diseño.

### 4.2 El flujo de delegación, en tres pasos

```
1. POST /v1/tokens/{cards|nequi|bancolombia_transfer}   → token
   (llave pública, lado cliente)
        ↓  el titular aprueba: challenge 3DS / push en Nequi / portal Bancolombia
2. POST /v1/payment_sources                             → payment_source_id
   (llave privada, requiere acceptance_token + accept_personal_auth)
        ↓  estado AVAILABLE
3. POST /v1/transactions { payment_source_id, amount }  → cobro
   (llave privada, N veces, sin el titular)
```

**Para tarjetas, 3DS es obligatorio al crear la fuente**, y hay que solicitar la activación a soporte Wompi **por separado para sandbox y para producción**. La contrapartida es buena: los cobros posteriores contra esa fuente quedan protegidos bajo **3RI** (3DS for Recurring Initiations), lo que traslada parte de la responsabilidad de fraude al emisor. Para tu PoC de fraude, la comparación entre una fuente con 3DS/3RI y una fuente Nequi sin equivalente es en sí un hallazgo.

### 4.3 Onboarding como persona natural

Es la figura que elegiste. Lo que aplica:

- **Registro:** `registro.wompi.co`. Documentos: **RUT actualizado** y **número de cuenta bancaria**. La información debe ser únicamente de quien registra.
- **Tope por transacción:** **$2.500.000 COP** (persona jurídica: $10.000.000).
- **Dispersión:** hasta 5 días hábiles desde la aprobación. **Ojo: para comercios persona natural nuevos, el primer desembolso puede retenerse 30 días desde la primera transacción.** El dinero se mueve de verdad, pero no vuelve rápido.
- **Retención por fraude:** Wompi puede retener fondos hasta **370 días** mientras investiga contracargos. Tienes 5 días hábiles para aportar soportes o quedas responsable del monto disputado.
- **Nequi bajo modelo Gateway:** **no es autoservicio.** Exige ejecutivo de cuenta, luego registro en `negocios.nequi.co/registro/wompi`, luego confirmación de Nequi por correo. Arranca este trámite el día uno, en paralelo.

### 4.4 Lo que dice el reglamento de comercios sobre credenciales almacenadas

Para el **Servicio de Pago Rápido** (el producto que ampara guardar el medio de pago), el reglamento te obliga a:

- Implementar **2FA**
- Exigir usuario y contraseña al comprador
- Contraseñas de 10+ caracteres con mayúsculas, minúsculas, números y especiales
- Validación estricta de todos los campos de entrada
- Atender en 15 días los reclamos sobre registro de cuenta y **retiro de autorizaciones**

Y en ventas no presentes, **el riesgo de fraude lo asume el comercio**.

Aquí hay una tensión que vale la pena nombrar en tu informe interno: el reglamento asume que del otro lado hay un humano con usuario y contraseña. En comercio agéntico no lo hay. El "2FA" que el reglamento exige no tiene dónde ejecutarse cuando quien compra es un agente en nombre del titular. **Es una brecha normativa real, no una omisión tuya**, y documentarla es probablemente uno de los entregables más valiosos de esta PoC.

---

## 5. Bre-B: por qué todavía no

Bre-B está vivo desde octubre de 2025: 218+ participantes, liquidación en menos de 20 segundos, 24/7, tope de **$12.110.000 COP por transacción en 2026**, gratis para personas naturales hasta 2028, y ~3.7 millones de cuentas de personas jurídicas registradas.

Es el riel de pagos más moderno del país. Y **no sirve para delegación hoy**:

- **El recaudo exige que el pagador apruebe en la app de su propio banco.** No hay mandato, no hay credential-on-file.
- **No existe request-to-pay ni débito recurrente.** ACI Worldwide, que opera la infraestructura, confirma que la capacidad técnica está —nómina, solicitud de pago para comercios, dispersión de subsidios— pero depende de *"consenso de la industria y disponibilidad de los nodos participantes"*. Es decisión regulatoria y de gobernanza, no desarrollo pendiente.
- **Es irreversible.** Una dispersión sale y llega; no hay contracargo. Tu `payouts.py` ya lo dice mejor de lo que yo podría.

**Dónde sí encaja en tu PoC:** en la pata de *salida*, no de entrada. La resolución de llave antes de dispersar —tu `cmd_resolve`— es el único punto donde se puede contrastar a quién crees que le pagas contra a quién le vas a pagar. En comercio agéntico, donde el destinatario lo eligió un modelo y no una persona, ese contraste es el control de fraude más importante que existe en el flujo. Vale la pena que la iteración 1 lo incluya aunque el cobro no vaya por Bre-B.

Registra el riesgo: **Bre-B es el riel que un atacante usaría para sacar el dinero**, precisamente porque no tiene reversa. Un agente comprometido que puede cobrar por Wompi *y* dispersar por Bre-B cierra el ciclo completo sin dejar un punto de disputa.

---

## 6. La pieza que ningún riel colombiano te da: el mandato

Este es el hallazgo central.

Wompi te da un `payment_source_id`. Ese identificador es:

- **Sin tope.** Puedes cobrar $1.000 o el máximo del comercio.
- **Sin vencimiento.** No expira solo.
- **Sin ligadura** a un monto, un producto, un comercio destino ni una intención.
- **Sin distinción** entre un cobro que el titular pidió y uno que un agente inventó.
- **Revocable solo por anulación total** (`void`) de la fuente.

Comparado con lo que los estándares de comercio agéntico ya definieron:

**AP2 (Google, con PayPal y otros)** — tres credenciales verificables firmadas criptográficamente:

- **Intent Mandate** — autoriza al agente a comprar bajo restricciones, con el humano ausente
- **Cart Mandate** — firma del usuario sobre un carrito concreto, con el humano presente; genera prueba de no repudio
- **Payment Mandate** — se comparte con la red y el emisor, señalando que hubo un agente y si había humano presente

Hoy AP2 soporta métodos *pull* (tarjetas); los *push* (Pix, UPI, transferencias en tiempo real) están en hoja de ruta.

**ACP (OpenAI, Stripe y Meta)**, spec `2026-04-17` — checkout agéntico, *delegate payment* con tokens de pago compartidos, *delegate authentication* con OAuth 2.0, y webhooks de órdenes.

Ninguno de los dos está implementado sobre rieles colombianos. **La capa de mandato es tuya.** Y como Colombia tiene la Ley 527 de 1999 y el Decreto 2364 de 2012 —que dan validez probatoria a la firma electrónica y digital— un mandato firmado criptográficamente por el titular **es oponible en Colombia**. No es un adorno técnico: es la evidencia con la que se resuelve una disputa.

### El diseño mínimo

```
Mandato firmado por el titular
  ├── payment_source_id      a qué fuente aplica
  ├── monto_maximo           tope por transacción
  ├── monto_acumulado_max    tope total de vida del mandato
  ├── comercios_permitidos   lista blanca de destinos
  ├── categoria              restricción de rubro
  ├── vigencia_desde/hasta   ventana temporal
  ├── humano_presente        true = cart mandate, false = intent mandate
  ├── nonce                  anti-replay
  └── firma                  Ed25519 sobre el canónico
```

El ejecutor **jamás** llama a `POST /v1/transactions` sin verificar el mandato primero. Wompi no lo sabe y no lo va a validar: el control vive enteramente en tu lado. Eso también es un hallazgo —la superficie de fraude es exactamente igual al tamaño de lo que tú decidas no verificar.

---

## 7. Arquitectura propuesta de la iteración 1

Diagrama completo en `arquitectura-iteracion-1.mermaid`. En resumen:

**Actores:** titular (tú, con tarjeta o Nequi real) · agente · bóveda de mandatos · ejecutor de pagos · Wompi producción · comercio de prueba.

**Fase A — Enrolamiento (humano presente, una sola vez)**

1. El titular tokeniza su tarjeta o su Nequi.
2. Aprueba el challenge: 3DS en iframe, o push en la app Nequi.
3. Se crea la fuente de pago. Estado `AVAILABLE`.
4. **El titular firma un mandato** que ata esa fuente a límites concretos. Aquí es donde se cierra el hueco que Wompi deja abierto.
5. Mandato y fuente quedan en la bóveda. La llave privada del titular nunca sale de su dispositivo.

**Fase B — Compra agéntica (humano ausente)**

6. El agente arma un carrito.
7. Pide autorización al ejecutor presentando el mandato y el carrito.
8. **El ejecutor verifica**: firma válida, vigencia, monto ≤ tope, acumulado + monto ≤ tope de vida, comercio en lista blanca, nonce no usado.
9. Si pasa: `POST /v1/transactions` con `payment_source_id`. Si falla: rechazo con motivo, y queda anotado.
10. Se registra el desenlace ligado al mandato, al carrito y a la decisión del agente.

**Fase C — Lo que hace que esto sea una PoC de fraude, no una demo de pagos**

Esta fase es la razón de ser del proyecto. Los escenarios a ejercer:

- Cobro **sin mandato** — mide qué tan lejos llega un atacante que solo robó el `payment_source_id`
- Cobro **excediendo el tope** — verifica que el control es tuyo y solo tuyo
- Cobro a un **comercio fuera de la lista blanca** — el caso del agente manipulado por inyección de prompt
- **Replay** de un mandato ya consumido
- Mandato **expirado**
- **Carrito alterado** después de la firma — el ataque más realista contra un agente
- **Escalada**: muchos cobros pequeños bajo el tope individual, sumando por encima del acumulado
- **Ciclo completo**: cobro por Wompi y dispersión inmediata por Bre-B sin resolución de llave

Cada uno debe fallar de forma observable y quedar en el ledger. Un escenario que "no pasa nada" es un escenario que no probaste.

---

## 8. Plan de habilitación

### Semana 1 — En paralelo, todo el mismo día

| # | Acción | Depende de | Tiempo |
|---|---|---|---|
| 1 | Registro en `registro.wompi.co` con RUT + cuenta | — | 1 día + validación |
| 2 | Solicitar a soporte Wompi **activación de 3DS en sandbox** | — | días |
| 3 | Solicitar a soporte Wompi **activación de 3DS en producción** | (1) | días |
| 4 | Preguntar por escrito: ¿fuentes de pago **Nequi** en producción? | (1) | días |
| 5 | Contactar ejecutivo Wompi para **modelo Gateway + Nequi** | (1) | semanas |
| 6 | Construir la capa de mandato contra sandbox | — | ya puedes |

El punto 6 no depende de nadie. Empieza por ahí.

### Semana 2–3

7. Migrar `lab.py` a producción con llaves `pub_prod_` / `prv_prod_`, **manteniendo el guardarraíl invertido**: hoy tu código se niega a arrancar sin `pub_test_`. Cámbialo por un flag explícito, no por borrar la validación.
8. Primer cobro real: **$1.000–$5.000 COP** contra tu propia tarjeta.
9. Crear la primera fuente de pago real con 3DS. Firmar el primer mandato.
10. Primer cobro agéntico real contra mandato.

### Semana 4+

11. Batería de escenarios de fraude de la sección 7, fase C.
12. Si Nequi se habilitó: repetir todo con fuente Nequi y **documentar la diferencia** — tarjeta tiene 3DS/3RI y contracargo; Nequi no tiene ninguno de los dos.

### Advertencias operativas

- **El dinero se demora en volver.** Persona natural nueva: hasta 30 días el primer desembolso, 5 días hábiles después. Presupuesta el capital de prueba como inmovilizado.
- **Montos mínimos.** No hay razón para probar con $50.000 lo que se prueba igual con $1.000.
- **Comercio de prueba propio.** Cobrarte a ti mismo para validar es práctica normal, pero mantenlo a montos simbólicos y con actividad económica declarada correcta en el RUT. El reglamento de Wompi es estricto con actividades prohibidas y restringidas, y una discrepancia entre lo declarado y lo transaccionado es causal de bloqueo.
- **Separa las llaves.** `prv_prod_` en un gestor de secretos, nunca en el `.env` del repo. Hoy tu `.env` está en la raíz junto al `.gitignore`; verifica que efectivamente lo excluya antes del primer commit con llaves productivas.

---

## 9. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Fuentes de pago Nequi no habilitadas en producción | Alto — cambia el riel de la PoC | Preguntar por escrito en semana 1. Plan B: tarjeta con 3DS |
| Modelo Gateway + Nequi tarda meses | Medio | No bloquear la iteración 1 con ello. Tarjeta primero |
| 3DS no activado en producción | Alto — sin él no hay fuente de tarjeta | Solicitud independiente a soporte, semana 1 |
| Retención de 30 días del primer desembolso | Bajo | Montos simbólicos |
| Bloqueo de cuenta por patrón transaccional atípico | Alto | Declarar el propósito de prueba al ejecutivo. Montos bajos y regulares |
| Reglamento exige 2FA que un agente no puede hacer | Medio — brecha real | Documentar como hallazgo. Implementar 2FA en el enrolamiento, no en el cobro |
| Decreto 1297: prohibición de solicitar claves | Alto si se automatiza el Botón | No automatizar interfaces del banco. Punto |
| Contracargo con responsabilidad del comercio | Medio | 3DS/3RI en tarjeta traslada parte al emisor |

---

## 10. Lo que no pude confirmar

Honestidad sobre los límites de esta investigación:

1. **`developer.bancolombia.com` no fue accesible** por su `robots.txt`. El catálogo de la sección 2 viene del Centro de Ayuda de APIs Bancolombia y de resultados de búsqueda, no de la página de productos. Puede haber APIs no listadas ahí, y en particular **no puedo descartar que exista un producto de débito recurrente no publicado**. Vale preguntarlo directamente.
2. **`conecta.nequi.com.co` tampoco fue accesible.** Los detalles de la API de Suscripciones vienen de `nequi.com.co/negocios/pagos-recurrentes` y de integradores (Cobre, Treli). Los endpoints exactos y los límites de monto hay que sacarlos de la documentación oficial con credenciales.
3. **Contradicción documental en Wompi** sobre tokenización Nequi (sección 4.1). Sin resolver.
4. **Sin límites de monto publicados** para la API de suscripciones de Nequi.
5. La `RESOLVE_PATH` de Bre-B en tu `payouts.py` sigue siendo conjetura; la guía de integración de Wompi devuelve 403 a lectura automatizada.

---

## 11. Contexto: no vas tarde

Dos señales de abril y de este año:

- **Visa Agentic Ready** se lanzó en América Latina y el Caribe el 29 de abril de 2026, y **Bancolombia es participante activo** (junto a Banco de Bogotá, Davivienda y Banco Popular de Colombia como partners que avanzan capacidades). El programa se apoya en tokenización —ya el 50% del e-commerce en LAC está tokenizado— autenticación biométrica y una capa de confianza que valida enrolamiento, autenticación y autorización.
- **Pomelo y Mastercard procesaron el primer pago agéntico dentro de ChatGPT en América Latina, y ocurrió en Colombia**, con Mastercard Agent Pay y tokenización propia. Iniciado dentro de un LLM, confirmado por el usuario, autorizado en tiempo real.

Es decir: el país ya tiene el primer pago agéntico ejecutado, y el banco cuyos rieles estás investigando ya está en el programa de la red. Tu PoC no está adelantada al mercado — está justo donde el mercado se está definiendo, y la pregunta de fraude que estás haciendo es la que todavía nadie respondió.

---

## Fuentes

**Bancolombia**

- [Centro de Ayuda APIs Bancolombia — productos](https://soportedevs.bancolombia.com/hc/es-419/p/category_portal_page?template_topic=productos)
- [¿Cómo solicitar el paso a producción con los productos de APIs?](https://soportedevs.bancolombia.com/hc/es-419/articles/22036835683860--C%C3%B3mo-solicitar-el-paso-a-producci%C3%B3n-con-los-productos-de-APIs)
- [¿Cómo usar el Botón Bancolombia con integración por APIs?](https://www.bancolombia.com/centro-de-ayuda/preguntas-frecuentes/usar-boton-bancolombia-apis)
- [Contrato para la habilitación y prestación de servicios de APIs](https://s3.amazonaws.com/nequi-dev-portal-api-doc/Contrato_APIS.pdf)
- [SDK Botón Bancolombia (Placetopay)](https://github.com/placetopay-org/bancolombia-sdk)
- [Portal de desarrolladores Bancolombia](https://developer.bancolombia.com/es/product-list)

**Nequi**

- [Pagos recurrentes con Nequi — API de suscripciones](https://www.nequi.com.co/negocios/pagos-recurrentes)
- [API suscripciones | Nequi Conecta](https://conecta.nequi.com.co/apis/pago-con-d%C3%A9bito-autom%C3%A1tico)
- [Documentación APIs | Nequi Conecta](https://docs.conecta.nequi.com.co/)
- [Débito automático con Nequi para empresas (Cobre)](https://www.cobre.com/local-payments/debito-a-cuenta)

**Wompi**

- [Fuentes de pago & Tokenización](https://docs.wompi.co/en/docs/colombia/fuentes-de-pago/)
- [Métodos de pago](https://docs.wompi.co/en/docs/colombia/metodos-de-pago/)
- [Fuentes de pago seguras con 3D Secure](https://docs.wompi.co/en/docs/colombia/fuentes-de-pago-3ds-sandbox/)
- [Reglamento de Comercios Wompi Colombia (V3-2025)](https://wompi.com/assets/downloadble/reglamento-Comercios-Colombia.pdf)
- [¿Cómo es el proceso de vinculación a la pasarela de pago?](https://soporte.wompi.co/hc/es-419/articles/360020955173--C%C3%B3mo-es-el-proceso-de-vinculaci%C3%B3n-a-la-pasarela-de-pago)
- [¿Cómo activar Nequi bajo el modelo Gateway?](https://soporte.wompi.co/hc/es-419/articles/1500007698501--C%C3%B3mo-activar-Nequi-como-medio-de-pago-en-Wompi-bajo-el-modelo-Gateway)

**Bre-B y regulación**

- [Conozca Bre-B | Banco de la República](https://www.banrep.gov.co/es/bre-b/que-es)
- [Documento técnico Bre-B, febrero 2026](https://www.banrep.gov.co/en/publications-research/working-papers/paper-bre-b-february-2026)
- [Bre-B para empresas en Colombia: guía 2026](https://www.mouvlatam.com/recursos/bre-b-empresas)
- [Infraestructura de Bre-B lista para ampliar servicios](https://www.valoraanalitik.com/infraestructura-tecnologica-de-bre-b-esta-lista-para-ampliar-los-servicios-de-pagos-y-transferencias/)
- [Bre-B pay-in vía API (Cobre)](https://www.cobre.com/breb/payin)
- [Nueva regulación de pagos y Open Finance en Colombia (Belvo)](https://belvo.com/es/blog/como-profundiza-nueva-regulacion-pagos-open-finance-colombia/)
- [Decreto 1297 de 2022](https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=190426)
- [Ley 527 de 1999](https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=4276)
- [Decreto 2364 de 2012 — firma electrónica](https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=50583)

**Comercio agéntico**

- [Agent Payments Protocol (AP2)](https://ap2-protocol.net/en/)
- [Announcing Agent Payments Protocol (AP2) — Google Cloud](https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol)
- [Agentic Commerce Protocol | Stripe](https://docs.stripe.com/agentic-commerce/acp)
- [ACP — repositorio de la especificación](https://github.com/agentic-commerce-protocol/agentic-commerce-protocol)
- [Visa lanza Visa Agentic Ready para LAC](https://www.visa.com.mx/acerca-de-visa/sala-de-noticias/notas-de-prensa/visa-agentic-ready-comercio-inteligencia-artificial-lac.html)
- [Pomelo y Mastercard procesan el primer pago agéntico en ChatGPT](https://impactotic.co/inteligencia-artificial/pomelo-y-mastercard-procesan-el-primer-pago-agentico-en-chatgpt/)
