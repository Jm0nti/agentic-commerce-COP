"""`Comercio`/`Producto` <-> fila de `catalogo.json`.

Centralizado aqui por la misma razon que `driven_adapters/persistencia_sqlite/
serializacion.py`: para que `repositorio.py` no repita la forma del JSON en
cada metodo, y para que escribir el archivo (`scripts/
generar_catalogo_semilla.py`) y leerlo (`RepositorioCatalogoSemilla`) usen
exactamente la misma definicion de "fila", no dos que puedan divergir.
"""

from __future__ import annotations

from typing import Any

from ...model.catalogo.modelo import Comercio, Disponibilidad, Producto
from ...model.commons.dinero import Dinero


def comercio_a_json(comercio: Comercio) -> dict[str, Any]:
    return {
        "comercio_id": comercio.comercio_id,
        "nombre": comercio.nombre,
        "categoria": comercio.categoria,
        "descripcion": comercio.descripcion,
        "simulado": comercio.simulado,
    }


def comercio_desde_json(fila: dict[str, Any]) -> Comercio:
    return Comercio(
        comercio_id=fila["comercio_id"],
        nombre=fila["nombre"],
        categoria=fila["categoria"],
        descripcion=fila.get("descripcion", ""),
        simulado=fila.get("simulado", True),
    )


def producto_a_json(producto: Producto) -> dict[str, Any]:
    return {
        "producto_id": producto.producto_id,
        "comercio_id": producto.comercio_id,
        "nombre": producto.nombre,
        "descripcion": producto.descripcion,
        "precio": producto.precio.to_json(),
        "categoria": producto.categoria,
        "disponibilidad": producto.disponibilidad.value,
    }


def producto_desde_json(fila: dict[str, Any]) -> Producto:
    precio = fila["precio"]
    return Producto(
        producto_id=fila["producto_id"],
        comercio_id=fila["comercio_id"],
        nombre=fila["nombre"],
        descripcion=fila.get("descripcion", ""),
        precio=Dinero.de_centavos(precio["centavos"], precio.get("moneda", "COP")),
        categoria=fila["categoria"],
        disponibilidad=Disponibilidad(fila.get("disponibilidad", Disponibilidad.EN_STOCK.value)),
    )
