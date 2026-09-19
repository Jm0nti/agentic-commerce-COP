# Cómo funciona una compra

Una compra con el asistente pasa siempre por las mismas etapas, y en dos de
ellas decide la persona, nunca el asistente: autorizar la compra y, a veces,
confirmar el cobro. La idea que resume todo el sistema es esta: **el
asistente propone, la persona firma, la bóveda ejecuta**.

## Paso a paso

- **Conversación.** La persona le cuenta al asistente qué busca. El asistente
  consulta los comercios y productos disponibles; no inventa productos ni
  precios, todo sale del catálogo.
- **Carrito y propuesta.** Cuando la persona quiere comprar, el asistente arma
  un carrito con un solo comercio y, a partir de él, una propuesta de compra.
  La propuesta todavía no autoriza nada: es un pedido de permiso.
- **Firma de la persona.** La app le muestra a la persona la propuesta: el
  comercio, los productos y el monto exacto. Si está de acuerdo, la firma. Esa
  firma crea un mandato: un permiso firmado digitalmente, atado a ese carrito,
  con un monto máximo, un número de usos y una vigencia corta.
- **Pago.** Con el mandato firmado, el asistente puede pedir el cobro. Antes de
  cobrar, la bóveda revisa el mandato completo: que la firma sea válida, que no
  haya vencido, que el comercio y el monto correspondan, y que el carrito no
  haya cambiado desde que se firmó.
- **Confirmación, si hace falta.** Si el cobro cabe en el mandato pero tiene
  algo inusual, se pausa y la app le pregunta a la persona si lo confirma.
- **Resultado.** El cobro queda aprobado, rechazado o pendiente. Si queda
  pendiente, el resultado final llega después, sin que la persona tenga que
  hacer nada.

## Por qué la persona tiene que firmar

El asistente no tiene forma de firmar: la llave con la que se firma es de la
persona y el asistente no tiene acceso a ella. Así, aunque el asistente se
equivoque o alguien intente engañarlo, no puede autorizar una compra que la
persona no vio y aceptó.

## Por qué la propuesta es por un carrito concreto

El mandato queda atado al carrito que la persona vio al firmar. Si el carrito
cambia después de la firma (otro producto, otra cantidad), el cobro se
bloquea. Para comprar algo distinto hace falta una propuesta nueva y una firma
nueva.

## Dónde se hace cada cosa

- En la app web, la firma y la confirmación aparecen como ventanas emergentes
  dentro del mismo chat.
- Desde la terminal, la persona firma y confirma con los comandos que el
  asistente le indica, en su propia terminal.

En los dos casos, quien firma y quien confirma es siempre la persona.
