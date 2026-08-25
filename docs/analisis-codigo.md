# Análisis del código actual

**19 de agosto de 2026** · 4.287 líneas · el flujo completo funciona con dinero real

---

## Lo que hay que decir primero

El código está mejor de lo que suele estar una PoC. Tres cosas que **no** hay que
tocar en la refactorización porque ya son correctas:

1. **La separación entre el mandato y el tope duro** (`nucleo.py:9-19`). Lo que se
   estudia se puede apagar; lo que protege, no. Esa distinción es difícil de
   inventar después y aquí ya está.
2. **`mandato.py` es dominio casi puro.** 229 líneas, sin IO, sin HTTP, sin
   configuración. Su única dependencia externa es `cryptography` para firmar. Es
   el núcleo alrededor del cual se acomoda todo lo demás.
3. **La honestidad de `Recibo`.** Guarda lo que el mandato decía *al lado* de lo
   que pasó, incluida `aprobado_pese_a_violacion`. Ese campo es el experimento.

Y una evidencia que conviene no perder en la refactorización: en
`boveda/recibos.jsonl` está la corrida donde un mandato que autorizaba 8.000 COP
terminó en un cobro de 15.000 `APPROVED` con tres violaciones registradas. Ese
archivo es el resultado, no un log.

---

## Los hallazgos

Ordenados por cuánto duelen cuando llegue la app, no por cuánto ofenden hoy.

### 1. `Boveda` es un god object — `nucleo.py:257-421`

Una sola clase hace siete cosas: cargar y guardar un JSON, resolver mandatos,
evaluar políticas, aplicar topes duros, hablar HTTP con Wompi, hacer long-polling
y mutar el consumo.

```python
self.cliente = ClienteWompi(modo)     # nucleo.py:277 — la pasarela, cableada en el constructor
self.estado = self._cargar()          # nucleo.py:279 — la persistencia, también
```

**Por qué duele con la app:** no se puede reusar. Para meter una pasarela
simulada hay que tocar la clase. Para probarla hace falta un `monkeypatch` de
variables de entorno y un archivo temporal. Para servir dos peticiones web
concurrentes, no hay forma.

**En qué se convierte:** un caso de uso `EjecutarIntencion` que recibe sus
dependencias por constructor, contra interfaces.

---

### 2. Persistencia sin atomicidad ni concurrencia — `nucleo.py:288-292`

```python
def _guardar(self) -> None:
    self.estado_path.write_text(json.dumps(self.estado, ...))
```

Lee todo, muta en memoria, reescribe todo. Sin lock, sin transacción, sin
escritura atómica.

**Por qué duele:** hoy es deuda anotada. Con un servidor web es un bug de
seguridad. Dos cobros simultáneos leen `gastado_dia_cop = 90.000`, cada uno suma
15.000, el último escribe 105.000 — y el tope duro de 100.000 **ya no es un
tope**. El control que existe para no perder dinero es justamente el que se
rompe primero bajo concurrencia.

Peor: un `write_text` interrumpido a la mitad deja el JSON corrupto y con él se
pierden todos los mandatos y el consumo.

**En qué se convierte:** SQLite con transacciones y `UPDATE ... WHERE` para el
consumo. El tope diario tiene que ser una condición en la escritura, no una
lectura previa.

---

### 3. El long-polling bloquea un minuto — `nucleo.py:214-225`

```python
def esperar(self, tx_id, intentos: int = 40, pausa: float = 1.5):
    for _ in range(intentos):
        ...
        time.sleep(pausa)   # nucleo.py:224
```

40 × 1,5s = hasta 60 segundos de bloqueo síncrono. En CLI es aceptable. En una
app de chat significa un worker ocupado un minuto por compra, y un usuario
mirando un spinner sin saber qué pasa.

Y hay una ironía: `eventos.py` ya recibe el `transaction.updated` que haría
innecesario el polling, pero sólo lo escribe a un `.jsonl` que **nadie lee**
(`eventos.py:97-99`). El canal correcto existe y está desconectado.

**En qué se convierte:** `EjecutarIntencion` devuelve `PENDIENTE` de inmediato;
`ConciliarEvento` cierra el ciclo desde el webhook; el chat recibe el desenlace
por SSE. El polling queda como respaldo, no como camino principal.

---

### 4. No hay idempotencia — `nucleo.py:364`

```python
referencia = f"bov-{uuid.uuid4().hex[:14]}"
```

Referencia nueva en cada intento. Si el POST llega a Wompi pero la respuesta se
pierde por timeout, el reintento **crea un segundo cobro**. Wompi rechaza
referencias repetidas — esa sería la defensa — pero sólo funciona si reusamos la
referencia, y no la reusamos.

**En qué se convierte:** la referencia se deriva del `intencion_id`. Reintentar
es seguro por construcción, y el rechazo de Wompi por duplicado pasa de estorbo a
red de seguridad.

---

### 5. Credenciales leídas del entorno global en el constructor — `nucleo.py:124-126`

```python
self.pub = os.environ.get("WOMPI_PUBLIC_KEY", "")
```

Imposible tener dos configuraciones en el mismo proceso. Los tests necesitan
`monkeypatch.setenv`. Un futuro multi-comercio no cabe.

**En qué se convierte:** un objeto `ConfiguracionWompi` construido en el
*composition root* y pasado al adaptador. El entorno se lee en un solo lugar del
programa.

---

### 6. El dominio conoce a Wompi — `mandato.py:57`

```python
@dataclass
class Mandato:
    fuente_pago: int    # <- un payment_source_id de Wompi, dentro del dominio
```

Es el acoplamiento más caro de todos porque **está dentro de la carga firmada**
(`mandato.py:69-72`). Cambiar el tipo invalida las firmas existentes.

**Por qué duele:** con pasarela simulada y Wompi conviviendo, un `int` no basta
para saber a qué mundo pertenece. Ya viste la versión suave de este problema
cuando hubo que agregar la guarda de modos (`nucleo.py:319-330`) — el síntoma era
exactamente que `fuente_pago` es un entero sin contexto.

**En qué se convierte:** `medio_de_pago: MedioDePagoRef` con `proveedor` y
`id_externo`. Requiere versionar el mandato (`version: 2`) y mantener el
verificador de la v1 para no romper lo firmado.

---

### 7. `Recibo` mezcla dominio y detalle del proveedor — `nucleo.py:64-112`

`estado_wompi`, `status_message`, `afe_decision` son campos de Wompi viviendo en
un objeto del dominio. Registrarlos es correcto — `afe_decision` resultó ser el
dato más valioso de toda la corrida. Pero deberían ir en un sub-objeto
`detalle_proveedor: dict` para que el dominio no dependa del nombre de una
pasarela.

Observación de la evidencia: `afe_decision` toma al menos dos valores,
`DECLINE` y `FRAUD_CHECK` (el aprobado de 2.050 COP). No es booleano, y
`detenido_por_antifraude` (`nucleo.py:104-112`) hace bien en comparar sólo contra
`DECLINE`.

---

### 8. `evaluar()` devuelve violaciones, no un dictamen — `mandato.py:172-229`

La política real —"cualquier violación bloquea"— está implícita en el `if` de
`nucleo.py:354`. Para el agente vas a necesitar graduar: bloquear, **pedir
confirmación al humano**, o dejar pasar registrando.

Ese caso intermedio es el más interesante de la app: el agente propone algo que
no viola el mandato pero sí huele raro, y la respuesta correcta no es sí ni no,
es preguntar.

**En qué se convierte:** `evaluar()` devuelve un `Dictamen` con
`PERMITIR | CONFIRMAR | BLOQUEAR` más las violaciones que lo sustentan.

---

### 9. Sin puertos para el reloj ni los identificadores — `mandato.py:42-43, 159`

```python
def ahora(): return datetime.now(timezone.utc)
mandato_id=f"mnd_{uuid.uuid4().hex[:12]}"
```

Probar vencimientos obliga a trucos como emitir con vigencia negativa — que es
justo lo que tuve que hacer en `tests/test_modos.py`. Un `Reloj` y un
`GeneradorIds` inyectables vuelven el tiempo un parámetro.

---

### 10. Errores sin tipo — `enrolamiento.py` y `nucleo.py`, 12 sitios

Todo es `BovedaError` con un mensaje formateado, y algunos casos vuelven como
`Recibo(motivo="error_pasarela: Wompi 422: {...}")` (`nucleo.py:377`). En
`recibos.jsonl` hay una fila exactamente así.

Un agente no puede decidir qué hacer sin parsear texto. "Fondos insuficientes"
(reintentar más tarde) y "mandato vencido" (pedir uno nuevo) son respuestas
opuestas y hoy son la misma cadena.

**En qué se convierte:** jerarquía de errores del dominio, y el detalle crudo del
proveedor guardado aparte para la auditoría.

---

### 11. `cli.py` tiene lógica de negocio — 714 líneas

`_fuente_por_defecto` (`cli.py:353`) decide cuál medio de pago usar. `confirmar`
(`cli.py:105`) es una política de autorización. Cuando llegue la API web, o se
duplica o se extrae.

---

### 12. Código muerto que confunde el mapa

- `mandato/` (943 líneas) — la entrega temprana que refactorizaste dentro de
  `boveda/`. Duplica conceptos con nombres distintos.
- `wompi_lab/` (987 líneas) — banco de pruebas. Cumplió su función; `payouts.py`
  vale conservarlo por la parte de Bre-B, que no está en ningún otro lado.

Juntos son el 45% del código del repositorio.

---

### 13. Cosas menores pero reales

- **`gastado_dia_cop` compartido entre modos** (`nucleo.py:286`). Conservador, pero
  una tanda de pruebas consume el cupo real.
- **`aceptaciones()` en cada cobro** (`nucleo.py:177`) — un GET extra por
  transacción. Los tokens duran; se pueden cachear.
- **`esperar()` no distingue un fallo de red de un `PENDING`** (`nucleo.py:221`):
  `r.json()["data"]` revienta con `KeyError` si Wompi devuelve un error.
- **Sin trazabilidad conversación → intención.** Para la app hace falta saber qué
  turno del chat produjo qué carrito, qué mandato y qué cobro. Hoy ese hilo no
  existe y es justamente lo que se quiere demostrar.

---

## Lo que el análisis no cubre

- No corrí análisis estático (`ruff`, `mypy`) sobre el árbol completo; los
  hallazgos salen de lectura y de la evidencia en `recibos.jsonl`.
- No evalué `wompi_lab/payouts.py` a fondo — es scratch y la ruta de Bre-B sigue
  siendo conjetura declarada en su propio encabezado.
- La cobertura de pruebas actual (25 casos) cubre enrolamiento, eventos y modos.
  **No hay pruebas de `Boveda.ejecutar` en el camino feliz** más allá del caso de
  `DECLINED` que agregué. El camino que mueve dinero es el menos probado.
