# Viabilidad: conectar el agente a varios comercios reales de Wompi

**Estado: implementado (1 de septiembre de 2026).** Este documento arrancó
como un analisis de viabilidad -- ver la nota original mas abajo -- y
Juan pidio despues, en la misma fecha, que se implementara. Lo que sigue en
el resto del archivo es la evaluacion tal como se escribio antes de tocar
codigo; para lo que efectivamente se construyo:

- `agora/adaptadores/pasarelas/registro.py` (`RegistroDePasarelas`): implementa
  el `SelectorDePasarela` nuevo (`puertos/pasarela.py`) que este documento
  proponia -- resuelve por `comercio_id`, con fallback a una unica pasarela
  cuando `AGORA_PASARELA=simulada`.
- `agora/composicion/configuracion.py`: `ConfiguracionAgora.wompi` paso de
  una sola `ConfiguracionWompi` a un `dict[comercio_id, ConfiguracionWompi]`,
  leido de un registro JSON (`AGORA_WOMPI_COMERCIOS`, default
  `agora_datos/secretos/comercios_wompi.json`) en vez de variables `WOMPI_*`
  sueltas -- el puente remoto no deja escribir `.env` con una entrada por
  comercio. Ver `docs/variables-de-entorno.md`.
- `agora/entradas/webhooks/wompi.py`: la ruta quedo en
  `/pagos/wompi/transacciones/{comercio_id}`, exactamente la opcion que este
  documento recomendaba en "Puerto 8001 y el webhook con varios comercios"
  -- un solo puerto, un solo tunel, un segmento de URL por comercio.
- **Decision que este documento dejaba abierta** ("el amarre medio ->
  comercio"): se resolvio por la opcion mas liviana -- `RepositorioMedios`
  ahora guarda `comercio_id` junto al medio (`vinculado_con`/`comercio_de`),
  en vez de extender `MedioDePagoRef` o el mandato (v3). `EmitirMandato`
  exige que el medio este vinculado con el comercio de la propuesta antes de
  firmar; si el titular tiene un medio vivo pero de OTRO comercio, levanta
  `SinMedioVinculadoAlComercio` en vez de `SinMedioDePagoVivo` -- la
  funcionalidad nueva que Juan pidio ("verificar si ya se ha vinculado el
  comercio con el medio seleccionado").
- El catalogo semilla se regenero con 2 comercios reales (`Dulceria La
  Golosina`, `Papeleria El Lapiz Feliz`), 12 productos cada uno, todos entre
  1.500 y 2.000 COP -- reemplaza el placeholder (TecnoX/LibroSur) que
  describe `docs/catalogo-simulado-deepseek.md`.
- 478 pruebas en verde, incluida `test_fronteras.py`.

---

Evaluación pedida por Juan el 1 de septiembre de 2026: qué tan complicado
sería que el agente se conecte a distintos comercios reales de Wompi (por
ejemplo 3), guardando por cada uno sus credenciales
(`WOMPI_PUBLIC_KEY`/`WOMPI_PRIVATE_KEY`/`WOMPI_INTEGRITY_SECRET`/
`WOMPI_EVENTS_SECRET`) y la URL de webhook que se registra en el dashboard
de ese comercio, y eligiendo el comercio correcto según la intención de
compra del usuario. Es solo un análisis — no se implementó nada de esto.

## Veredicto

Viable, complejidad media. La arquitectura hexagonal con un composition
root único (`agora/composicion/contenedor.py`) ya está preparada para
esto, y `ComercioId` ya es un concepto de dominio de punta a punta. El
hueco no está en el dominio ni en el agente — está enteramente en
`composicion/` y en cómo los casos de uso reciben la pasarela de pagos.

## Lo que ya está resuelto, sin tocar nada

`Producto`, `Carrito`, `Intencion` y `Mandato` ya cargan `comercio_id`.
`NavegarCatalogo` ya impide carritos mixtos ("un carrito es de un solo
comercio", `agora/aplicacion/navegar_catalogo.py`). `Mandato.
violaciones_contra` (`agora/dominio/mandato/modelo.py`) ya valida
`comercio_no_autorizado` comparando `intencion.comercio_id` contra
`mandato.comercio_id`, y ese id viaja dentro de la carga firmada del
mandato desde la v2 (`Mandato.canonico()`). En otras palabras: el agente,
al navegar el catálogo y armar un carrito, ya declara con qué comercio
está tratando de comprar, y esa decisión ya queda firmada. No hace falta
enseñarle al agente a "elegir" comercio — eso ya lo hace. Hoy los tres
comercios simulados existen en `RepositorioCatalogoSemilla`
(`Comercio.simulado: bool = True`); lo que falta es que ese `comercio_id`
resuelva a credenciales reales de Wompi en vez de a la pasarela simulada.

## El hueco real: una sola pasarela por proceso

`Contenedor.construir()` (`agora/composicion/contenedor.py`) arma
exactamente **una** `PasarelaDePagos` por proceso: o un
`AdaptadorSimulado`, o un `AdaptadorWompi` con **una** `ConfiguracionWompi`
(un solo juego de credenciales, leídas una vez de `os.environ` en
`agora/composicion/configuracion.py`). Esa única `pasarela` se inyecta fija
en el constructor de `EjecutarIntencion`, `ConciliarEvento`,
`EnrolarMedio` (y sus tres pasos sueltos `IniciarEnrolamiento`/
`ConsultarEnrolamiento`/`ConfirmarEnrolamiento`) y `RevocarMedio`.

Cambios concretos, en orden de dependencia:

1. **Configuración.** `ConfiguracionAgora.wompi` pasa de ser un
   `ConfiguracionWompi | None` a algo indexado por `comercio_id` —
   probablemente un archivo bajo `agora_datos/secretos/` (ya gitignored,
   siguiendo la convención del repo de que todo lo sensible vive ahí), no
   variables `.env` planas que no escalan a N comercios. `leer_configuracion`
   tiene que parsear N juegos de credenciales en vez de uno.

2. **Amarre medio → comercio (esto es un hallazgo, no solo una tarea).**
   Un `payment_source_id` de Wompi está atado al comercio (a la llave
   pública) que lo creó — no es portable entre comercios aunque los tres
   usen Wompi. Hoy `MedioDePagoRef` (`agora/dominio/pago/modelo.py`) NO
   carga `comercio_id`, y `RepositorioMedios.guardar(ref, titular_id)`
   tampoco lo registra. Dos consecuencias:
   - Hay que enrolar el medio de pago (Nequi) **una vez por cada uno de
     los tres comercios** — no existe "un solo medio" que sirva para los
     tres, así funciona Wompi hoy.
   - Nada en el código verifica hoy que `mandato.medio` de verdad
     pertenezca al `comercio_id` que ese mismo mandato autoriza. El
     mandato solo compara `intencion.comercio_id` contra
     `mandato.comercio_id`, nunca contra la procedencia real del medio.
     Con un solo comercio esa distinción no importaba; con tres, es
     exactamente el tipo de descuido que esta PoC existe para exponer.

   Dos caminos posibles, sin decidir todavía:
   - Guardar la relación medio→comercio como metadata no firmada en
     `RepositorioMedios` (liviano, rápido de implementar).
   - Meter `comercio_id` dentro de `MedioDePagoRef` (más robusto porque
     viaja también dentro de la carga firmada del mandato, pero implica
     versionar el mandato a v3 y conservar el verificador v2 — mismo
     patrón que ya usaron de v1 a v2).

3. **`SelectorDePasarela`** (puerto nuevo) en `composicion/`: resuelve
   `comercio_id -> PasarelaDePagos`, construyendo internamente un
   `AdaptadorWompi` por cada juego de credenciales. Es aditivo: cada
   `AdaptadorWompi` ya recibe su config por constructor (decisión
   explícita de la etapa 2, justo para poder tener dos configuraciones en
   el mismo proceso). En `EjecutarIntencion._cobrar` el cambio es limpio
   porque `mandato.comercio_id` ya está disponible ahí — solo hace falta
   seleccionar la pasarela con ese id antes de llamar `.cobrar()`.

4. **Los casos de uso que hoy reciben `pasarela` fija por constructor**
   pasan a recibir el selector: `EjecutarIntencion`, `ConciliarEvento`,
   `EnrolarMedio` + sus 3 pasos, `RevocarMedio`.

5. **Guardarraíl existente.** El `__post_init__` de `ConfiguracionAgora`
   que hoy bloquea la combinación `wompi + producción + memoria`
   (`agora/composicion/configuracion.py`) tiene que aplicar por comercio,
   no una sola vez de forma global.

6. **Pruebas.** `tests/test_fronteras.py` y cualquier prueba que hoy arma
   un `Contenedor`/`AdaptadorWompi` con una sola config van a necesitar el
   nuevo shape.

Lo que NO se toca: el núcleo del mandato, la política de riesgo
(`PERMITIR`/`CONFIRMAR`/`BLOQUEAR`), el catálogo.

## Puerto 8001 y el webhook con varios comercios (decisión ya tomada)

Cada comercio real tiene su propio `WOMPI_EVENTS_SECRET` y configura, en
**su propio dashboard de Wompi**, a qué URL le llegan sus eventos. Wompi no
manda ningún header confiable de "qué comercio soy" antes de que se
verifique el checksum con el secreto correcto — la única forma de saber
qué secreto usar es por **cuál URL golpearon**.

**Decisión: un solo puerto (8001), un solo túnel (ngrok/cloudflared),
rutas distintas por comercio** — por ejemplo
`/pagos/wompi/transacciones/{comercio_id}`. Cada uno de los tres
dashboards de Wompi apunta su webhook a su propia ruta bajo la misma URL
pública. Esto es consistente con el ADR-1 del proyecto ("un proceso, no un
servicio aparte", ver `docs/arquitectura-v2.md`) y no multiplica los
túneles ni los puertos expuestos.

Alternativa descartada: un puerto por comercio (8001, 8011, 8021...) — casi
cero cambio de código (parametrizar `scripts/servir_webhook_wompi.py`),
pero triplica la superficie expuesta y se aparta del ADR-1 sin necesidad
real.

Cambio de código que implica: `agora/entradas/webhooks/wompi.py:crear_app`
deja de recibir un `ConciliarEvento` único y pasa a recibir el selector (o
un dict `comercio_id -> ConciliarEvento`); la ruta usa el segmento de la
URL para elegir con qué secreto validar antes de procesar.

## Estado

Solo evaluación — nada de esto está implementado todavía. Resumen también
guardado en la memoria del proyecto (`viabilidad-multi-comercio-wompi.md`
en memoria) para que quede disponible entre sesiones.
