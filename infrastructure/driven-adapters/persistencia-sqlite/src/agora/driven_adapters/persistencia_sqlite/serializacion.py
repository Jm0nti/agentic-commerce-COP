"""Mandato <-> fila de SQLite. Centralizado aqui para que `repositorio_
mandatos.py` no repita las mismas 19 columnas en cada metodo.

`categorias` se guarda como JSON (`tuple[str, ...]` no tiene un tipo columna
nativo razonable para 0..N valores sin una tabla aparte, que a esta escala es
mas ceremonia de la que vale). Todo lo demas es una columna por campo: nada
de serializar el mandato completo a JSON, porque entonces `listar(ambiente)`
no podria filtrar con SQL.
"""

from __future__ import annotations

import json
from datetime import datetime

from ...model.commons.dinero import Dinero
from ...model.mandato.modelo import Mandato
from ...model.pago.modelo import Ambiente, MedioDePagoRef, Proveedor

# Orden fijo de columnas: lo que `mandato_a_fila` produce y lo que
# `fila_a_mandato` consume tienen que coincidir exactamente con esto y con
# el `INSERT` de `repositorio_mandatos.py`.
COLUMNAS = (
    "mandato_id", "ambiente", "titular_id",
    "medio_proveedor", "medio_ambiente", "medio_id_externo",
    "comercio_id",
    "monto_max_centavos", "monto_max_moneda",
    "tope_total_centavos", "tope_total_moneda",
    "usos_max", "expira_en", "creado_en",
    "llave_publica", "categorias", "carrito_hash", "version", "firma",
)


def mandato_a_fila(mandato: Mandato, ambiente: Ambiente) -> tuple:
    return (
        mandato.mandato_id,
        ambiente.value,
        mandato.titular_id,
        mandato.medio.proveedor.value,
        mandato.medio.ambiente.value,
        mandato.medio.id_externo,
        mandato.comercio_id,
        mandato.monto_max.centavos,
        mandato.monto_max.moneda,
        mandato.tope_total.centavos,
        mandato.tope_total.moneda,
        mandato.usos_max,
        mandato.expira_en.isoformat(),
        mandato.creado_en.isoformat(),
        mandato.llave_publica,
        json.dumps(list(mandato.categorias)),
        mandato.carrito_hash,
        mandato.version,
        mandato.firma,
    )


def fila_a_mandato(fila: tuple) -> Mandato:
    (
        mandato_id, _ambiente, titular_id,
        medio_proveedor, medio_ambiente, medio_id_externo,
        comercio_id,
        monto_max_centavos, monto_max_moneda,
        tope_total_centavos, tope_total_moneda,
        usos_max, expira_en, creado_en,
        llave_publica, categorias_json, carrito_hash, version, firma,
    ) = fila
    return Mandato(
        mandato_id=mandato_id,
        titular_id=titular_id,
        medio=MedioDePagoRef(
            Proveedor(medio_proveedor), Ambiente(medio_ambiente), medio_id_externo
        ),
        comercio_id=comercio_id,
        monto_max=Dinero.de_centavos(monto_max_centavos, monto_max_moneda),
        tope_total=Dinero.de_centavos(tope_total_centavos, tope_total_moneda),
        usos_max=usos_max,
        expira_en=datetime.fromisoformat(expira_en),
        creado_en=datetime.fromisoformat(creado_en),
        llave_publica=bytes(llave_publica),
        categorias=tuple(json.loads(categorias_json)),
        carrito_hash=carrito_hash,
        version=version,
        firma=bytes(firma),
    )
