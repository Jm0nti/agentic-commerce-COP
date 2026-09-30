"""Persistencia de los carritos. Salio de `puertos/repositorios.py` (Fase 2
del refactor a la Clean Architecture de Bancolombia).
"""

from __future__ import annotations

from typing import Protocol

from ..modelo import Carrito


class RepositorioCarritos(Protocol):
    """Etapa 5. `EmitirMandato` necesita volver a buscar el `Carrito` EXACTO
    por `carrito_id` al momento de firmar, en vez de confiar en un carrito
    que le llegue de afuera (por ejemplo, por parametro desde el agente):
    calcular `carrito_hash` a partir de una fuente que el agente pudo
    manipular volveria inutil la verificacion que ese hash existe para
    ofrecer. `NavegarCatalogo.armar_carrito` es el unico que guarda."""

    def guardar(self, carrito: Carrito) -> None: ...

    def obtener(self, carrito_id: str) -> Carrito:
        """Levanta `CarritoDesconocido` si no existe."""
        ...
