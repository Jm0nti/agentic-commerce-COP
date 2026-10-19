"""Busqueda semantica de productos y sus reglas duras (migracion a agentes,
etapa 4).

`docs/arquitectura-agentes/arquitectura-agentes-langgraph.md`, decision 1:
la recuperacion del catalogo son tres peldanos, no un RAG unico.

    1. estructurada   filtros exactos y match por nombre/descripcion. Es lo
                      que ya hace `RepositorioCatalogo`. Preferida siempre
                      que alcance: es auditable y no puede devolver un
                      producto inexistente.
    2. reglas duras   `FiltrosDeProducto` -- disponibilidad, comercio, rango
                      de precio. Se aplican SIEMPRE, antes y despues del
                      peldano semantico.
    3. semantica      `BuscadorSemanticoDeProductos`, solo cuando lo
                      estructurado no encontro nada.

POR QUE UN PUERTO SEPARADO DEL DE SOPORTE
-------------------------------------------
`model/agente/gateways/recuperacion.py:BuscadorDocumental` indexa documentacion; este
indexa productos. El documento pide dos indices que NUNCA se mezclan
(decision 1), y `tests/arquitectura/test_fronteras.py` lo verifica. Comparten una sola
cosa a proposito: `ProveedorDeEmbeddings`, que es el puerto de "texto ->
vector" de la decision 2 y no sabe nada de lo que se este indexando.

LO QUE ESTE PUERTO NUNCA DECIDE
---------------------------------
Que producto se puede comprar. `buscar` recibe los candidatos YA filtrados y
solo los ordena por parecido: no lee el catalogo, no consulta stock, no
puede devolver algo que no estuviera en `candidatos`. Un modelo de
embeddings no tiene autoridad sobre disponibilidad ni sobre precio -- esas
son reglas duras del dominio, y por eso se aplican de este lado de la
frontera.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from ..modelo import Disponibilidad, Producto


@dataclass(frozen=True)
class FiltrosDeProducto:
    """Las reglas duras de la decision 1, dichas como datos.

    Todos los campos son opcionales y el default es "no filtrar nada": asi
    `buscar_productos` sin filtros se comporta exactamente como antes de
    esta etapa. En particular `solo_disponibles` arranca en `False` --
    esconder los agotados por omision cambiaria lo que hoy ve el modelo, y
    que un producto este agotado es informacion util para contestar ("ese
    esta agotado, te muestro otro") aunque no se pueda comprar
    (`usecase/navegar_catalogo/navegar_catalogo_use_case.py:armar_carrito` lo rechaza igual)."""

    solo_disponibles: bool = False
    precio_min_cop: int | None = None
    precio_max_cop: int | None = None

    def __post_init__(self) -> None:
        for campo, valor in (
            ("precio_min_cop", self.precio_min_cop),
            ("precio_max_cop", self.precio_max_cop),
        ):
            if valor is not None and valor < 0:
                raise ValueError(f"{campo} no puede ser negativo: {valor}")
        if (
            self.precio_min_cop is not None
            and self.precio_max_cop is not None
            and self.precio_min_cop > self.precio_max_cop
        ):
            raise ValueError(
                f"rango de precio invalido: min={self.precio_min_cop} > "
                f"max={self.precio_max_cop}"
            )

    @property
    def vacios(self) -> bool:
        return self == FiltrosDeProducto()

    def aplicar(self, productos: Sequence[Producto]) -> list[Producto]:
        """Conserva el orden de entrada. Es una funcion pura sobre objetos de
        dominio -- ningun adaptador la puede saltear, porque quien busca la
        llama antes de entregar resultados."""
        return [p for p in productos if self._pasa(p)]

    def _pasa(self, producto: Producto) -> bool:
        if self.solo_disponibles and producto.disponibilidad is not Disponibilidad.EN_STOCK:
            return False
        pesos = producto.precio.pesos
        if self.precio_min_cop is not None and pesos < self.precio_min_cop:
            return False
        if self.precio_max_cop is not None and pesos > self.precio_max_cop:
            return False
        return True


class BuscadorSemanticoDeProductos(Protocol):
    def buscar(
        self, consulta: str, candidatos: Sequence[Producto], limite: int = 5
    ) -> list[Producto]:
        """Hasta `limite` productos de `candidatos`, del mas al menos
        parecido a `consulta`.

        Recibe los candidatos en vez de ir a buscarlos: asi el resultado es
        siempre un subconjunto de lo que quien llama ya considero elegible,
        y una regla dura no se puede evadir por el camino semantico. Una
        consulta vacia o una lista vacia devuelven lista vacia, no un error.
        Levanta `RecuperacionNoDisponible` si no se pudo consultar al
        proveedor de embeddings."""
        ...
