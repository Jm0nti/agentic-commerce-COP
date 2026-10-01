"""Implementa `puertos.catalogo.RepositorioCatalogo` leyendo un
`catalogo.json` estatico -- sin red, sin base de datos.

Simetrico a como la pasarela simulada resuelve pagos sin hablar con Wompi
(ADR-2 de `docs/arquitectura-v2.md`): el catalogo simulado no necesita un
servidor detras para que el agente lo navegue, solo datos con la forma
correcta. La diferencia es de donde salen esos datos -- `AdaptadorSimulado`
los decide en el momento (`GuionSimulado`), este adaptador los lee de un
archivo que `scripts/generar_catalogo_semilla.py` fabrico una vez, con
DeepSeek, por fuera del camino caliente. Ningun cobro ni ninguna busqueda del
agente dependen de que DeepSeek este disponible.
"""

from __future__ import annotations

import json
from pathlib import Path

from ...model.catalogo.modelo import Comercio, Producto
from ...model.commons.errores import ComercioDesconocido, ProductoDesconocido
from . import serializacion

RUTA_POR_DEFECTO = Path(__file__).resolve().parent / "datos" / "catalogo.json"


class RepositorioCatalogoSemilla:
    """Implementa `puertos.catalogo.RepositorioCatalogo`."""

    nombre = "semilla"

    def __init__(self, ruta: Path = RUTA_POR_DEFECTO) -> None:
        self._comercios, self._productos = _cargar(ruta)

    def buscar_comercios(self, consulta: str = "") -> list[Comercio]:
        termino = consulta.strip().lower()
        comercios = list(self._comercios.values())
        if not termino:
            return comercios
        return [c for c in comercios if _coincide(termino, c.nombre, c.categoria, c.descripcion)]

    def buscar_productos(self, comercio_id: str, consulta: str = "") -> list[Producto]:
        if comercio_id not in self._comercios:
            raise ComercioDesconocido(f"no existe el comercio '{comercio_id}'")
        del_comercio = [p for p in self._productos.values() if p.comercio_id == comercio_id]
        termino = consulta.strip().lower()
        if not termino:
            return del_comercio
        return [p for p in del_comercio if _coincide(termino, p.nombre, p.descripcion)]

    def ver_producto(self, producto_id: str) -> Producto:
        try:
            return self._productos[producto_id]
        except KeyError:
            raise ProductoDesconocido(f"no existe el producto '{producto_id}'") from None


def _coincide(termino: str, *campos: str) -> bool:
    return any(termino in campo.lower() for campo in campos)


def _cargar(ruta: Path) -> tuple[dict[str, Comercio], dict[str, Producto]]:
    if not ruta.exists():
        raise FileNotFoundError(
            f"no existe {ruta} -- corra scripts/generar_catalogo_semilla.py "
            "para fabricar el catalogo antes de usar este adaptador"
        )
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    comercios = {
        fila["comercio_id"]: serializacion.comercio_desde_json(fila)
        for fila in datos.get("comercios", [])
    }
    productos = {
        fila["producto_id"]: serializacion.producto_desde_json(fila)
        for fila in datos.get("productos", [])
    }
    return comercios, productos
