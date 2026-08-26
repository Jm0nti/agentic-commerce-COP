"""El DDL. Cuatro tablas, tal como lo dice `docs/arquitectura-v2.md` (ADR-3):
"Los repositorios son cuatro tablas. SQLAlchemy agrega mas concepto del que
quita a esta escala." Sin ORM: SQL de verdad, a proposito.

`asegurar()` es idempotente (`CREATE TABLE IF NOT EXISTS`) y se llama desde
`conexion.abrir_conexion()` en cada apertura -- barato, y evita que el orden
en que se construyen los repositorios importe.
"""

from __future__ import annotations

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS mandato (
    mandato_id          TEXT PRIMARY KEY,
    ambiente             TEXT NOT NULL,
    titular_id            TEXT NOT NULL,
    medio_proveedor       TEXT NOT NULL,
    medio_ambiente        TEXT NOT NULL,
    medio_id_externo      TEXT NOT NULL,
    comercio_id           TEXT NOT NULL,
    monto_max_centavos    INTEGER NOT NULL,
    monto_max_moneda      TEXT NOT NULL,
    tope_total_centavos   INTEGER NOT NULL,
    tope_total_moneda     TEXT NOT NULL,
    usos_max              INTEGER NOT NULL,
    expira_en             TEXT NOT NULL,
    creado_en             TEXT NOT NULL,
    llave_publica         BLOB NOT NULL,
    categorias            TEXT NOT NULL,
    carrito_hash          TEXT,
    version                INTEGER NOT NULL,
    firma                  BLOB NOT NULL
);

-- Cuanto se ha usado de cada mandato. Separado de `mandato` a proposito
-- (dominio/mandato/modelo.py:Consumo): el mandato es inmutable y firmado, el
-- consumo cambia con cada cobro confirmado.
CREATE TABLE IF NOT EXISTS consumo (
    mandato_id            TEXT PRIMARY KEY,
    usos                   INTEGER NOT NULL DEFAULT 0,
    acumulado_centavos     INTEGER NOT NULL DEFAULT 0,
    acumulado_moneda       TEXT NOT NULL DEFAULT 'COP'
);

-- Reserva -> cobra -> confirma o libera (puertos/repositorios.py:LibroDeConsumo).
-- `ambiente` vive en la fila (y no solo en el objeto `Mandato` de quien
-- reservo) para que `confirmar`/`liberar` puedan actualizar `gastado_dia` sin
-- depender de estado en memoria del proceso -- lo que hace atomica y segura
-- entre reinicios la reserva, a diferencia del adaptador en memoria (que
-- guarda esa correspondencia en un `dict` que se pierde con el proceso).
CREATE TABLE IF NOT EXISTS reserva (
    reserva_id             TEXT PRIMARY KEY,
    intencion_id           TEXT NOT NULL,
    mandato_id             TEXT NOT NULL,
    ambiente                TEXT NOT NULL,
    monto_centavos          INTEGER NOT NULL,
    monto_moneda            TEXT NOT NULL,
    dia                      TEXT NOT NULL,
    estado                   TEXT NOT NULL CHECK (estado IN ('pendiente', 'confirmada', 'liberada')),
    creada_en                TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reserva_estado ON reserva (estado);

-- El tope duro diario es del ambiente, no de un mandato (`nucleo.py:286`,
-- `docs/analisis-codigo.md` hallazgo 13: "gastado_dia_cop compartido entre
-- modos"). Se actualiza en la MISMA transaccion que inserta la reserva
-- (`libro_consumo.py:reservar`) -- esa atomicidad es el punto entero de la
-- etapa 3.
CREATE TABLE IF NOT EXISTS gastado_dia (
    ambiente                TEXT NOT NULL,
    dia                      TEXT NOT NULL,
    gastado_centavos         INTEGER NOT NULL DEFAULT 0,
    moneda                    TEXT NOT NULL DEFAULT 'COP',
    PRIMARY KEY (ambiente, dia)
);

-- Medios de pago vivos (equivalente a `boveda/secretos/fuentes.json`, que
-- separaba por modo). `estado` no se borra al revocar: se marca, para que
-- quede la evidencia de que existio.
CREATE TABLE IF NOT EXISTS medio_de_pago (
    proveedor                TEXT NOT NULL,
    ambiente                  TEXT NOT NULL,
    id_externo                TEXT NOT NULL,
    titular_id                 TEXT NOT NULL,
    estado                     TEXT NOT NULL,
    creado_en                  TEXT,
    PRIMARY KEY (proveedor, ambiente, id_externo)
);

-- Etapa 5: el carrito que `NavegarCatalogo.armar_carrito` arma y que
-- `EmitirMandato`/`EjecutarIntencion` vuelven a buscar por `carrito_id`.
-- Tiene que sobrevivir entre procesos igual que `mandato` -- si no,
-- `entradas/cli/` (donde "armar y firmar" y "pagar" son comandos separados,
-- cada uno su propio proceso) nunca podria completar una compra con
-- `AGORA_PERSISTENCIA=sqlite`. `items` va como JSON por el mismo motivo que
-- `categorias` en `mandato`: una tabla aparte seria mas ceremonia de la que
-- vale a esta escala.
CREATE TABLE IF NOT EXISTS carrito (
    carrito_id                TEXT PRIMARY KEY,
    comercio_id                TEXT NOT NULL,
    turno_id                    TEXT,
    items                        TEXT NOT NULL
);

-- Etapa 6: la `PropuestaDeMandato` que `NavegarCatalogo.armar_carrito` arma
-- junto con el carrito. Sin esto, `EmitirMandato` solo podia firmar una
-- propuesta que le llegara por parametro desde el MISMO proceso que la
-- creo -- lo que dejaba sin conectar el carrito que arma el chat (un
-- proceso) con la firma que hace el titular (`entradas/cli/firmar`, otro
-- proceso, otra terminal). Misma razon de ser que la tabla `carrito` de
-- arriba, un nivel mas adentro.
CREATE TABLE IF NOT EXISTS propuesta (
    propuesta_id               TEXT PRIMARY KEY,
    carrito_id                  TEXT NOT NULL,
    comercio_id                  TEXT NOT NULL,
    monto_max_centavos           INTEGER NOT NULL,
    monto_max_moneda             TEXT NOT NULL,
    usos_max                      INTEGER NOT NULL,
    vigencia_minutos               INTEGER NOT NULL,
    categorias                      TEXT NOT NULL,
    justificacion                    TEXT NOT NULL
);

-- Etapa 6 (segunda parte): `RegistroDeEstados`. Se penso "en memoria nomas"
-- en la etapa 5 porque su unico consumidor pensado era `consultar_estado`
-- DENTRO de la misma sesion de `chat`. Eso dejo de ser cierto en cuanto
-- `retomar` -- que nunca es herramienta del agente, resolver un CONFIRMAR
-- es siempre decision humana -- se corre desde OTRA terminal: sin esta
-- tabla, el chat nunca se entera de que la persona ya confirmo, y se queda
-- diciendo "esperando confirmacion humana" para siempre. Mismo argumento
-- que `carrito`/`propuesta` de arriba, un escalon mas adentro del flujo.
CREATE TABLE IF NOT EXISTS estado_intencion (
    intencion_id                TEXT PRIMARY KEY,
    estado                       TEXT NOT NULL,
    detalle                       TEXT NOT NULL
);
"""


def asegurar(con: sqlite3.Connection) -> None:
    con.executescript(DDL)
