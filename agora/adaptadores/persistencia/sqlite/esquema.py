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
"""


def asegurar(con: sqlite3.Connection) -> None:
    con.executescript(DDL)
