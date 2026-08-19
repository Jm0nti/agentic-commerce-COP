# Fase A con dinero real

**Rama `prod`** · 18 de agosto de 2026

El titular autoriza una vez, desde su cuenta Nequi real, con un push que acepta
en la app. Después de eso el agente puede cobrar sin él. Este documento cubre
qué se usa, por qué, y qué hacer antes de correrlo.

---

## 1. Una corrección al informe anterior

El informe de viabilidad decía que activar Nequi en Wompi exigía el **modelo
Gateway**, con ejecutivo comercial y trámite de semanas. Eso salía del artículo
de soporte titulado *"¿Cómo activar Nequi bajo el modelo Gateway?"* — que es
correcto, pero describe solo uno de los dos modelos.

En el **Modelo Negocios (Agregador)** Nequi viene entre los medios estándar, y
el plan que lo habilita —**Avanzado Agregador**— se activa **100% en línea**.

| | Modelo Negocios (Agregador) | Modelo Gateway |
|---|---|---|
| Activación | En línea | Ejecutivo + código de venta no presente + convenios con Bancolombia |
| Medios | Tarjetas, **Nequi**, PSE, Botón Bancolombia, QR, Daviplata, BNPL, Corresponsales, SU+Pay | Solo aquellos con convenio directo |
| Dinero | Wompi centraliza y dispersa | Directo a la cuenta del comercio |
| Comisión | 2.65% + $700 + IVA por transacción aprobada (QR 1%, primer mes 0%) | Se negocia con Bancolombia |

Requisitos del plan Avanzado Agregador, según la propia página: **RUT original
en PDF de la DIAN** (no fotos ni capturas) y **cuenta Bancolombia o Nequi
activa** para recibir. Sirve para persona natural.

Que la cuenta receptora pueda ser **Nequi** es cómodo para la PoC: el circuito
cerrado se arma sin abrir nada nuevo.

> **Discrepancia sin resolver.** La página del plan dice desembolso **al
> siguiente día hábil**. El Reglamento de Comercios dice **hasta 5 días
> hábiles**, y hasta 30 días el primer desembolso de un comercio persona natural
> nuevo. Los dos son documentos publicados por Wompi. Presupueste con el
> pesimista y verifique con el primer cobro real.

---

## 2. Qué más hay en el ecosistema, y por qué no

La instrucción era no construir desde cero. Se revisó qué ofrece el mercado
colombiano para el primitivo concreto que la Fase A necesita: **autorización una
vez, cobro N veces después, sin el titular presente**.

| Herramienta | Nequi | Tokenización / recurrente | Onboarding | Veredicto |
|---|---|---|---|---|
| **Wompi** | Sí | **Sí** — `payment_sources` para CARD, NEQUI, DAVIPLATA, BANCOLOMBIA_TRANSFER | En línea (Avanzado Agregador) | **Es el que sirve** |
| Bold | Sí | **No documenta** tokenización ni cobros sin el cliente presente | API self-service, `x-api-key` | Cada cobro exige al titular. No hay delegación que estudiar |
| ePayco | Sí como medio | Tokenización documentada **solo para tarjeta de crédito** | En línea | Sirve como plan B de tarjeta, no de Nequi |
| Treli | Sí, automático | Sí, pero **por debajo usa Wompi** | SaaS | Esconde justo la capa que la PoC quiere medir |
| Nequi Conecta directo | Sí | Sí — API de Suscripciones, el mejor primitivo del país | Contrato con Nequi para Negocios | Meses. Vale la pena para la iteración 2 |
| Cobre | Sí, tokenización Nequi | Sí | Comercial, enterprise | Fuera de escala para una PoC |

**Treli es la confirmación indirecta más útil de todas.** Es un SaaS colombiano
de suscripciones que cobra por Nequi de forma automática y recurrente, y su
documentación dice explícitamente que requiere un plan **"Avanzado Agregador" o
"Avanzado Gateway"** activo en Wompi. Si Treli cobra Nequi recurrente sobre el
modelo Agregador, las fuentes de pago Nequi funcionan en producción bajo ese
modelo. Eso resuelve la duda que el informe anterior dejó abierta.

Pero Treli no sirve *para la PoC*: es una capa de facturación que envuelve el
mandato, los reintentos y la cancelación. Justo lo que hay que observar en
crudo. Se usa Wompi directo.

---

## 3. Qué se construyó

Un módulo nuevo y cuatro comandos. Nada más — el resto ya existía.

```
boveda/enrolamiento.py    Fase A: token Nequi, espera del push, fuente de pago,
                          revocación, y el registro de fuentes por modo
boveda/cli.py             + preflight, enrolar, fuentes, revocar
tests/test_enrolamiento.py  10 pruebas contra una Wompi simulada
```

`enrolamiento.py` **no cobra**. Cobrar sigue siendo `nucleo.py`, donde viven los
topes duros. La separación importa: enrolar es un acto del titular, cobrar es un
acto del agente. Si un solo comando hiciera las dos cosas, la PoC no podría
distinguir cuál de los dos falló.

---

## 4. El flujo

```
POST /v1/tokens/nequi        {phone_number}      -> token, status PENDING
   >>> llega el push a la app Nequi <<<
GET  /v1/tokens/nequi/{id}   (sondeo)            -> PENDING ... APPROVED
POST /v1/payment_sources     {type: NEQUI, ...}  -> payment_source_id, AVAILABLE
```

Desde `AVAILABLE` el agente puede cobrar. Sin tope propio, sin vencimiento, sin
ligadura a un producto. Ese es el hueco.

```
PUT  /v1/payment_sources/{id}/void                -> VOIDED
```

Es el único botón de pánico que existe. Wompi no ofrece nada más fino: no hay
"pausar", no hay "bajar el tope". O está viva o no. Conviene saber dónde está
antes de necesitarlo.

---

## 5. Cómo correrlo

### Antes de tocar nada

```bash
# 1. El repositorio y la rama prod (ver seccion 7)
.\scripts\init-repo.ps1

# 2. Las llaves de produccion en el .env de la raiz
#    WOMPI_PUBLIC_KEY=pub_prod_...
#    WOMPI_PRIVATE_KEY=prv_prod_...
#    WOMPI_INTEGRITY_SECRET=prod_integrity_...

# 3. Que el codigo corre
python -m pytest tests/ -q
```

### Preflight — sin involucrar a nadie todavía

```bash
python -m boveda.cli --modo produccion preflight
```

Confirma que el comercio responde, **que Nequi esté entre los medios activos**,
e imprime los dos enlaces de términos que la bóveda acepta en tu nombre en cada
llamada.

Si Nequi no aparece habilitado, el enrolamiento falla en silencio: el token se
queda en `PENDING` y el push nunca llega. Descubrirlo aquí cuesta un comando;
descubrirlo después cuesta a alguien mirando un teléfono que no suena.

### Enrolar — aquí sí llega el push a tu Nequi

```bash
python -m boveda.cli --modo produccion enrolar --telefono 3001234567 --email tu@correo.co
```

Pide confirmación escrita (`PRODUCCION`), crea el token, y se queda esperando
hasta 5 minutos a que aceptes en la app. Transcripción real del flujo:

```
  *** MODO PRODUCCION -- esto opera sobre cuentas reales ***

  ====================================================================
  PRODUCCION -- enrolamiento de una cuenta Nequi real
  ====================================================================
  telefono          3001234567
  correo            tu@correo.co

  No se cobra nada en este paso. Lo que se entrega es la autorizacion
  para cobrar despues sin que usted este presente, sin tope propio y
  sin vencimiento. Se revoca con `revocar <id>`.
  ====================================================================
  Escriba PRODUCCION para continuar: PRODUCCION

  token          solicitando la suscripcion para 300****567
  token_creado   nequi_prod_RQkUiuv... estado PENDING

  >>> REVISA TU APP NEQUI: LLEGO UNA NOTIFICACION PARA ACEPTAR LA SUSCRIPCION
      esperando......
  fuente         aceptado. Creando la fuente de pago
  lista          fuente 3891 en estado AVAILABLE
```

**No se mueve un peso en este paso.** Lo que se entrega es la autorización, que
es peor: el dinero se puede devolver, una autorización mal dada sigue viva hasta
que alguien la revoque.

### Ver y apagar

```bash
python -m boveda.cli --modo produccion fuentes
python -m boveda.cli --modo produccion revocar 3891
```

### El primer cobro real

```bash
python -m boveda.cli --modo produccion emitir --monto 2000
python -m boveda.cli --modo produccion ejecutar <mandato_id> -m 2000
```

`emitir` toma automáticamente la fuente viva más reciente **del modo actual**.
Nunca cruza modos.

---

## 6. Guardarraíles

| Control | Dónde | Se puede apagar |
|---|---|---|
| Modo y prefijo de llave tienen que coincidir | `nucleo.py` | No |
| Topes duros: 20.000 COP/tx, 100.000 COP/día | `nucleo.py` | No |
| Confirmación escrita en producción | `cli.py` | Sí, con `--si` (para guiones) |
| Fuentes separadas por modo, sin cruce | `enrolamiento.py` | No |
| `revocar` exige que la fuente sea del modo actual | `enrolamiento.py` | No |
| Teléfono validado antes de salir a la red | `enrolamiento.py` | No |
| Verificación de mandato | `nucleo.py` | Sí, con `--sin-mandato` — **es el experimento** |

La separación entre las dos últimas filas es la tesis del proyecto y ya estaba
en tu `nucleo.py`: el mandato es lo que se estudia, el tope duro es lo que
protege. Apagar el control para medir su efecto no puede apagar la protección.

**Por qué el registro separa por modo.** Un `payment_source_id` es un entero. El
mismo entero existe en sandbox y en producción apuntando a cuentas distintas.
Antes, `emitir` sin `--fuente` leía el cache del banco de pruebas — en modo
producción eso habría emitido un mandato contra un id de sandbox, o peor, contra
uno que existe en los dos lados y pertenece a otra persona. Hay una prueba
dedicada a eso.

---

## 7. El repositorio

**No pude crear el repo desde la sesión remota.** El puente hacia tu máquina
puede escribir archivos pero no borrarlos, y git necesita borrar
`.git/index.lock` después de cada operación que escribe el índice. Quedó un
`.git/` a medio hacer con un lock atascado.

`scripts/init-repo.ps1` lo limpia y hace todo bien:

```powershell
.\scripts\init-repo.ps1
```

Borra el `.git` incompleto, inicializa limpio en `main`, **verifica que ningún
archivo sensible entre al índice antes de commitear** (aborta si aparece `.env`,
`secretos/` o `firma.sk`), hace el primer commit con el estado de sandbox, y crea
`prod` encima.

---

## 8. Antes del primer enrolamiento real

- [ ] Plan **Avanzado Agregador** activo y Nequi habilitado (`preflight` lo confirma)
- [ ] `.env` con llaves `pub_prod_` / `prv_prod_`, y `.env` fuera de git
- [ ] `python -m pytest tests/ -q` en verde
- [ ] Avisar a Wompi. Un comercio cobrándose a sí mismo en bucle es el patrón que
      dispara el monitoreo antifraude; que congelen la cuenta a mitad de la PoC
      cuesta semanas. Ya está el texto en `docs/solicitudes-bancolombia-nequi.md`
- [ ] Presupuestar la comisión: 2.65% + $700 + IVA **por transacción aprobada**.
      En circuito cerrado cada vuelta pierde el fee. Con cobros de 2.000 COP la
      comisión supera el monto — cuente el gasto, no el flujo
- [ ] Saber de memoria cómo se revoca: `revocar <id>`
- [ ] Revisar el tope de tu cuenta Nequi. Las cuentas con límite no pueden gastar
      más de $7.268.208 al mes; las tradicionales no tienen tope

---

## 9. Qué observar

Lo que la Fase A debería producir como hallazgo, más allá de "funcionó":

1. **Cuánto ve el titular en el push.** ¿Dice el monto? ¿Dice que es una
   suscripción sin tope ni vencimiento? ¿O solo el nombre del comercio? La
   diferencia entre lo que Nequi muestra y lo que el titular está entregando es
   material para el informe.
2. **Si el token vence.** Wompi no documenta un vencimiento del token Nequi. Vale
   medirlo: enrolar, no aceptar, y ver cuánto dura `PENDING`.
3. **Qué pasa al revocar desde la app Nequi** en vez de con `void`. ¿La fuente
   queda `AVAILABLE` en Wompi y el cobro falla, o Wompi se entera? Si Wompi no se
   entera, la bóveda cree tener una autorización que ya no existe.
4. **El error exacto cuando la cuenta no tiene saldo.** Para distinguir un
   rechazo por fondos de uno por revocación hace falta ver los dos.
5. **Los `acceptance_token`.** Los está aceptando la bóveda en nombre de una
   persona. En producción esa persona eres tú y sí puedes leerlos — `preflight`
   imprime los enlaces. Hacerlo una vez convierte una nota al pie en un hallazgo
   con fundamento.

---

## Fuentes

- [Plan Avanzado Agregador — Wompi](https://wompi.com/es/co/planes-tarifas/plan-avanzado-agregador)
- [¿Qué es el Modelo Negocios (Agregador)? — Wompi](https://soporte.wompi.co/hc/es-419/articles/47313815889939--Qu%C3%A9-es-el-Modelo-Negocios-Agregador)
- [¿Qué diferencia el modelo Negocios del modelo Gateway? — Wompi](https://soporte.wompi.co/hc/es-419/articles/360020775954--Qu%C3%A9-diferencia-el-modelo-Negocios-del-modelo-Gateway)
- [Fuentes de pago & Tokenización — Wompi Docs](https://docs.wompi.co/en/docs/colombia/fuentes-de-pago/)
- [¿Cómo es el proceso de pago con Nequi? — Wompi](https://soporte.wompi.co/hc/es-419/articles/1500007702282--C%C3%B3mo-es-el-proceso-de-pago-con-Nequi)
- [Monto mínimo y máximo para pagos por Nequi — Wompi](https://soporte.wompi.co/hc/es-419/articles/1500007684121--Cu%C3%A1l-es-el-monto-m%C3%ADnimo-y-m%C3%A1ximo-para-realizar-pagos-por-Nequi)
- [Reglamento de Comercios Wompi Colombia (V3-2025)](https://wompi.com/assets/downloadble/reglamento-Comercios-Colombia.pdf)
- [Proceso de integración — Bold Developers](https://developers.bold.co/pagos-en-linea/api-de-pagos-en-linea/integracion)
- [Cobrar con token — ePayco Docs](https://docs.epayco.com/docs/cobrar-con-token)
- [Integración con Wompi — Treli Docs](https://treli.readme.io/docs/wompi)
- [Suscripciones con Nequi — Treli](https://treli.co/suscripciones-con-nequi/)
- [Pagos recurrentes con Nequi — API de suscripciones](https://www.nequi.com.co/negocios/pagos-recurrentes)
- [Débito automático con Nequi para empresas — Cobre](https://www.cobre.com/local-payments/debito-a-cuenta)
