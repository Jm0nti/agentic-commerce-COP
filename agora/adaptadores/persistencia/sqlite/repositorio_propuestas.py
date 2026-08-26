"""`RepositorioPropuestas` contra SQLite. Ver el comentario de la tabla
`propuesta` en `esquema.py` para el porque: sin esto, una `PropuestaDeMandato`
armada durante una charla de `chat` no sobrevive para que `entradas/cli/
firmar` la encuentre desde otra terminal -- el mismo problema que la tabla
`carrito` (etapa 5) resuelve para el carrito.
"""

from __future__ import annotations

import json
from pathlib import Path

from ....dominio.comun.dinero import Dinero
from ....dominio.comun.errores import PropuestaDesconocida
from ....dominio.mandato.modelo import PropuestaDeMandato
from .conexion import abrir_conexion


class RepositorioPropuestasSQLite:
    """Implementa `puertos.repositorios.RepositorioPropuestas`."""

    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta

    def guardar(self, propuesta: PropuestaDeMandato) -> None:
        con = abrir_conexion(self._ruta)
        try:
            con.execute(
                "INSERT OR REPLACE INTO propuesta (propuesta_id, carrito_id, comercio_id, "
                "monto_max_centavos, monto_max_moneda, usos_max, vigencia_minutos, "
                "categorias, justificacion) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    propuesta.propuesta_id,
                    propuesta.carrito_id,
                    propuesta.comercio_id,
                    propuesta.monto_max.centavos,
                    propuesta.monto_max.moneda,
                    propuesta.usos_max,
                    propuesta.vigencia_minutos,
                    json.dumps(list(propuesta.categorias)),
                    propuesta.justificacion,
                ),
            )
        finally:
            con.close()

    def obtener(self, propuesta_id: str) -> PropuestaDeMandato:
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                "SELECT propuesta_id, carrito_id, comercio_id, monto_max_centavos, "
                "monto_max_moneda, usos_max, vigencia_minutos, categorias, justificacion "
                "FROM propuesta WHERE propuesta_id = ?",
                (propuesta_id,),
            ).fetchone()
        finally:
            con.close()
        if fila is None:
            raise PropuestaDesconocida(f"propuesta desconocida: {propuesta_id}")
        (
            propuesta_id, carrito_id, comercio_id, monto_max_centavos,
            monto_max_moneda, usos_max, vigencia_minutos, categorias_json, justificacion,
        ) = fila
        return PropuestaDeMandato(
            propuesta_id=propuesta_id,
            carrito_id=carrito_id,
            comercio_id=comercio_id,
            monto_max=Dinero.de_centavos(monto_max_centavos, monto_max_moneda),
            usos_max=usos_max,
            vigencia_minutos=vigencia_minutos,
            categorias=tuple(json.loads(categorias_json)),
            justificacion=justificacion,
        )
