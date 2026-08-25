# Flujo de la PoC

Runbook de comandos después de los cambios del 19 de agosto de 2026.

---

## Lo primero: no, no hay que volver a enrolar

Los datos del `.env` (`PAGADOR_*`) se usan **al cobrar**, no al enrolar. Son
campos de la transacción, no de la fuente de pago.

La fuente `22620436` sigue viva y sirve. Lo que el antifraude rechazó fue **la
transacción**, no la fuente — si la fuente hubiera estado mal, el error habría
sido otro. Confírmalo con:

```bash
python -m boveda.cli --modo produccion fuentes
```

Si dice `AVAILABLE`, no toques nada. Re-enrolar solo tiene sentido si:

- la fuente aparece `VOIDED` (la revocaste, o la cancelaste desde la app Nequi), o
- Wompi te responde que el problema es el registro del cliente asociado a la
  fuente — improbable, pero es la única hipótesis que obligaría a rehacerla.

Enrolar cuesta un push. No es caro, pero tampoco es gratis: cada fuente nueva es
una autorización más viva contra tu cuenta, y hay que acordarse de revocar las
que quedan sueltas.

**Lo que sí está vencido es el mandato.** `emitir` usa por defecto un uso y 60
minutos de vigencia, así que `mnd_c048d9219722` ya no sirve. Dato útil: el
`DECLINED` **no lo consumió** — solo un `APPROVED` suma usos. Está vencido por
tiempo, no por gasto.

---

## Fase 0 — una sola vez

```bash
pip install -r requirements.txt

# El .env en la raiz. Contenido en docs/variables-de-entorno.md
#   WOMPI_PUBLIC_KEY / PRIVATE_KEY / INTEGRITY_SECRET
#   WOMPI_EVENTS_SECRET
#   PAGADOR_EMAIL / NOMBRE / TELEFONO / DOCUMENTO / TIPO_DOC

python -m pytest tests/ -q          # 25 en verde
python -m boveda.cli llaves         # par ed25519 del titular
```

`llaves` es idempotente: si ya existen, avisa y no las toca. Rotarlas invalida
todos los mandatos firmados.

---

## Fase A — el titular autoriza (ya está hecha)

```bash
python -m boveda.cli --modo produccion preflight
python -m boveda.cli --modo produccion enrolar --telefono 3232014944
python -m boveda.cli --modo produccion fuentes
```

`preflight` ahora hace dos cosas: verifica que Nequi esté habilitado en el
comercio, **y audita el perfil del pagador** que va a ver el antifraude. Después
del rechazo de ayer, correrlo antes de cada sesión deja de ser opcional.

`enrolar` manda el push y espera hasta 5 minutos. No cobra nada.

---

## Fase B — el agente cobra (el ciclo de todos los días)

```bash
# 1. Ver que hay
python -m boveda.cli --modo produccion listar

# 2. Emitir uno nuevo (casi siempre hace falta: vencen en 60 min)
python -m boveda.cli --modo produccion emitir --monto 2000

# 3. Ejecutarlo
python -m boveda.cli --modo produccion ejecutar <mandato_id> -m 2000

# 4. Ver el resultado
python -m boveda.cli --modo produccion recibos
```

`listar` ahora marca cada mandato como `usable`, `vencido`, `usos agotados`,
`tope agotado` u `otro ambiente`, y si no queda ninguno usable te dice el comando
para emitir otro.

`emitir` toma sola la fuente viva más reciente **de ese modo**. Solo hace falta
`--fuente` si tienes varias y quieres una en concreto.

Defaults de `emitir`, deliberadamente estrechos:

| | Default | Cambiar con |
|---|---|---|
| Usos | 1 | `--usos 3` |
| Vigencia | 60 min | `--vigencia 480` |
| Tope acumulado | = `--monto` | `--tope-total 10000` |
| Comercio | `tienda_demo` | `--comercio otro` |

Un mandato amplio debería costar escribirlo, no ser lo que sale por omisión.

---

## Diagnóstico — cuando algo sale `DECLINED`

```bash
python -m boveda.cli --modo produccion diagnostico <transaction_id>
python -m boveda.cli --modo produccion diagnostico <transaction_id> --json
```

Ya no hace falta abrir el dashboard: `ejecutar` imprime `antifraude` y `mensaje`
directamente, y si fue el AFE lo dice con todas las letras.

Para ver los eventos que Wompi intentó entregarte, levanta el receptor:

```bash
uvicorn boveda.eventos:app --port 8000
# exponerlo con ngrok/cloudflared y poner esa URL en
# Dashboard > Desarrolladores > Eventos
```

---

## Pánico

```bash
python -m boveda.cli --modo produccion revocar 22620436
```

Único botón que existe. Irreversible: para volver a cobrar hay que enrolar de
nuevo. Wompi no ofrece "pausar" ni "bajar el tope".

---

## El experimento

Es la razón de todo lo anterior. Necesita **dos corridas comparables**:

```bash
# el mandato autoriza 2.000
python -m boveda.cli --modo produccion emitir --monto 2000

# brazo con control: la boveda lo detiene antes de llamar a Wompi
python -m boveda.cli --modo produccion ejecutar <id> -m 15000

# brazo sin control: la boveda deja pasar, Wompi decide
python -m boveda.cli --modo produccion emitir --monto 2000
python -m boveda.cli --modo produccion ejecutar <id2> -m 15000 --sin-mandato
```

> **Ojo con esto ahora mismo.** Mientras el AFE rechace, los dos brazos dan
> `DECLINED` y la comparación no mide el efecto del mandato — mide el del
> antifraude de Wompi. Hay que conseguir al menos un `APPROVED` antes de que el
> experimento signifique algo. Ver `docs/decline-afe.md`.

Los 15.000 del ejemplo siguen bajo el tope duro de 20.000, así que el brazo sin
control llega de verdad a Wompi. Es a propósito: si el tope duro lo atajara, no
habría brazo sin control.

---

## Referencia rápida

| Comando | Qué hace | ¿Mueve dinero? |
|---|---|---|
| `llaves` | Par ed25519 del titular | No |
| `preflight` | Comercio, medios activos, perfil del pagador | No |
| `enrolar --telefono N` | Fase A: push y fuente de pago | No (entrega la autorización) |
| `fuentes` | Fuentes registradas en ese modo | No |
| `revocar <id>` | Apaga una fuente | No |
| `emitir --monto N` | Mandato firmado | No |
| `ejecutar <id> -m N` | Fase B: el cobro | **Sí** |
| `diagnostico <tx>` | Lo que Wompi dice de una transacción | No |
| `listar` | Mandatos y su estado | No |
| `recibos` | Historial de decisiones | No |

---

## Trampas que ya me comí

**`--modo` y `--si` van antes del subcomando.** Son flags globales:

```bash
python -m boveda.cli --modo produccion ejecutar mnd_x -m 2000   # bien
python -m boveda.cli ejecutar --modo produccion mnd_x -m 2000   # error
```

**Sin `--modo`, todo corre en sandbox.** Y como el modo tiene que coincidir con
el prefijo de la llave, con llaves `pub_prod_` en el `.env` un comando sin
`--modo` no cobra por error: falla de entrada.

**Un mandato de un ambiente ya no se ejecuta en el otro.** `estado.json` es un
solo archivo para los dos modos, y `fuente_pago` es un entero que en producción
apunta a otra cuenta. Ahora la bóveda lo rechaza con el mensaje explícito. Los
mandatos emitidos antes de este cambio no traen modo registrado y se dejan pasar
— romper el estado existente habría sido peor que la guarda que falta.

**El gasto diario es compartido entre sandbox y producción.** Una tanda de
pruebas consume el cupo real de 100.000 COP. Es conservador a propósito: falla
hacia el lado seguro.

**En Fase B no llega ningún push.** El titular no se entera de ningún cobro. El
webhook es la única señal, y por eso importa que funcione.

**No reintentes en bucle tras un `DECLINE` del AFE.** Wompi vigila los intentos
fallidos repetidos y cada uno empeora el perfil.

---

## Estado actual, en orden

1. `preflight` → confirmar que el perfil del pagador ya no está vacío
2. `fuentes` → confirmar que `22620436` sigue `AVAILABLE`
3. Escribirle a Wompi (`docs/decline-afe.md`, sección 6.2) — **esto es lo que
   desbloquea**
4. Un solo `emitir` + `ejecutar` de 2.000 COP. Uno, no un bucle
5. Si vuelve `DECLINE`: la respuesta la tiene Wompi, no el código
6. Si vuelve `APPROVED`: ahí sí empieza el experimento de la sección anterior
