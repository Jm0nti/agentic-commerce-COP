"""Como se abre una conexion SQLite en este paquete, y por que.

Una conexion nueva por llamada, no una compartida entre hilos. `sqlite3.
Connection` de Python no esta pensado para compartirse entre hilos sin
condiciones (`check_same_thread`), y verificar que el SQLite del sistema esta
compilado en modo "serialized" no vale la pena a esta escala. Abrir y cerrar
por operacion es mas lento, pero deja que sea SQLite -- via WAL y
`busy_timeout`, a nivel de archivo -- quien de verdad serialice el acceso
concurrente. Es exactamente lo que las pruebas de concurrencia verifican.

`PRAGMA journal_mode=WAL` (ADR-3, `docs/arquitectura.md`): lectores no
bloquean escritores. `isolation_level=None` deja el control de transacciones
en manos de cada adaptador (`BEGIN IMMEDIATE` explicito) en vez del manejo
implicito de Python, que puede pelear con sentencias `BEGIN` propias.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import esquema


def abrir_conexion(ruta: Path, tiempo_espera_seg: float = 10.0) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(ruta), timeout=tiempo_espera_seg, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    esquema.asegurar(con)
    return con
