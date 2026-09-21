"""Implementa `puertos.busqueda_productos.BuscadorSemanticoDeProductos` con
un indice en memoria y coseno de numpy.

POR QUE NUMPY Y NO UN VECTOR STORE
------------------------------------
La etapa 2 uso `InMemoryVectorStore` de LangChain para la documentacion, y
ahi valia la pena: LangChain aportaba el fragmentado de Markdown por
encabezados, que es trabajo de verdad. Un producto no se fragmenta -- es una
linea de texto -- asi que lo unico que quedaria de LangChain aca es el
coseno, que son tres lineas de numpy, y numpy YA es dependencia del
proyecto. Traer un vector store para eso seria sumar una capa que hay que
entender a las 3 de la manana para no ganar nada.

El catalogo son decenas de productos. Si algun dia son cientos de miles, se
cambia este adaptador por uno con indice de verdad y el puerto no se entera
-- que es justamente para lo que existe el puerto.

CUANDO SE LLAMA AL PROVEEDOR DE EMBEDDINGS
--------------------------------------------
Nunca al construir. El indice se arma la PRIMERA vez que alguien busca, y
solo sobre los productos que se pasaron al constructor. Mismo criterio que
el buscador documental: construir el `Contenedor` no toca la red, y si esa
primera indexacion falla no queda un indice a medias -- la siguiente
busqueda lo reintenta.

LO QUE NO PUEDE HACER
-----------------------
Devolver algo que no este en `candidatos`. El indice se arma sobre el
catalogo completo, pero `buscar` descarta todo lo que no venga en la lista
de candidatos que recibe: las reglas duras (disponibilidad, precio,
comercio) las decidio quien llama, antes, con objetos de dominio. Un
producto que no paso esos filtros no vuelve por la puerta de atras aunque
sea el mas parecido del mundo.
"""

from __future__ import annotations

import threading
from typing import Sequence

import numpy as np

from ....dominio.catalogo.modelo import Producto
from ....puertos.recuperacion import ProveedorDeEmbeddings

# Coseno minimo para considerar que un producto tiene algo que ver con la
# consulta. MEDIDO contra OpenAI real el 19 de septiembre de 2026
# (`scripts/validar_con_modelos_reales.py`, catalogo semilla de 24 productos,
# `text-embedding-3-small`): consultas ajenas al catalogo ("un tractor
# agricola usado", "clases de piano") tocaron techo en 0,288; necesidades que
# el catalogo SI satisface arrancaron en 0,333.
#
# EL PISO NO ALCANZA, Y ESO ES UN HALLAZGO
# ------------------------------------------
# La misma medicion mostro que una necesidad PLAUSIBLE que el catalogo no
# puede satisfacer ("algo para la piel reseca", contra un catalogo de
# confites y papeleria) saca ~0,34 -- MAS que una consulta absurda. Ningun
# umbral separa "no hay match" de "hay un match debil": a 0,31 el modelo
# recibe una Chocolatina como respuesta a una crema. La defensa de verdad es
# que este peldano solo corre cuando el estructurado no encontro nada, y que
# la instruccion del nodo le pide al modelo no inventar. Ver
# `docs/arquitectura-agentes/etapa-4-agentes-especializados-retrieval-
# hibrido.md`, seccion de validacion.
PARECIDO_MINIMO_POR_DEFECTO = 0.31
LIMITE_POR_DEFECTO = 5


def texto_de(producto: Producto) -> str:
    """Lo que se embebe de un producto. Nombre, descripcion y categoria --
    los tres campos que describen QUE es; nunca el precio ni la
    disponibilidad, que son reglas duras y no se parecen a nada."""
    partes = [producto.nombre, producto.descripcion, producto.categoria]
    return " ".join(p.strip() for p in partes if p and p.strip())


class BuscadorSemanticoEnMemoria:
    """Implementa `puertos.busqueda_productos.BuscadorSemanticoDeProductos`."""

    def __init__(
        self,
        productos: Sequence[Producto],
        embeddings: ProveedorDeEmbeddings,
        parecido_minimo: float = PARECIDO_MINIMO_POR_DEFECTO,
    ) -> None:
        self._productos = tuple(productos)
        self._embeddings = embeddings
        self._parecido_minimo = parecido_minimo
        self._matriz: np.ndarray | None = None
        self._lock = threading.Lock()

    @property
    def cantidad_de_productos(self) -> int:
        return len(self._productos)

    @property
    def indexado(self) -> bool:
        return self._matriz is not None

    def puntuar(
        self, consulta: str, candidatos: Sequence[Producto]
    ) -> list[tuple[Producto, float]]:
        """Los candidatos con su parecido, de mayor a menor, SIN aplicar el
        piso ni el limite.

        Existe para poder calibrar `parecido_minimo`: un umbral que no se
        puede ver no se puede elegir, solo adivinar. El puerto documental ya
        devuelve el `puntaje` de cada fragmento (`FragmentoRecuperado`) por
        la misma razon; esto lo hace simetrico.
        `scripts/validar_con_modelos_reales.py` es quien lo usa."""
        consulta = consulta.strip()
        elegibles = {p.producto_id for p in candidatos}
        if not consulta or not elegibles or not self._productos:
            return []

        matriz = self._indice()
        vector = _normalizar(np.asarray(self._embeddings.embeber_consulta(consulta), dtype=float))
        parecidos = matriz @ vector

        # `argsort` descendente sobre todo el indice, y recien despues se
        # descartan los que no son candidatos: asi el orden es el del
        # parecido real y no el de la lista que llego.
        return [
            (self._productos[int(i)], float(parecidos[int(i)]))
            for i in np.argsort(-parecidos)
            if self._productos[int(i)].producto_id in elegibles
        ]

    def buscar(
        self, consulta: str, candidatos: Sequence[Producto], limite: int = LIMITE_POR_DEFECTO
    ) -> list[Producto]:
        if limite < 1:
            raise ValueError(f"limite invalido: {limite}")
        return [
            producto
            for producto, parecido in self.puntuar(consulta, candidatos)[:limite]
            if parecido >= self._parecido_minimo
        ]

    def _indice(self) -> np.ndarray:
        # Lock por la misma razon que el buscador documental: `entradas/api/`
        # atiende turnos en un threadpool y dos busquedas simultaneas al
        # arrancar no deberian embeber el catalogo dos veces.
        with self._lock:
            if self._matriz is None:
                vectores = self._embeddings.embeber_documentos(
                    [texto_de(p) for p in self._productos]
                )
                matriz = np.asarray(vectores, dtype=float)
                if matriz.ndim != 2 or matriz.shape[0] != len(self._productos):
                    raise ValueError(
                        f"el proveedor devolvio {matriz.shape} vectores para "
                        f"{len(self._productos)} productos"
                    )
                # Se asigna recien si todo salio bien: una falla del
                # proveedor sube sin dejar un indice a medias.
                self._matriz = _normalizar_filas(matriz)
            return self._matriz


def _normalizar(vector: np.ndarray) -> np.ndarray:
    """Vectores unitarios: con eso el producto punto ES el coseno, y no hay
    que dividir por normas en cada busqueda."""
    norma = float(np.linalg.norm(vector))
    return vector if norma == 0.0 else vector / norma


def _normalizar_filas(matriz: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0.0] = 1.0
    return matriz / normas
