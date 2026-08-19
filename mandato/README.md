# `mandato/` — la capa que Wompi no trae

## Por qué existe

`wompi_lab/lab.py` ya demuestra el hallazgo central de la PoC. El comentario al
final de `cmd_source` lo dice sin adornos:

> *Desde aqui se puede cobrar sin el titular. No hay tope, ni vencimiento, ni
> ligadura a un monto o a un producto.*

Eso no es un defecto de Wompi: es el contrato del producto. Una fuente de pago
es una credencial almacenada, y las credenciales almacenadas no llevan
restricciones adheridas en ningún riel colombiano hoy — ni en Wompi, ni en la
API de suscripciones de Nequi, ni en Bre-B.

En comercio agéntico eso deja de ser aceptable. Quien dispara el cobro no es el
titular: es un modelo que puede ser manipulado, que puede alucinar un carrito, o
que puede estar corriendo con un `payment_source_id` robado. Este módulo es el
control que falta.

## Los dos archivos

| Archivo | Qué hace |
|---|---|
| `mandato.py` | Emite y verifica mandatos firmados con Ed25519 |
| `ejecutor.py` | Único camino permitido hacia `POST /v1/transactions` |

La separación importa. `mandato.py` es criptografía pura y no sabe que Wompi
existe; se puede portar a Nequi directo, a Bre-B o a lo que venga sin tocarlo.
`ejecutor.py` es el que aterriza el mandato sobre un riel concreto.

## Los ocho controles

`ejecutor.py` nunca llama a Wompi sin que los ocho pasen:

1. **firma** — Ed25519 sobre el canónico del cuerpo
2. **vigencia** — dentro de la ventana temporal
3. **tope_por_cobro** — monto individual
4. **tope_acumulado** — suma de vida del mandato
5. **comercio_permitido** — lista blanca
6. **max_transacciones** — conteo, si se definió
7. **nonce** — anti-replay
8. **carrito** — hash, solo para mandatos tipo `cart`

Ninguno lo valida Wompi. **La superficie de fraude de la PoC es exactamente del
tamaño de lo que este módulo decida no revisar.**

## Uso

```bash
# 1. Par de llaves del titular. Una sola vez.
python mandato/mandato.py llaves

# 2. Emitir un mandato contra la fuente que ya creaste con lab.py
python mandato/mandato.py emitir \
    --payment-source-id 363784 \
    --monto-max 20000 \
    --tope-vida 60000 \
    --comercio tienda-demo \
    --horas 12

# 3. Verificación en seco
python mandato/mandato.py verificar boveda/mnd-xxxx.json \
    --monto 15000 --comercio tienda-demo

# 4. Autorizar (simulado por defecto)
python mandato/ejecutor.py autorizar --mandato boveda/mnd-xxxx.json \
    -a 15000 --comercio tienda-demo

# 5. Cobrar de verdad en sandbox
python mandato/ejecutor.py autorizar --mandato boveda/mnd-xxxx.json \
    -a 15000 --comercio tienda-demo --cobrar

# 6. La batería de fraude
python mandato/ejecutor.py escenarios
```

## Dónde queda cada cosa

| Ruta | Qué | ¿Se versiona? |
|---|---|---|
| `boveda/secretos/titular_ed25519.key` | Llave privada del titular | No — ya en `.gitignore` |
| `boveda/secretos/titular_ed25519.pub` | Llave pública | No |
| `boveda/secretos/estado.json` | Nonces consumidos y acumulados | No |
| `boveda/mnd-*.json` | Mandatos firmados | Sí, no traen secretos |
| `boveda/ledger_mandatos.jsonl` | Bitácora de decisiones | Agrégalo al `.gitignore` |

Todo lo sensible cae bajo `boveda/secretos/`, que tu `.gitignore` ya excluye.
El único que falta agregar es `boveda/ledger_mandatos.jsonl`.

## Guardarraíles

- Por defecto el ejecutor solo opera contra `sandbox.wompi.co`. Mover dinero
  real exige `--produccion` **y** llaves `pub_prod_`. Es deliberado que sea
  incómodo.
- El nonce se consume aunque el banco rechace el cobro. Si no, un rechazo se
  convierte en una vía para reintentar un mandato indefinidamente.
- El ledger anota **también los rechazos**. Un intento atajado que no queda
  escrito es un ataque que no se puede contar después.

## Dos decisiones de diseño que conviene discutir

**La llave privada del titular está en disco.** En un despliegue real vive en su
dispositivo o en un HSM, y la firma ocurre allá. Aquí está en `boveda/` porque
esto es un banco de pruebas; esconderlo daría una falsa sensación de rigor.

**El estado es un JSON local.** Acumulados y nonces en `boveda/secretos/estado.json`.
Sirve para la iteración 1 y no sirve para nada más: no hay concurrencia, no hay
atomicidad, y un atacante con acceso al archivo desactiva los controles 4, 6 y 7
borrando una línea. Cuando la PoC pase de un proceso a dos, esto tiene que ser
una base de datos con transacciones — y ese salto merece quedar registrado como
hallazgo, porque es exactamente el punto donde un integrador apurado se
equivocaría.

## Vocabulario

Sigue a [AP2](https://ap2-protocol.net/en/):

- **`intent`** — el titular está ausente. Autoriza al agente bajo restricciones.
  Es el caso interesante, y el peligroso.
- **`cart`** — el titular está presente y firma un carrito concreto. Su hash
  queda dentro del mandato, así que alterarlo después invalida la firma.

En Colombia esto tiene peso legal, no solo técnico: la **Ley 527 de 1999** y el
**Decreto 2364 de 2012** dan validez probatoria a la firma electrónica. Un
mandato firmado es la evidencia con la que se resuelve una disputa sobre si el
titular autorizó o no.
