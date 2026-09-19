# El mandato y sus controles

Un mandato es el permiso firmado que la persona le da al sistema para cobrar
una compra concreta. Es lo único que la bóveda acepta como autorización:
ningún cobro sale sin un mandato firmado que lo cubra.

## Qué dice un mandato

- **Quién lo firma**: la persona titular, con su propia llave de firma.
- **A qué comercio** se le puede pagar.
- **Cuánto** se puede cobrar por vez y en total.
- **Cuántas veces** se puede usar.
- **Hasta cuándo** vale.
- **Qué carrito** cubre, cuando el mandato nace de una propuesta del asistente.

Los valores exactos de cada mandato (su monto máximo, su tope total, sus usos y
su vencimiento) los fija la propuesta que la persona firmó. Esas cifras se
consultan en el mandato real, en la app; no se deducen de una explicación
general.

## Los controles que se revisan antes de cobrar

Cada vez que se intenta un cobro, la bóveda vuelve a revisar el mandato
completo. Si alguno de estos controles falla, el cobro se bloquea y queda
registrado el motivo:

- **Firma válida.** El mandato tiene que estar firmado y la firma tiene que
  corresponder exactamente a su contenido. Si alguien cambia cualquier dato
  después de firmar, la firma deja de validar.
- **Mandato correcto.** El cobro tiene que citar ese mandato y no otro.
- **Vigencia.** Un mandato vencido no autoriza nada; hace falta uno nuevo.
- **Comercio autorizado.** Solo se le puede pagar al comercio que dice el
  mandato.
- **Monto por cobro.** Un cobro no puede superar el monto máximo del mandato.
- **Tope total.** Lo cobrado con ese mandato, sumado, no puede superar su tope
  total.
- **Número de usos.** Un mandato de un solo uso no se puede usar dos veces.
- **Categoría.** Si el mandato limita las categorías de compra, el cobro tiene
  que ser de una de ellas.
- **Carrito sin cambios.** Si el mandato está atado a un carrito, el carrito
  que se cobra tiene que ser idéntico al que se firmó.

## Los topes del sistema

Además del mandato, el sistema tiene topes propios por transacción y por día.
Esos topes no dependen del mandato ni del asistente y no se pueden cambiar
desde la app: protegen a la persona incluso si un mandato se firmara con un
monto demasiado alto.

## Qué no controla el mandato

Un mandato no puede saber si el producto es el que la persona realmente
quería: si el asistente arma un carrito equivocado y la persona lo firma sin
revisarlo, el mandato lo autoriza. Por eso la app muestra el detalle del
carrito antes de firmar, y por eso algunos cobros piden una confirmación
adicional.
