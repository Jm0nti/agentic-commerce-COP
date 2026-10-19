"""El puerto del catalogo. `docs/arquitectura.md`, seccion 3: una sola
interfaz, dos formas de servirla -- la de verdad no existe todavia (los
comercios de esta demo siempre son simulados), la de mentiras es
`driven_adapters/catalogo_semilla/`, que lee un `catalogo.json` fabricado por
`usecase/generar_catalogo_semilla/generar_catalogo_semilla_use_case.py`.

TRES METODOS, NO UNO
---------------------
`docs/arquitectura.md` (seccion 5) le da al agente tres herramientas
separadas -- `buscar_comercios`, `buscar_productos`, `ver_producto` -- en vez
de una sola `navegar(consulta)` que devuelva de todo. No es apuro: un agente
que primero elige un comercio y despues busca dentro de el hace preguntas mas
chicas y mas faciles de auditar que uno que busca en todo el catalogo de una
vez. El puerto refleja esa forma de navegar, no la aplana.

DONDE VIVE LA BUSQUEDA
-----------------------
`consulta` es un string libre; como se interpreta (substring, por categoria,
por similitud) es decision de cada adaptador, no de este puerto. La semilla
de esta etapa hace un match trivial por substring -- alcanza para una demo
con pocos comercios y no hace falta mas hasta que haga falta de verdad.
"""

from __future__ import annotations

from typing import Protocol

from ..modelo import Comercio, Producto


class RepositorioCatalogo(Protocol):
    def buscar_comercios(self, consulta: str = "") -> list[Comercio]:
        """`consulta` vacia devuelve todos los comercios. Nunca levanta por
        no encontrar nada -- una lista vacia es una respuesta valida."""
        ...

    def buscar_productos(self, comercio_id: str, consulta: str = "") -> list[Producto]:
        """Levanta `ComercioDesconocido` si `comercio_id` no existe.
        `consulta` vacia devuelve todo el catalogo de ese comercio."""
        ...

    def ver_producto(self, producto_id: str) -> Producto:
        """Levanta `ProductoDesconocido` si no existe. A diferencia de las
        busquedas, aqui no hay una respuesta vacia razonable: quien llama
        siempre llega con un id que espera que exista (lo saco de
        `buscar_productos`), asi que uno que no existe es un error, no un
        resultado."""
        ...
