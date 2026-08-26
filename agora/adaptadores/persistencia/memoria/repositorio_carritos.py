"""`RepositorioCarritos` en memoria.

Simetrico a `repositorio_mandatos.py`: un `dict` protegido por un lock, sin
persistencia entre procesos. Alcanza para esta etapa -- un carrito vive el
tiempo de una conversacion, y no hay todavia una version SQLite porque nada
en `docs/arquitectura-v2.md` pide que un carrito sobreviva un reinicio (a
diferencia del consumo o los mandatos, que si tienen que hacerlo contra
dinero real).
"""

from __future__ import annotations

import threading

from ....dominio.catalogo.modelo import Carrito
from ....dominio.comun.errores import CarritoDesconocido


class RepositorioCarritosEnMemoria:
    """Implementa `puertos.repositorios.RepositorioCarritos`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._carritos: dict[str, Carrito] = {}

    def guardar(self, carrito: Carrito) -> None:
        with self._lock:
            self._carritos[carrito.carrito_id] = carrito

    def obtener(self, carrito_id: str) -> Carrito:
        with self._lock:
            carrito = self._carritos.get(carrito_id)
        if carrito is None:
            raise CarritoDesconocido(f"carrito desconocido: {carrito_id}")
        return carrito
