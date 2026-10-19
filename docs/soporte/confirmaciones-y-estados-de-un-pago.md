# Confirmaciones y estados de un pago

## Las tres decisiones posibles

Antes de cobrar, el motor de pagos revisa el mandato y llega a una de tres decisiones:

- **Permitir.** El cobro cabe en el mandato y no tiene nada inusual. Se cobra.
- **Confirmar.** El cobro cabe en el mandato, pero algo merece una mirada
  humana. El cobro se pausa y la app le pregunta a la persona si lo confirma o
  lo rechaza. El asistente nunca puede confirmar por la persona.
- **Bloquear.** El cobro no cabe en el mandato. No se cobra, y queda escrito
  por qué.

## Por qué a veces se pide confirmación

Pedir confirmación no significa que algo esté mal. Pasa cuando el cobro:

- usa todo lo que quedaba disponible del mandato de una sola vez,
- llega casi al monto máximo por cobro del mandato, o
- es el último uso que le queda al mandato.

Como las propuestas del asistente se arman justas para el carrito (el monto
máximo igual al total y un solo uso), es normal que la mayoría de las compras
pidan esta confirmación. Es la consecuencia esperada de firmar un permiso
angosto, no un error.

## Los estados de un pago

- **Esperando confirmación.** El cobro está pausado hasta que la persona lo
  confirme o lo rechace.
- **Pendiente.** El cobro se envió, pero el banco o la billetera todavía no
  dieron una respuesta final. Con Nequi es habitual: la respuesta llega unos
  momentos después.
- **Aprobado.** El cobro se hizo.
- **Rechazado.** El cobro no se hizo: lo rechazó la persona, lo bloqueó el
  mandato, o lo rechazó la entidad de pago.

## Qué pasa con un pago pendiente

La persona no tiene que hacer nada. Cuando la entidad de pago da la respuesta
final, el sistema la recibe y actualiza el estado. En la app web, el chat
avisa solo cuando el resultado llega. Si la persona pregunta por el estado, el
asistente vuelve a consultarlo en ese momento en lugar de repetir lo último que
sabía.

## Qué pasa si se rechaza una confirmación

El cobro no se hace y el mandato no se consume. Si la persona quiere comprar
de todos modos, puede pedirle al asistente una propuesta nueva.
