# Etapa 2: puertos con implementación, y la pasarela simulada

**25 de agosto de 2026.** `docs/arquitectura-v2.md`, plan de migración, fila 2:
"Definir puertos y partir `Boveda`". `Boveda.ejecutar` (`boveda/nucleo.py:337-408`)
ya estaba partido en `aplicacion/ejecutar_intencion.py` desde antes de esta
sesión — lo que faltaba eran los adaptadores que le dan cuerpo a los puertos, y
esta es la primera etapa que efectivamente toca el código que mueve dinero
(aunque `boveda/` no se tocó: sigue siendo el camino real, ver más abajo).

No se tocó ni una línea de `boveda/`. Sigue siendo el código que ya hizo una
transferencia real; `agora/` es la casa nueva y todavía nada la invoca desde
fuera de sus propias pruebas.

## Qué se construyó

| Paquete | Qué hace |
|---|---|
| `adaptadores/pasarelas/wompi/` | `ClienteWompi` (HTTP puro) + `AdaptadorWompi` (traduce a los tipos del dominio). Lo que queda de `boveda/nucleo.py:ClienteWompi` sin los topes, el mandato ni la persistencia — eso ya vive en `aplicacion/` y en los otros adaptadores |
| `adaptadores/pasarelas/simulada/` | `AdaptadorSimulado`: los cuatro desenlaces (aprobado, declinado, declinado por antifraude, pendiente) elegidos por un `GuionSimulado` inyectable. La heurística por defecto usa el correo del pagador — un dominio reservado por la RFC 2606 declina por antifraude, reproduciendo la corrida real de `docs/hallazgo-afe.md` |
| `adaptadores/persistencia/memoria/` | `LibroDeConsumoEnMemoria` (reserva atómica con lock, corrige la condición de carrera del hallazgo 2 de `docs/analisis-codigo.md`), `RepositorioMandatosEnMemoria` (la guarda de ambiente tipada), `RepositorioMediosEnMemoria` |
| `adaptadores/sistema/` | `RelojDelSistema`, `GeneradorIdsUuid`, `VerificadorEd25519` (promovido desde el test double que vivía en `tests/test_dominio.py`), `BitacoraJsonl` |
| `composicion/` | `configuracion.py` (el único lugar de `agora/` que lee `os.environ`) y `contenedor.py` (arma `EjecutarIntencion` con los adaptadores según la configuración) |

190 pruebas en verde (125 de antes + las nuevas de esta etapa), incluida
`test_fronteras.py` corriendo contra el árbol completo de `agora/` — ningún
adaptador nuevo cruza una frontera prohibida.

## Dos correcciones al esqueleto de la etapa 1

Encontradas al implementar los puertos por primera vez — antes de esta etapa
nadie los había implementado, así que era el momento correcto para
corregirlas:

1. **`LibroDeConsumo.reservar` no recibía `intencion_id`**, pero `Reserva` lo
   exige como campo. Se agregó el parámetro al puerto
   (`puertos/repositorios.py`) y a su único llamador
   (`aplicacion/ejecutar_intencion.py`). Sin esto, ninguna implementación
   real del puerto podía poblar ese campo.
2. **`Proveedor` solo tenía `WOMPI`.** La pasarela simulada necesita su
   propio valor: conviven en el mismo proceso, y un `MedioDePagoRef` no puede
   fingir que es de otro proveedor. Se agregó `Proveedor.SIMULADA`
   (`dominio/pago/modelo.py`) — cambio aditivo, no rompe nada firmado.

## Una decisión de diseño que vale explicar

**La persistencia sigue en memoria, incluso para la pasarela Wompi real.**
`composicion/contenedor.py` puede armar `EjecutarIntencion` con
`AdaptadorWompi`, pero `LibroDeConsumoEnMemoria` pierde todo el consumo
acumulado si el proceso se reinicia — un mandato que se creía agotado vuelve
a estar fresco. Eso es aceptable para pruebas y para la pasarela simulada; **no
lo es contra dinero real en `produccion`**. Migrar `boveda/secretos/
estado.json` a SQLite con reserva/confirmación atómica es la etapa 3, tal
como estaba planeado, y no se adelantó aquí para no mezclar "partir `Boveda`"
con "migrar datos reales" en el mismo cambio.

## Qué no se tocó a propósito

- **`aplicacion/ejecutar_intencion.py`**: la lógica de `EjecutarIntencion` no
  cambió (salvo la línea que pasa `intencion_id` a `reservar`). Notablemente,
  hoy `CONFIRMAR` se comporta igual que `BLOQUEAR` (se detiene, libera la
  reserva): el mecanismo para retomar tras preguntarle al humano no existe
  todavía — es trabajo de las etapas 4-5 (webhook vivo + agente). Documentado
  con una prueba dedicada (`tests/test_ejecutar_intencion.py::
  test_confirmar_tambien_detiene_y_libera_pero_no_es_un_bloqueo`).
- **`enrolar_medio` como caso de uso**: los métodos de enrolamiento del
  puerto (`preparar_medio`, `confirmar_medio`, etc.) están implementados en
  ambos adaptadores y probados, pero no existe todavía un
  `aplicacion/enrolar_medio.py` que los orqueste — eso encaja mejor en la
  etapa 5 junto con el resto de `agente/` y `entradas/`.
- **`wompi_lab/lab.py`**: sigue en el repo. `AdaptadorWompi` lo reemplaza
  funcionalmente, pero borrarlo es limpieza (`docs/mapa-del-proyecto.md` ya lo
  documentaba como "se va sola en su etapa 2") y no se hizo en esta pasada
  para no mezclar construcción con borrado; queda para cuando se corra
  `scripts/limpiar.ps1`.

## Pendiente inmediato

1. Confirmar que los archivos nuevos están en disco (llegaron por el puente
   de archivos, no por `git`).
2. `git add` + commit desde tu terminal — el puente no puede correr `git`
   (ver [[entorno-y-limitaciones]] en la memoria del proyecto).
3. Etapa 3: SQLite con reserva/confirmación real, migrando
   `boveda/secretos/estado.json`. Es la primera que toca datos reales; con
   190 pruebas y la equivalencia v1 probada, el riesgo sigue acotado.
