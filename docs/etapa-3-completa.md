# Etapa 3: SQLite con reserva/confirmación atómica real

**25 de agosto de 2026.** `docs/arquitectura-v2.md`, plan de migración, fila 3:
"SQLite con reserva/confirmación atómica, migrando `boveda/secretos/
estado.json`". Detalle de ADR-3 (por qué SQLite sin ORM) en
`docs/arquitectura-v2.md`. `boveda/` no se tocó — sigue siendo el código que
mueve dinero real; `agora/` sigue sin invocarse desde fuera de sus propias
pruebas.

## Qué se construyó

| Paquete | Qué hace |
|---|---|
| `adaptadores/persistencia/sqlite/esquema.py` | El DDL: cuatro tablas (`mandato`, `consumo`, `reserva`, `gastado_dia`) más `medio_de_pago`. `asegurar()` es idempotente y se llama en cada apertura de conexión |
| `adaptadores/persistencia/sqlite/conexion.py` | `abrir_conexion`: una conexión nueva por llamada (no compartida entre hilos), WAL + `busy_timeout` + `isolation_level=None` para control manual de transacciones |
| `adaptadores/persistencia/sqlite/serializacion.py` | `Mandato` ⇄ fila de SQLite, centralizado para que el repositorio no repita las 19 columnas en cada método |
| `adaptadores/persistencia/sqlite/libro_consumo.py` | `LibroDeConsumoSQLite`: la reserva atómica de verdad. `reservar` es una sola transacción `BEGIN IMMEDIATE` — toma el lock de escritura del archivo *antes* de leer `gastado_dia`, así que dos procesos que compiten por el último tramo del tope diario no pueden leer el mismo valor y escribir cada uno el suyo |
| `adaptadores/persistencia/sqlite/repositorio_mandatos.py` | `RepositorioMandatosSQLite`: misma guarda de ambiente tipada que la versión en memoria, pero sobrevive un reinicio |
| `adaptadores/persistencia/sqlite/repositorio_medios.py` | `RepositorioMediosSQLite`: equivalente de `boveda/secretos/fuentes.json`, con el ambiente como parte de la llave primaria en vez de una clave de nivel superior en el JSON |
| `composicion/configuracion.py` | `AGORA_PERSISTENCIA` (`memoria` \| `sqlite`, default `memoria`) y `AGORA_SQLITE_PATH` (default `agora_datos/agora.db`). Guardarraíl nuevo: `AGORA_PASARELA=wompi` + `AGORA_AMBIENTE=produccion` + `AGORA_PERSISTENCIA=memoria` es una `ConfiguracionInvalida` — esa combinación es exactamente la que la etapa 2 dejó documentada como "no usar contra dinero real" |
| `composicion/contenedor.py` | `construir()` ahora arma el trío memoria o SQLite según `config.persistencia` |
| `scripts/migrar_fuentes_a_sqlite.py` | Migra `boveda/secretos/fuentes.json` a `medio_de_pago`. Dry-run por defecto, `--aplicar` para escribir de verdad, backup automático del destino si ya existe, `--titular` obligatorio (`fuentes.json` nunca guardó a nombre de quién está un medio) |

252 pruebas en verde (190 de antes + 62 nuevas), incluida `test_fronteras.py`
contra el árbol completo: ningún adaptador nuevo cruza una frontera
prohibida. La prueba de concurrencia (`test_libro_consumo_sqlite.py::
test_reserva_atomica_entre_conexiones_sqlite_independientes`) no comparte un
`threading.Lock` de Python entre hilos como hacía la de memoria — cada hilo
abre su propia conexión SQLite, que es lo más cerca que una prueba de un solo
proceso puede llegar a simular dos procesos reales compitiendo por el mismo
archivo. Verificado corriendo la suite completa (pytest + pyflakes) en un
entorno espejo antes de escribir al disco de Juan.

## Decisión importante: los mandatos v1 NO se migran

Antes de implementar esta etapa surgieron dos preguntas sin respuesta obvia
en `docs/arquitectura-v2.md`, y se le preguntaron a Juan directamente:

1. **¿Correr la migración contra los datos reales en esta sesión, o solo
   construir la herramienta?** Respuesta: **construir, no ejecutar**.
   `scripts/migrar_fuentes_a_sqlite.py` existe y está probado contra un
   fixture, pero nunca se corrió contra `boveda/secretos/fuentes.json` real.
   Juan decide cuándo, corriéndolo él mismo.

2. **¿Qué hacer con los mandatos v1 de `boveda/secretos/estado.json`?**
   Respuesta: **omitirlos por completo**. Se quedan archivados tal cual en
   `boveda/`; de ahora en adelante `agora/` solo trabaja con mandatos v2. No
   hay ninguna tabla "histórica" de mandatos v1 en SQLite, ni siquiera de solo
   lectura. `scripts/migrar_fuentes_a_sqlite.py` no lee `estado.json` en
   absoluto — solo migra medios de pago (`fuentes.json`), nunca mandatos.

   Esto además resuelve un problema que `arquitectura-v2.md` no menciona:
   reescribir el payload canónico de un mandato v1 para que encaje en el
   esquema v2 invalidaría su firma ed25519 original (`dominio/mandato/
   compat.py` explica por qué la conversión v1→v2 no es posible sin pedirle
   al titular que autorice de nuevo). "Omitir" no es solo la decisión más
   simple — era, además, la única sin una firma inválida al final del
   camino.

## Otra decisión: `ambiente` vive en la fila de `reserva`

El adaptador en memoria (etapa 2) guarda la correspondencia
reserva → ambiente en un `dict` privado del proceso, porque `Reserva` (el
objeto que ve `EjecutarIntencion`) no lleva ese dato. En SQLite esa solución
no alcanza — necesita sobrevivir un reinicio — así que `ambiente` es una
columna real de la tabla `reserva`. Estrictamente mejor que el dict en
memoria, no un rodeo: no depende de estado del proceso y `confirmar`/
`liberar` pueden actualizar `gastado_dia` sin reconstruir nada.

## Qué no se tocó a propósito

- **Los mandatos v1** — ver arriba.
- **La migración real** — la herramienta existe, no se corrió.
- **`aplicacion/ejecutar_intencion.py`** — no cambió. `CONFIRMAR` se sigue
  comportando como `BLOQUEAR`; eso sigue pendiente para las etapas 4-5.
- **`RepositorioMediosSQLite` no tiene un caso de uso que lo llame** —
  igual que en la etapa 2, nada de `agora/` lo necesita todavía
  (`aplicacion/enrolar_medio.py` es etapa 5). Se probó de todas formas,
  porque es el destino directo de la migración.

## Pendiente inmediato

1. Confirmar que los archivos nuevos están en disco (llegaron por el puente
   de archivos, no por `git`).
2. `git add` + commit desde tu terminal — el puente no puede correr `git`
   (ver [[entorno-y-limitaciones]] en la memoria del proyecto).
3. Cuando quieras migrar `fuentes.json` de verdad: `python
   scripts/migrar_fuentes_a_sqlite.py --titular <tu_id>` primero sin
   `--aplicar` para ver el plan, y con `--aplicar` cuando confirmes que se ve
   bien.
4. **Etapa 4:** lo que sigue en `docs/arquitectura-v2.md` — conciliación por
   webhook real y el mecanismo para retomar `CONFIRMAR` tras preguntarle al
   humano, en vez del `BLOQUEAR` de hoy.
