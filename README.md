# PoC de comercio agéntico sobre rieles colombianos

Un agente hace una compra y el dinero llega a un comercio real, sobre Wompi. El
objeto de estudio es lo que pasa en medio: qué autoriza el titular, qué ejecuta
el agente, y cuánto de la diferencia entre esas dos cosas alcanza a detenerse.

## Estado

Sandbox de cobros verificado de punta a punta. El hallazgo de partida ya está en
`wompi_lab/ledger.jsonl`: una sola suscripción Nequi y después cobros de 67.450,
88.300 y 17.400 COP, ninguno autorizado por separado, los tres `APPROVED`.

Wompi no tiene el concepto de mandato. Una fuente de pago autoriza al comercio a
cobrar y punto — sin techo, sin vencimiento, sin ligadura a un producto. La
bóveda es la capa que falta.

**Rama `prod`:** Fase A implementada contra producción. El titular enrola su
cuenta Nequi real aceptando un push en la app. Ver `docs/fase-a-produccion.md`.

## Componentes

```
wompi_lab/     banco de pruebas de la pasarela, sin abstracciones
  lab.py         cobros: tarjeta, Nequi, fuente de pago
  payouts.py     envíos: cuentas bancarias y llaves Bre-B

boveda/        lo único que toca credenciales de pago
  enrolamiento.py  Fase A: el titular autoriza una vez, por push
  mandato.py       modelo del mandato, firma ed25519, evaluación
  nucleo.py        Fase B: ejecución contra Wompi, topes duros
  cli.py           las dos fases desde la terminal
```

El agente irá aparte y nunca verá una credencial: solo pide a la bóveda que
ejecute un mandato por su `mandato_id`.

## Arranque

```bash
pip install -r requirements.txt

# .env en la raíz
#   WOMPI_PUBLIC_KEY=pub_test_...      (o pub_prod_ en la rama prod)
#   WOMPI_PRIVATE_KEY=prv_test_...
#   WOMPI_INTEGRITY_SECRET=test_integrity_...

python -m pytest tests/ -q
python -m boveda.cli llaves
```

### Fase A — el titular autoriza, una vez

```bash
python -m boveda.cli --modo produccion preflight
python -m boveda.cli --modo produccion enrolar --telefono 3001234567
python -m boveda.cli --modo produccion fuentes
python -m boveda.cli --modo produccion revocar <payment_source_id>
```

`preflight` confirma que Nequi esté habilitado antes de involucrar a un humano
con un teléfono. `enrolar` manda el push y espera hasta 5 minutos. No se cobra
nada: lo que se entrega es la autorización.

### Fase B — el agente cobra, sin el titular

```bash
python -m boveda.cli emitir --monto 8000
python -m boveda.cli ejecutar <mandato_id> -m 8000
python -m boveda.cli listar
python -m boveda.cli recibos
```

## El experimento

```bash
# el mandato autoriza 8.000; la intención pide 15.000
python -m boveda.cli ejecutar <id> -m 15000                 # detenido
python -m boveda.cli ejecutar <id> -m 15000 --sin-mandato   # Wompi lo aprueba
```

La diferencia entre las dos corridas es el efecto del control. Sin el brazo de
comparación, una tasa sola no dice nada.

## Dos límites, distintos a propósito

**El mandato** es lo que se estudia. Se puede emitir amplio, degradar, o apagar
su verificación con `--sin-mandato`.

**El tope duro** es lo que protege. Vive en constantes de `boveda/nucleo.py`
(20.000 COP por transacción, 100.000 COP diarios), se aplica siempre y no se
puede desactivar por parámetro. Con dinero real, un bug en la capa que se está
estudiando no puede convertirse en una pérdida.

Si fueran el mismo límite, apagar el control para medir su efecto apagaría
también la protección.

## Lo que la PoC prueba, y lo que no

Prueba que un agente puede consumar un pago sobre infraestructura colombiana en
producción, y que el mandato firmado no lo detiene cuando fue el agente quien se
equivocó — solo cuando se desvía el comercio.

No prueba nada sobre desvío de beneficiario: con un solo comercio, el dinero
siempre llega a donde debe. Eso requiere un segundo comercio real, o el lado de
payouts.

## Antes de tocar producción

- Avisarle al equipo de Wompi. Un comercio cobrándose a sí mismo en bucle es el
  patrón que dispara monitoreo antifraude; que congelen la cuenta a mitad de la
  PoC cuesta semanas.
- Presupuestar la comisión: 2.65% + $700 + IVA por transacción aprobada. En
  circuito cerrado cada vuelta pierde el fee, y con cobros de 2.000 COP la
  comisión supera el monto.
- Nequi antes que tarjeta: cero superficie PCI, consentimiento observable por
  push, revocación en un comando (`PUT /v1/payment_sources/{id}/void`).
- Los `acceptance_token` los está aceptando el software en nombre de una persona
  que nunca vio el contrato. `preflight` imprime los dos enlaces: en producción
  esa persona eres tú y sí puedes leerlos.

## Documentos

```
docs/fase-a-produccion.md               qué se usa, por qué, y cómo correrlo
docs/informe-viabilidad-pagos-agenticos-co.md   comparativa de rieles colombianos
docs/solicitudes-bancolombia-nequi.md   qué pedir a Wompi, Bancolombia y Nequi
docs/arquitectura-iteracion-1.mermaid   el flujo con los puntos de control
```
