# Guion de solicitudes para desbloquear producción

Qué pedir, a quién, y con qué justificación. Ordenado por lo que bloquea antes.

**Figura elegida:** persona natural con RUT propio. Eso fija el tope de Wompi en
$2.500.000 COP por transacción y hace el registro autoservicio.

---

## Solicitud 1 — Wompi: activación de 3DS

**Prioridad:** bloqueante. Sin esto no hay fuente de pago con tarjeta.
**Canal:** soporte Wompi (`soporte.wompi.co`), desde el correo del comercio.
**Ojo:** son **dos solicitudes separadas**, una para sandbox y otra para producción.

> Asunto: Solicitud de activación de 3D Secure para fuentes de pago — sandbox y producción
>
> Buen día,
>
> Soy comercio registrado en Wompi (persona natural). Estoy integrando fuentes de
> pago con tarjeta y la documentación indica que 3D Secure es obligatorio para
> crearlas, y que la activación debe solicitarse por este canal de forma
> independiente para cada ambiente.
>
> Solicito activación de 3DS para fuentes de pago en:
>
> 1. Ambiente **sandbox**
> 2. Ambiente **producción**
>
> Datos del comercio: [nombre] · NIT/CC [x] · llave pública `pub_test_...`
>
> Adicionalmente, quisiera confirmar dos puntos:
>
> - ¿Los cobros posteriores contra una fuente creada con 3DS quedan efectivamente
>   amparados bajo 3RI, y eso desplaza la responsabilidad de contracargo al emisor?
> - ¿Hay algún requisito adicional de habilitación para el Servicio de Pago Rápido
>   más allá de 3DS?
>
> Gracias,

---

## Solicitud 2 — Wompi: ¿fuentes de pago Nequi en producción?

**Prioridad:** alta. Define si el riel principal de la PoC es tarjeta o Nequi.
**Canal:** soporte Wompi. **Pídelo por escrito**: la documentación se contradice.

La contradicción concreta: la página *Métodos de pago* marca NEQUI sin
tokenización, mientras que *Fuentes de pago & Tokenización* documenta
`/v1/tokens/nequi` explícitamente. Y en sandbox el endpoint responde. Necesitas
saber qué pasa en producción **antes** de comprometer el diseño.

> Asunto: Disponibilidad de fuentes de pago Nequi en producción
>
> Buen día,
>
> Encuentro una inconsistencia en la documentación que necesito aclarar antes de
> avanzar con la integración.
>
> La guía de *Fuentes de pago & Tokenización* documenta el endpoint
> `POST /v1/tokens/nequi` y describe el flujo de aprobación de la suscripción
> desde la app Nequi. En sandbox ya lo integré y funciona: obtengo el token,
> el estado pasa a APPROVED y puedo crear la fuente de pago.
>
> Sin embargo, la tabla de *Métodos de pago* marca NEQUI sin soporte de
> tokenización ni fuentes de pago.
>
> ¿Me confirman por escrito si las fuentes de pago Nequi están disponibles en
> **producción**, y bajo qué condiciones? En particular:
>
> - ¿Requiere el modelo Gateway, o funciona con el registro estándar?
> - ¿Hay topes de monto o de frecuencia distintos a los de tarjeta?
> - ¿Existe algún equivalente a 3DS/3RI para Nequi, o el riesgo de la transacción
>   no presente lo asume íntegramente el comercio?
>
> Gracias,

La respuesta a la última pregunta es material para el informe de la PoC, tanto si
es sí como si es no.

---

## Solicitud 3 — Wompi: modelo Gateway + activación de Nequi

**Prioridad:** media. Semanas de trámite, así que **empieza el día uno** aunque no
bloquee la iteración 1.
**Canal:** ejecutivo de cuenta Wompi. No es autoservicio.

Secuencia documentada:

1. Contactar al ejecutivo de cuenta para registrarte bajo **modelo Gateway**
2. Con eso listo, diligenciar el formulario en `negocios.nequi.co/registro/wompi`
3. Esperar confirmación de Nequi
4. Wompi notifica el estado de activación al correo de registro

> Buen día,
>
> Soy comercio registrado en Wompi como persona natural y quiero habilitar Nequi
> como medio de pago bajo el modelo Gateway.
>
> Contexto: estoy desarrollando una prueba de concepto sobre pagos iniciados por
> agentes de IA en rieles colombianos, con foco en los controles de fraude que el
> escenario exige. El volumen es de pruebas —montos entre $1.000 y $20.000 COP,
> baja frecuencia— y el interés es técnico, no comercial de alto volumen.
>
> Lo declaro por adelantado para que el patrón transaccional no se lea como
> atípico. Si el caso de uso requiere algún tratamiento particular, agradezco que
> me lo indiquen.
>
> ¿Me pueden orientar sobre el proceso de registro bajo modelo Gateway y los
> tiempos estimados?
>
> Gracias,

**Declarar el propósito de prueba por adelantado no es opcional.** El reglamento
de comercios de Wompi permite bloquear cuentas por patrones transaccionales
atípicos, y una serie de cobros pequeños y repetitivos contra la misma fuente es
exactamente eso si nadie lo explicó antes.

---

## Solicitud 4 — Bancolombia: sandbox del API Market

**Prioridad:** baja para la iteración 1, alta para cerrar el informe.
**Canal:** formulario de soporte en `soportedevs.bancolombia.com`.

El objetivo aquí **no** es integrar. Es cerrar la pregunta que la investigación
pública dejó abierta: si existe algún producto de débito recurrente o mandato
delegado que no esté publicado en el catálogo.

> Buen día,
>
> Solicito credenciales de sandbox (Client-Id y Client-Secret) para el API Market.
>
> Contexto: estoy evaluando qué capacidades de los rieles de pago colombianos
> soportan transacciones iniciadas por agentes de software en nombre de un
> titular, en línea con estándares como AP2 y ACP.
>
> Del catálogo público entiendo que el Botón Bancolombia opera por redirección
> con clave dinámica en cada transacción, lo cual exige presencia interactiva del
> titular. Antes de descartar la integración directa quisiera confirmar:
>
> 1. ¿Existe algún producto de API —publicado o en piloto— que permita **débito
>    recurrente autorizado una vez** contra una cuenta Bancolombia, sin presencia
>    del titular en cada cobro? (El equivalente a `BANCOLOMBIA_TRANSFER` como
>    fuente de pago en Wompi, pero por API directa.)
> 2. ¿Hay hoja de ruta para exponer capacidades de **mandato de pago delegado** o
>    de iniciación de pago en el marco de finanzas abiertas del Decreto 1297?
> 3. Bancolombia figura como participante de **Visa Agentic Ready** en LAC.
>    ¿Hay un canal para desarrolladores interesados en probar contra esas
>    capacidades?
>
> Gracias,

La pregunta 3 es la que puede abrir una puerta que el catálogo público no muestra.

---

## Solicitud 5 — Nequi Conecta (opcional, ruta larga)

**Prioridad:** baja para esta iteración. Actívala solo si Wompi cierra la puerta
de las fuentes Nequi.
**Canal:** Nequi para Negocios.

Qué pedir: acceso a la **API de Suscripciones** (pago con débito automático),
que es funcionalmente el mejor mandato de pago delegado del país.

Preguntas que la documentación pública no responde y hay que resolver:

- Límite de monto por cobro y acumulado de una suscripción
- Si el comercio puede consultar el estado de una suscripción o solo recibir el
  webhook de éxito
- Qué pasa con cobros posteriores cuando el usuario cancela desde la app: ¿error
  específico o rechazo genérico?
- Si hay algún campo para declarar que la transacción fue **iniciada por un
  agente** (equivalente al Payment Mandate de AP2). Casi seguro que no — y esa
  ausencia es un hallazgo del informe.
- Migración a **OAuth 2.0**: la documentación anuncia el cambio desde el 1 de
  octubre. Confirmar que la integración nueva arranca directo en OAuth 2.0 y no
  en JWS/AWS SigV4.

---

## Checklist de seguimiento

| # | Solicitud | Canal | Bloquea | Estado |
|---|---|---|---|---|
| 1 | 3DS sandbox | Soporte Wompi | Fuente de pago tarjeta | ☐ |
| 1b | 3DS producción | Soporte Wompi | Cobro real | ☐ |
| 2 | Fuentes Nequi en producción | Soporte Wompi | Elección de riel | ☐ |
| 3 | Modelo Gateway + Nequi | Ejecutivo Wompi | Riel Nequi | ☐ |
| 4 | Sandbox API Market | Soporte Bancolombia | Cierre del informe | ☐ |
| 5 | Nequi Conecta | Nequi para Negocios | Solo si falla (2) | ☐ |

Guarda las respuestas escritas. Para el informe final de la PoC, "Wompi confirmó
por correo que no existe equivalente a 3RI en Nequi" vale mucho más que "no
encontré documentación al respecto".
