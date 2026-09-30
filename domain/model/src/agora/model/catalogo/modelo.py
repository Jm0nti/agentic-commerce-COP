"""Catalogo y carrito.

Los comercios son simulados y los productos tambien. Lo unico real es el dinero
que sale al final, y por eso el carrito importa mas de lo que parece: es lo que
ata una conversacion con un modelo de lenguaje a un debito en una cuenta.

EL HASH CANONICO
----------------
`Carrito.hash_canonico` es lo que hace posible el Cart Mandate de AP2. Sin el,
un agente manipulado puede hacer firmar un carrito de 45.000 COP y presentar
otro distinto por el mismo monto y al mismo comercio: el mandato no notaria
nada, porque el mandato solo mira montos y destinos.

El hash cubre los items, no solo el total. Cambiar dos audifonos por una consola
del mismo precio rompe la verificacion, que es exactamente lo que debe pasar.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..commons.dinero import CERO, Dinero
from ..commons.identidad import CarritoId, ComercioId, ProductoId, TurnoId


class Disponibilidad(str, Enum):
    """El vocabulario de `availability` del product feed de ACP (OpenAI +
    Stripe), reducido a lo que esta demo necesita -- sin `unknown` (aqui
    todo producto simulado tiene un estado, nunca uno desconocido).

    `PoliticaDeMandato` (etapa 1) no mira este campo: el mandato protege
    contra gastar de mas, no contra comprar algo agotado. Eso lo decide
    `navegar_catalogo` (etapa 5), filtrando o avisando antes de armar el
    carrito -- un producto AGOTADO nunca deberia llegar a `ItemCarrito`.
    """

    EN_STOCK = "en_stock"
    AGOTADO = "agotado"
    PEDIDO_ANTICIPADO = "pedido_anticipado"


@dataclass(frozen=True)
class Comercio:
    comercio_id: ComercioId
    nombre: str
    categoria: str
    descripcion: str = ""
    simulado: bool = True


@dataclass(frozen=True)
class Producto:
    producto_id: ProductoId
    comercio_id: ComercioId
    nombre: str
    descripcion: str
    precio: Dinero
    categoria: str
    disponibilidad: Disponibilidad = Disponibilidad.EN_STOCK


@dataclass(frozen=True)
class ItemCarrito:
    producto_id: ProductoId
    nombre: str
    cantidad: int
    # Congelado al armar el carrito. Si el catalogo cambia de precio despues, el
    # carrito firmado sigue valiendo lo que decia -- y si no coincide con el
    # catalogo al cobrar, eso es un hallazgo, no un detalle a corregir en
    # silencio.
    precio_unitario: Dinero

    def __post_init__(self) -> None:
        if self.cantidad < 1:
            raise ValueError("un item con cantidad menor a 1 no es un item")

    @property
    def subtotal(self) -> Dinero:
        return self.precio_unitario * self.cantidad


@dataclass(frozen=True)
class Carrito:
    carrito_id: CarritoId
    comercio_id: ComercioId
    items: tuple[ItemCarrito, ...]
    turno_id: TurnoId | None = None

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("un carrito vacio no se puede firmar ni cobrar")

    @property
    def total(self) -> Dinero:
        total = CERO
        for i in self.items:
            total = total + i.subtotal
        return total

    def canonico(self) -> bytes:
        """Estable e independiente del orden en que el agente agrego las cosas.

        Se ordena por `producto_id` porque dos carritos con los mismos items en
        distinto orden son el mismo carrito, y firmar el orden convertiria una
        diferencia irrelevante en una violacion.

        `carrito_id` y `turno_id` quedan fuera a proposito: identifican la
        instancia, no el contenido.
        """
        d = {
            "comercio_id": self.comercio_id,
            "items": [
                {
                    "producto_id": i.producto_id,
                    "cantidad": i.cantidad,
                    "precio_unitario": i.precio_unitario.to_json(),
                }
                for i in sorted(self.items, key=lambda x: x.producto_id)
            ],
            "total": self.total.to_json(),
        }
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def hash_canonico(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonico()).hexdigest()

    def to_json(self) -> dict[str, Any]:
        return {
            "carrito_id": self.carrito_id,
            "comercio_id": self.comercio_id,
            "turno_id": self.turno_id,
            "total": self.total.to_json(),
            "hash_canonico": self.hash_canonico,
            "items": [
                {
                    "producto_id": i.producto_id,
                    "nombre": i.nombre,
                    "cantidad": i.cantidad,
                    "precio_unitario": i.precio_unitario.to_json(),
                }
                for i in self.items
            ],
        }
