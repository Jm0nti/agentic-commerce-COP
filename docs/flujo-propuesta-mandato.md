# `PropuestaDeMandato`, paso a paso

La pregunta era por qué existe un tipo aparte en vez de dejar que el agente
construya un `Mandato` y ya. La respuesta corta: **porque si el agente puede
construir un `Mandato`, puede construir uno que le convenga.**

La larga es este recorrido.

---

## El escenario

Juan le pide al agente unos audífonos. El agente encuentra dos productos en
`TiendaX` (un comercio simulado) y arma un carrito de **16.500 COP**.

---

## Paso 1 — El agente arma el carrito

Llama a `armar_carrito`, una de sus seis herramientas.

```json
{
  "carrito_id": "car_9f2a",
  "comercio_id": "com_tiendax",
  "turno_id": "trn_004",
  "items": [
    {"producto_id": "prd_audif", "nombre": "Audifonos BT", "cantidad": 1,
     "precio_unitario": {"centavos": 1200000, "moneda": "COP"}},
    {"producto_id": "prd_cable", "nombre": "Cable USB-C", "cantidad": 1,
     "precio_unitario": {"centavos": 450000, "moneda": "COP"}}
  ],
  "total": {"centavos": 1650000, "moneda": "COP"},
  "hash_canonico": "sha256:4b1e...9c07"
}
```

El `hash_canonico` cubre los **items**, no sólo el total. Se ordena por
`producto_id`, así que dos carritos con las mismas cosas en distinto orden dan el
mismo hash — el orden en que el agente las agregó no es parte del acuerdo.

## Paso 2 — El agente propone, no autoriza

La misma herramienta devuelve una `PropuestaDeMandato`:

```json
{
  "propuesta_id": "prp_c41d",
  "carrito_id": "car_9f2a",
  "comercio_id": "com_tiendax",
  "monto_max": {"centavos": 1650000, "moneda": "COP"},
  "usos_max": 1,
  "vigencia_minutos": 30,
  "justificacion": "Audifonos BT y cable, TiendaX"
}
```

Mira lo que **no** tiene:

| Ausente | Por qué |
|---|---|
| `firma` | El agente no tiene la llave |
| `llave_publica` | No es suyo el mandato |
| `medio` | Nunca ve un `payment_source_id` |
| `mandato_id` | No existe todavía; existirá cuando alguien firme |
| `titular_id` | Lo pone quien firma, no quien pide |

Y no es que estén vacíos: **no existen en el tipo.** `PropuestaDeMandato` es un
dataclass distinto de `Mandato`. Ninguna función que espere un `Mandato` acepta
una propuesta — falla al construir el objeto, no en una validación que alguien
pudo olvidar escribir.

Esa es la diferencia entre una regla y una propiedad del sistema.

## Paso 3 — El humano ve lo que va a autorizar

La app le muestra a Juan la propuesta traducida a español:

```
El agente quiere comprar en TiendaX
  Audifonos BT          12.000
  Cable USB-C            4.500
  ─────────────────────────────
  Total                 16.500 COP

Vas a autorizar:
  hasta 16.500 COP · 1 uso · 30 minutos · sólo TiendaX
  atado a ESTE carrito

  [ Firmar ]   [ Cancelar ]
```

Este es el punto entero del diseño. Juan no está aprobando "que el agente
compre": está aprobando **estos ítems, en este comercio, por este monto, por
esta ventana**.

## Paso 4 — La firma

Juan aprieta Firmar. La llave privada (en su dispositivo, o tras un PIN) firma
la carga canónica y nace el `Mandato`:

```json
{
  "version": 2,
  "mandato_id": "mnd_7e30a1b2",
  "titular_id": "tit_juan",
  "medio": {"proveedor": "wompi", "ambiente": "produccion",
            "id_externo": "22620436", "tipo": "NEQUI"},
  "comercio_id": "com_tiendax",
  "monto_max": {"centavos": 1650000, "moneda": "COP"},
  "tope_total": {"centavos": 1650000, "moneda": "COP"},
  "usos_max": 1,
  "expira_en": "2026-08-19T21:35:00+00:00",
  "carrito_hash": "sha256:4b1e...9c07",
  "llave_publica": "07c6a5...4ff2",
  "firma": "9a3f...e1"
}
```

El `medio` lo pone la bóveda al firmar, no la propuesta. El agente nunca supo
que existe la fuente `22620436`.

## Paso 5 — El agente recibe un identificador y nada más

```json
{"mandato_id": "mnd_7e30a1b2", "estado": "firmado"}
```

Con eso puede llamar `pagar(mandato_id, carrito_id)`. Es todo lo que tiene.

## Paso 6 — La bóveda ejecuta

```
1. TopesDuros        16.500 <= 20.000        OK  (nunca se apaga)
2. Reserva atomica   16.500 contra el cupo   OK
3. Dictamen          firma, vigencia, comercio, monto, usos, carrito
                                              PERMITIR
4. Pasarela.cobrar   -> PENDIENTE
```

El paso 3 recalcula el hash del carrito que el agente presentó y lo compara con
el que quedó dentro de la firma.

---

## Qué pasa cuando el agente se sale del molde

### El agente presenta otro carrito

Lo convencieron por inyección de prompt. Firmado el carrito de audífonos,
presenta uno con una consola — mismo total, mismo comercio:

```
3. Dictamen  -> BLOQUEAR
   carrito_alterado: el carrito cambio despues de la firma
```

Sin `carrito_hash` esto pasaría limpio: mismo monto, mismo destino, nada que el
mandato pudiera objetar. Es el ataque que el Cart Mandate de AP2 existe para
atajar, y hay una prueba dedicada
(`test_cambiar_un_item_cambia_el_hash_aunque_el_total_no`).

### El agente pide más plata

Propone 16.500, Juan firma 16.500, y al pagar el agente pide 45.000:

```
1. TopesDuros -> 45.000 > 20.000. Detenido antes de mirar el mandato.
```

El tope duro atrapa este caso primero. Si el monto fuera 18.000 —bajo el tope
duro pero sobre el mandato— lo atraparía el dictamen con
`monto_sobre_mandato`.

### El agente pide algo que cabe pero huele raro

Propone gastar exactamente todo lo que queda del mandato, en su último uso:

```
3. Dictamen -> CONFIRMAR
   senales: agota el mandato de una sola vez
            es el ultimo uso del mandato
   violaciones: []
```

**No hay violación.** Cabe. Pero la respuesta correcta no es sí ni no: es
preguntarle al humano. Este desenlace no existe en la v1 y es el más
interesante para la app, porque es donde el sistema admite que hay cosas que la
criptografía no decide.

### El agente reutiliza un mandato

```
3. Dictamen -> BLOQUEAR
   usos_agotados: el mandato permite 1 uso y lleva 1
```

---

## El resumen en una tabla

| | `PropuestaDeMandato` | `Mandato` |
|---|---|---|
| La crea | El agente | El titular |
| Firma | No existe | ed25519 sobre la carga canónica |
| Medio de pago | No existe | `MedioDePagoRef`, puesto al firmar |
| Sirve para cobrar | No | Sí |
| Si se altera | Nada — no hay nada que romper | La firma deja de validar |

> El agente propone. El humano firma. La bóveda ejecuta.

`PropuestaDeMandato` es la primera frase de esa oración, hecha tipo.
