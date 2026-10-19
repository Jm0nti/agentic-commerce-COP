# El sistema de mandatos, de punta a punta

**Actualizado el 3 de septiembre de 2026** (multi-comercio, `agora/` con 2
comercios reales: Dulcería La Golosina y Papelería El Lápiz Feliz).

> **El agente propone. El humano firma. El motor de pagos ejecuta.**
> Ninguno de los tres puede hacer el trabajo de otro.

La pregunta que originó este documento fue por qué existe un tipo aparte
(`PropuestaDeMandato`) en vez de dejar que el agente arme un `Mandato` y ya.
La respuesta corta: **porque si el agente puede construir un `Mandato`, puede
construir uno que le convenga.** El resto de este documento es el recorrido
completo — el ejemplo paso a paso, dónde vive cada pieza, la criptografía
detrás de la firma, cómo firma el usuario en la práctica, y por qué el
agente no puede hacerlo él mismo.

---

## 1. El recorrido, con un ejemplo real

Juan le pide al agente algo dulce. El agente busca en el catálogo, encuentra
`Dulcería La Golosina` (`com_a6066287f648`) y arma un carrito con una
`Chocolatina Cremosa` (`prd_e4544c48a5f2`, 1.500 COP).

### Paso 1 — El agente arma el carrito y PROPONE, sin firmar

El agente llama a `armar_carrito`, una de sus seis herramientas
(`usecase/agente/herramientas.py`), que por debajo ejecuta
`NavegarCatalogoUseCase.armar_carrito` (`usecase/navegar_catalogo/navegar_catalogo_use_case.py`):

```python
carrito, propuesta = navegar_catalogo.armar_carrito(
    comercio_id="com_a6066287f648",
    items=[ItemPedido(producto_id="prd_e4544c48a5f2", cantidad=1)],
)
```

Esto produce dos objetos, y solo uno de los dos importa para lo que sigue:

- `Carrito` — comercio, ítems, precios, y un `hash_canonico` (el "Cart
  Mandate" de AP2: una huella del contenido exacto del carrito).
- `PropuestaDeMandato` — **sin firma, sin llave pública, sin verificador
  posible**. Un tipo de dato completamente distinto a `Mandato`
  (`model/mandato/modelo.py`), a propósito:

  ```python
  @dataclass(frozen=True)
  class PropuestaDeMandato:
      """Lo que el AGENTE pide. Todavia no lo firmo nadie.

      Existe como tipo propio para que sea imposible confundirla con un
      mandato: no tiene firma, no tiene llave publica, y ningun caso de uso
      la acepta donde espera un Mandato. La frontera entre proponer y
      autorizar queda en el sistema de tipos, no en la disciplina de quien
      escribe.
      """
      propuesta_id: str
      carrito_id: str
      comercio_id: str
      monto_max: Dinero
      usos_max: int = 1
      vigencia_minutos: int = 30
      categorias: tuple[str, ...] = ()
      justificacion: str = ""
  ```

  `monto_max` sale del total exacto del carrito y `usos_max=1` por defecto —
  límites estrechos a propósito: un
  mandato amplio debería costar escribirlo a propósito, no ser lo que sale
  por omisión.

El agente le muestra a Juan el `propuesta_id` y, en el chat por terminal, el
comando exacto para firmarla (`app_service/config/agente.py`); en el chat web
(`entry_points/api_rest/`), un popup se abre solo, empujado por un evento SSE
(`propuesta_pendiente`).

### Paso 2 — El humano firma: `PropuestaDeMandato` → `Mandato`

Este es el único paso que produce un objeto `Mandato` de verdad, y es
también el único paso que **nunca** ejecuta el agente — ver la sección 5. Lo
hace el caso de uso `EmitirMandatoUseCase` (`usecase/emitir_mandato/emitir_mandato_use_case.py`),
invocado por la persona:

- desde la terminal, con `python -m agora cli firmar <propuesta_id> <titular>`
  (si el carrito lo armó el chat, en otro proceso) o con
  `emitir <comercio_id> <titular> --item ...` (si la misma persona opera la
  CLI de punta a punta y no hace falta separar "proponer" de "firmar");
- desde el navegador, apretando "Firmar" en el popup (`POST
  /propuestas/{id}/firmar`).

`EmitirMandatoUseCase` hace, en orden:

1. Busca la propuesta **por id** contra `RepositorioPropuestas` — nunca
   acepta el objeto `PropuestaDeMandato` por parámetro. Si lo aceptara,
   confiar en un segundo proceso (el agente) para decirle su propio
   `monto_max`/`usos_max` sería exactamente el hueco que este diseño existe
   para cerrar.
2. Busca el carrito **por id** contra `RepositorioCarritos` y recalcula
   `carrito_hash` desde ahí — nunca desde un dato que la propuesta traiga
   por su cuenta, por el mismo motivo.
3. **Multi-comercio**: resuelve `RepositorioMedios.vinculado_con(titular_id,
   propuesta.comercio_id, ambiente)` — el medio de pago que Juan ya vinculó
   específicamente con `Dulcería La Golosina`, no "el último medio vivo que
   tenga" (que podría estar vinculado a otro comercio y que Wompi
   rechazaría al cobrar, con las credenciales equivocadas). Ver la sección
   6.
4. Arma el `Mandato`, con `llave_publica=firmante.llave_publica()` y
   `carrito_hash` incluidos dentro de la carga a firmar.
5. **Firma** con la llave privada del titular (`firmante.firma(mandato.canonico())`
   — ver la sección 3, la criptografía).
6. Lo guarda en `RepositorioMandatos` y deja constancia en la bitácora
   (`mandato_emitido`).

El resultado es un `Mandato` — ya firmado, inmutable desde ahí en más — con
`monto_max = 1.500 COP`, `usos_max = 1`, `comercio_id = com_a6066287f648`,
vigente 30 minutos.

### Paso 3 — El agente pide el cobro, el motor de pagos decide

Con el `mandato_id` en mano (se lo pasó la persona, nunca lo generó el
agente), el agente llama a su herramienta `pagar()`, que arma una
`Intencion` y la manda a `EjecutarIntencionUseCase`
(`usecase/ejecutar_intencion/ejecutar_intencion_use_case.py`). Ahí, en orden:

1. **Topes duros** — nunca se apagan, constantes en código (20.000 COP por
   transacción, 100.000 COP por día).
2. **Reserva atómica** — si no cabe en el cupo diario, ni se llega a evaluar
   el mandato.
3. **El mandato** — `Mandato.violaciones_contra(...)` recalcula la firma, el
   vencimiento, el comercio, el monto, el tope total, los usos, la
   categoría y el `carrito_hash`, y `model/mandato/politica.py:evaluar`
   traduce el resultado a un dictamen de tres desenlaces (no dos):

   | Decisión | Cuándo | Qué pasa |
   |---|---|---|
   | `PERMITIR` | Cabe en el mandato, sin nada raro | Se cobra |
   | `CONFIRMAR` | Cabe, pero huele raro (agota el mandato de una vez, pega contra el tope, es el último uso) | Se pausa y se le pregunta a un humano — nunca al agente |
   | `BLOQUEAR` | No cabe (cualquier violación real) | Se libera la reserva y no se cobra |

4. **El cobro** — resuelve la pasarela correcta con `SelectorDePasarela.
   para(mandato.comercio_id)` (multi-comercio: cada comercio real de Wompi
   tiene sus propias credenciales) y pide el cobro. Nunca bloquea esperando
   el desenlace final: si Wompi devuelve `PENDING` (típico de Nequi, que
   liquida de forma asíncrona), la reserva queda viva y el webhook
   (`ConciliarEventoUseCase`) la resuelve después, desde otro proceso.

Con un mandato cortado exacto al carrito (`monto_max` igual al total,
`usos_max=1`), casi siempre se disparan señales blandas de `CONFIRMAR` —
"agota el mandato de una sola vez" y "es el último uso" son casi
automáticas. Eso no es un error: es la consecuencia esperada de firmar un
mandato tan angosto, y `retomar()` (otro acto exclusivamente humano, nunca
del agente) es cómo se resuelve.

---

## 2. Dónde vive cada cosa

Cuatro repositorios, cada uno detrás de un puerto (`model/<agregado>/gateways/
repositorios.py`) con dos implementaciones intercambiables — en memoria
(pruebas, o `AGORA_PERSISTENCIA=memoria`) y SQLite
(`AGORA_PERSISTENCIA=sqlite`, cuatro tablas, SQL de mano, sin ORM):

| Repositorio | Qué guarda | Tabla SQLite | Por qué existe como repositorio y no como variable en memoria del proceso |
|---|---|---|---|
| `RepositorioCarritos` | El `Carrito` que `armar_carrito` produjo | `carrito` | Si "armar el carrito" (el chat) y "firmar" (la CLI, en otra terminal) son dos procesos distintos, el carrito tiene que sobrevivir entre los dos |
| `RepositorioPropuestas` | La `PropuestaDeMandato` sin firmar | `propuesta` | Mismo argumento, un nivel más adentro: sin esto, `EmitirMandatoUseCase` solo podía firmar una propuesta que le llegara por parámetro desde el MISMO proceso que la creó |
| `RepositorioMandatos` | El `Mandato` ya firmado | `mandato` | Sobrevive entre el proceso que firma y el que después paga o retoma |
| `RepositorioMedios` | Qué medios de pago (Nequi vía Wompi) tiene vivos cada titular, y con qué comercio los vinculó | `medio_de_pago` | Multi-comercio: `vinculado_con(titular_id, comercio_id, ambiente)` es lo que evita volver a pedir el enrolamiento cada vez que se compra en el mismo comercio (ver sección 6) |

Además, `RegistroDeEstados` (tabla `estado_intencion`) es lo que permite que
un `retomar()` corrido en OTRA terminal (siempre humano, nunca el agente)
le avise al chat original que la confirmación ya se resolvió — sin esto, el
chat se quedaría diciendo "esperando confirmación humana" para siempre.

Con `AGORA_PERSISTENCIA=sqlite` (recomendado fuera de las pruebas), todo
esto vive en un único archivo (`agora_datos/agora.db` por defecto,
`AGORA_SQLITE_PATH`) — el mismo que usa `LibroDeConsumo` para la reserva
atómica del cupo diario. Con `AGORA_PERSISTENCIA=memoria`, todo se pierde al
terminar el proceso — válido para pruebas o una demo de una sola terminal,
pero `ConfiguracionAgora` se niega a arrancar con `AGORA_PASARELA=wompi` +
`AGORA_AMBIENTE=produccion` + `AGORA_PERSISTENCIA=memoria`: contra dinero
real, perder el consumo acumulado al reiniciar permitiría reusar un mandato
agotado.

La llave de firma del titular (siguiente sección) vive aparte de estos
cuatro repositorios, en dos archivos sueltos:
`agora_datos/secretos/firma.sk`/`firma.pk`.

---

## 3. La criptografía detrás de la firma

### Qué se firma

`Mandato.canonico()` (`model/mandato/modelo.py`) serializa el
mandato — **sin la firma misma** — a JSON con claves ordenadas y sin
espacios, para que la misma carga produzca siempre los mismos bytes:

```python
def canonico(self) -> bytes:
    d = {
        "version": self.version,
        "mandato_id": self.mandato_id,
        "titular_id": self.titular_id,
        "medio": self.medio.to_json(),
        "comercio_id": self.comercio_id,
        "monto_max": self.monto_max.to_json(),
        "tope_total": self.tope_total.to_json(),
        "usos_max": self.usos_max,
        "expira_en": self.expira_en.isoformat(),
        "creado_en": self.creado_en.isoformat(),
        "categorias": sorted(self.categorias),
        "carrito_hash": self.carrito_hash,
        "llave_publica": self.llave_publica.hex(),
    }
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

Notas importantes de este diseño:

- **La versión va DENTRO de la carga.** Si no fuera así, alguien podría
  tomar una carga firmada con otro formato (sin `comercio_id` tipado ni
  `Dinero`) y hacerla pasar por la versión 2 sin romper la firma.
- **La llave pública del titular va DENTRO de la carga firmada**, no se
  pasa aparte al verificar. Eso es lo que impide que alguien tome un
  mandato firmado y lo "reverifique" contra una llave pública distinta de
  la que el propio titular declaró al firmar.
- **El `carrito_hash` va dentro de la carga** — el "Cart Mandate" de AP2:
  si el carrito cambia después de firmado, `carrito_hash` ya no calza y
  `violaciones_contra` levanta `carrito_alterado`.

### Cómo se firma y se verifica

Dos interfaces separadas y deliberadamente distintas (`model/<agregado>/gateways/
firma.py`, `model/mandato/modelo.py`):

```python
class Firmante(Protocol):        # model/mandato/gateways/firma.py -- lo usa EmitirMandatoUseCase
    def firma(self, carga: bytes) -> bytes: ...
    def llave_publica(self) -> bytes: ...

class Verificador(Protocol):     # model/mandato/modelo.py -- lo usa violaciones_contra
    def verifica(self, firma: bytes, carga: bytes, llave_publica: bytes) -> bool: ...
```

Separadas porque **firmar exige la llave privada; verificar solo necesita
la pública que ya viaja dentro del propio mandato**. Juntarlas en una sola
interfaz obligaría a `EjecutarIntencionUseCase` (que solo verifica) a depender de
una interfaz que también sabe firmar — más superficie de la que ese caso de
uso necesita, y una forma más de que un descuido le dé acceso a firmar a
quien solo debería poder comprobar una firma ajena.

La implementación real de las dos es **Ed25519**
(`driven_adapters/firma_ed25519/firma_ed25519.py`, usando el módulo
`cryptography` de Python — el único lugar de todo `agora/` que importa una
librería criptográfica):

```python
class VerificadorEd25519:
    def verifica(self, firma: bytes, carga: bytes, llave_publica: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(llave_publica).verify(firma, carga)
            return True
        except (InvalidSignature, ValueError):
            return False

class FirmanteEd25519:
    def __init__(self, llave_privada: Ed25519PrivateKey) -> None:
        self._sk = llave_privada
    def firma(self, carga: bytes) -> bytes:
        return self._sk.sign(carga)
    def llave_publica(self) -> bytes:
        return self._sk.public_key().public_bytes(...)
```

`EjecutarIntencionUseCase` recalcula `mandato.canonico()` y llama a `verifica(...)`
en CADA cobro y en CADA `retomar()` — no confía en que el mandato "ya se
validó una vez al firmarlo". Si un solo byte de la carga cambió después de
firmada (por ejemplo, alguien manipulara el registro donde se guardó), la
verificación falla y `violaciones_contra` devuelve `firma_invalida`.

### Dónde vive la llave privada — la simplificación consciente de esta PoC

Esto es importante para no llevarse una idea equivocada: **en esta demo, no
hay una billetera de navegador ni una llave que viva literalmente en el
dispositivo de Juan.** La llave ed25519 se genera una sola vez y se guarda
sin cifrar en disco, del lado del proceso que corre `agora/`
(`agora_datos/secretos/firma.sk`/`firma.pk`, en `.gitignore`) — simulando
"la llave del titular". `app_service/config/contenedor.py` la carga (o la
genera, si no existe) al armar el `Contenedor`; ningún archivo de
`usecase/agente/` la toca.

Lo que SÍ es real y verificable es la separación de procesos y de código: el
paso de firma requiere una acción explícita de la persona (correr `firmar`,
o apretar el botón del popup), y solo el composition root
(`app_service/config/contenedor.py`) construye un `Firmante` real — `usecase/agente/`
nunca puede alcanzarlo. Lo que esta PoC demuestra es esa frontera
estructural, no un modelo de custodia de llaves apto para producción — eso
queda documentado como alcance, no como descuido.

---

## 4. Cómo firma la persona, en la práctica

**Por terminal** (`entry_points/cli/`):

```bash
# Caso 1: la misma persona arma el carrito y firma, en un solo paso
python -m agora cli emitir <comercio_id> <titular> --item <producto_id>:1

# Caso 2: el agente ya armó una propuesta en el chat (otro proceso);
# la persona la firma en su propia terminal
python -m agora cli firmar <propuesta_id> <titular>
```

**Por navegador** (`entry_points/api_rest/`, `chat.html`): cuando el agente arma un
carrito, un evento SSE (`propuesta_pendiente`) abre un popup con el
`comercio_id`, los ítems y el total — la persona ve exactamente qué se le
pide autorizar antes de apretar "Firmar". Ese clic dispara
`POST /propuestas/{propuesta_id}/firmar`, que llama al mismo
`EmitirMandatoUseCase` que usa la CLI — no hay dos caminos de firma con reglas
distintas, solo dos formas de disparar el mismo caso de uso.

En ambos casos, la persona ve — antes de firmar — el comercio, los ítems, el
monto total y la vigencia. Nunca firma "lo que el agente le mostró en
texto": firma lo que el propio backend recalculó a partir del carrito
guardado, con el mismo `carrito_hash` que va a viajar dentro del mandato.

---

## 5. Por qué el agente NUNCA puede firmar

No es una regla de negocio ni una instrucción en el prompt del modelo —
sería una promesa, no un argumento. Es una propiedad estructural del
código, verificada en tres capas independientes:

1. **El agente no tiene la llave.** `usecase/agente/` nunca importa
   `puertos.firma` ni recibe un `Firmante` por constructor — solo
   `app_service/config/contenedor.py` construye uno, a partir de la llave en
   disco. No es que el agente "no deba" firmar: no tiene con qué.

2. **`EmitirMandatoUseCase` no está en su catálogo de herramientas.**
   `usecase/agente/herramientas.py` declara explícitamente qué puede llamar
   el modelo (`CATALOGO_DE_HERRAMIENTAS`) y qué palabras jamás pueden
   aparecer en el nombre de una herramienta (`PROHIBIDAS`):

   ```python
   CATALOGO_DE_HERRAMIENTAS = (
       "buscar_comercios", "buscar_productos", "ver_producto",
       "armar_carrito",     # devuelve una PropuestaDeMandato SIN FIRMAR
       "pagar",             # exige un mandato_id que firmo un humano
       "consultar_estado",
   )

   PROHIBIDAS = (
       "firmar", "enrolar", "revocar",
       "medio_de_pago", "payment_source", "llave", "secreto", "credencial",
   )
   ```

   `validar_catalogo(...)` corre **al arrancar el proceso**, no en una
   prueba lejana: si alguien agrega una herramienta con un nombre prohibido
   o fuera del catálogo autorizado, la app ni siquiera levanta.

3. **Una prueba rompe el build si alguien cruza la frontera de todos
   modos.** `tests/arquitectura/test_fronteras.py` no lee documentación ni confía en la
   disciplina de quien escribe código nuevo: lee el AST (árbol de sintaxis)
   de cada módulo de `usecase/agente/` y falla si encuentra un `import` hacia
   `driven_adapters/` o `app_service/config/` — las únicas capas desde donde se puede
   llegar a una pasarela de pagos o a una llave de firma real.

`pagar()` SÍ está en el catálogo del agente, y es deliberado: quitarla
haría que la PoC dejara de medir lo que quiere medir. El punto no es que el
agente no actúe — es que actúe **solo dentro de un límite que otra persona
ya firmó**, nunca fuera de él y nunca decidiendo el límite él mismo.

---

## 6. Multi-comercio: la vinculación entre el medio de pago y el comercio

Desde que `agora/` soporta varios comercios reales de Wompi en el mismo
proceso (1 de septiembre de 2026, ver `docs/utils/viabilidad-multi-comercio-wompi.md`),
"tener un medio de pago vivo" dejó de ser suficiente para firmar un
mandato — importa **con qué comercio** se vinculó ese medio:

- Un `payment_source_id` de Wompi queda atado al comercio (a la cuenta) que
  lo creó — no es portable a otro comercio, aunque los dos usen Wompi.
- `RepositorioMedios.guardar(ref, titular_id, comercio_id)` registra esa
  relación en el momento del enrolamiento (`usecase/enrolar_medio/enrolar_medio_use_case.py`).
- `RepositorioMedios.vinculado_con(titular_id, comercio_id, ambiente)` es lo
  que `EmitirMandatoUseCase` (paso 2 de la sección 1) consulta antes de firmar. Si
  no encuentra nada, distingue dos errores distintos, para que la persona
  (o el agente, contándoselo a la persona) sepa exactamente qué falta:

  | Error | Cuándo | Qué falta |
  |---|---|---|
  | `SinMedioDePagoVivo` | El titular nunca enroló nada, en ningún comercio | Enrolar por primera vez |
  | `SinMedioVinculadoAlComercio` | El titular ya enroló un medio, pero con OTRO comercio | Un enrolamiento más, dirigido a ESTE comercio |

Una vez vinculado un comercio, `vinculado_con` sigue encontrándolo en
compras futuras — no se vuelve a pedir el enrolamiento para ese mismo
comercio. Es lo que hace posible que Juan compre en `Dulcería La Golosina`
sin re-enrolar cada vez, y que la primera compra en `Papelería El Lápiz
Feliz` sí le pida vincular ese comercio puntual, aunque ya tenga un Nequi
enrolado en el otro.

**Deuda técnica consciente, documentada a propósito**: esta correspondencia
medio↔comercio la garantiza `EmitirMandatoUseCase` en el momento de firmar (nunca
firma con un medio que `vinculado_con` no haya asociado a ese comercio),
pero **no está verificada criptográficamente** dentro del mandato mismo ni
en `EjecutarIntencionUseCase` al cobrar — un bug en otra parte del sistema que
armara un `Mandato` a mano con un medio de otro comercio no lo detectaría
en ese punto. Se evaluaron dos caminos (`docs/utils/viabilidad-multi-comercio-
wompi.md`, sección "Amarre medio → comercio"): esta opción, más liviana, y
meter `comercio_id` dentro de `MedioDePagoRef` con una nueva versión de
la carga firmada (más robusto, pero exigiría conservar el verificador actual
para los mandatos ya emitidos). Se eligió la liviana para
esta iteración porque `EmitirMandatoUseCase` es el único punto del sistema que
construye un `Mandato` de verdad.

---

## 7. Qué protege el mandato, y qué no

Sigue siendo la
aclaración más importante del documento:

**Protege** contra un comercio que cobra distinto de lo pactado, y contra
un agente (manipulado o con un bug) que intenta gastar más de lo que la
persona autorizó — en monto, en cantidad de usos, en el tiempo, en el
comercio, o en la categoría.

**No protege** contra un agente al que convencieron de pedir *otra cosa*
dentro del mismo límite. Si la intención cabe dentro del mandato, el
mandato la deja pasar — para eso se firmó. Ese caso (comprar el producto
equivocado, a un comercio ya autorizado, dentro del monto autorizado) no lo
atrapa la firma: lo atrapan las señales blandas de `politica.CONFIRMAR`
(sección 1, paso 3) o un motor de riesgo aparte — nunca la criptografía por
sí sola.
