"""`RepositorioCarritos` contra SQLite. Ver el comentario de la tabla
`carrito` en `esquema.py` para el porque: sin esto, `entry_points/cli/` (donde
"armar y firmar" y "pagar" son comandos separados, cada uno su propio
proceso) nunca podria completar una compra con `AGORA_PERSISTENCIA=sqlite`
-- el adaptador en memoria pierde el carrito apenas termina el proceso que
lo armo.
"""

from __future__ import annotations

import json
from pathlib import Path

from ...model.catalogo.modelo import Carrito, ItemCarrito
from ...model.commons.dinero import Dinero
from ...model.commons.errores import CarritoDesconocido
from .conexion import abrir_conexion


def _items_a_json(carrito: Carrito) -> str:
    return json.dumps([
        {
            "producto_id": i.producto_id,
            "nombre": i.nombre,
            "cantidad": i.cantidad,
            "precio_unitario_centavos": i.precio_unitario.centavos,
            "precio_unitario_moneda": i.precio_unitario.moneda,
        }
        for i in carrito.items
    ])


def _items_desde_json(bruto: str) -> tuple[ItemCarrito, ...]:
    return tuple(
        ItemCarrito(
            producto_id=d["producto_id"],
            nombre=d["nombre"],
            cantidad=d["cantidad"],
            precio_unitario=Dinero.de_centavos(
                d["precio_unitario_centavos"], d["precio_unitario_moneda"]
            ),
        )
        for d in json.loads(bruto)
    )


class RepositorioCarritosSQLite:
    """Implementa `puertos.repositorios.RepositorioCarritos`."""

    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta

    def guardar(self, carrito: Carrito) -> None:
        con = abrir_conexion(self._ruta)
        try:
            con.execute(
                "INSERT OR REPLACE INTO carrito (carrito_id, comercio_id, turno_id, items) "
                "VALUES (?, ?, ?, ?)",
                (carrito.carrito_id, carrito.comercio_id, carrito.turno_id, _items_a_json(carrito)),
            )
        finally:
            con.close()

    def obtener(self, carrito_id: str) -> Carrito:
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                "SELECT carrito_id, comercio_id, turno_id, items FROM carrito WHERE carrito_id = ?",
                (carrito_id,),
            ).fetchone()
        finally:
            con.close()
        if fila is None:
            raise CarritoDesconocido(f"carrito desconocido: {carrito_id}")
        carrito_id, comercio_id, turno_id, items_json = fila
        return Carrito(
            carrito_id=carrito_id, comercio_id=comercio_id, turno_id=turno_id,
            items=_items_desde_json(items_json),
        )
