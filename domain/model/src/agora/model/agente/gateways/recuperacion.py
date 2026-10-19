"""Los puertos de recuperacion documental (migracion a agentes, etapa 2).

Dos puertos, no uno, por la decision 2 de `docs/arquitectura-agentes/
arquitectura-agentes-langgraph.md` ("embeddings detras de su propio puerto"):

    ProveedorDeEmbeddings   texto -> vector. Hoy OpenAI
                            (`driven_adapters/embeddings_openai/`).
    BuscadorDocumental      consulta -> fragmentos de documentacion. Hoy un
                            vector store en memoria de LangChain
                            (`driven_adapters/recuperacion_langchain/`),
                            que recibe un `ProveedorDeEmbeddings` por
                            constructor.

Cambiar de proveedor de embeddings no toca el buscador; cambiar de vector
store no toca el proveedor. Y ninguno de los dos tipos de LangChain ni del SDK
de OpenAI cruza esta frontera: `FragmentoRecuperado` y `DocumentoFuente` son
del proyecto, igual que `Mensaje`/`RespuestaModelo` en `modelo_lenguaje.py`.

POR QUE "DOCUMENTAL" Y NO "SEMANTICO" A SECAS
-----------------------------------------------
El documento de arquitectura pide dos indices que nunca se mezclan: uno sobre
la documentacion (para soporte, esta etapa) y otro sobre el catalogo (etapa
4). Nombrar este puerto por lo que indexa -- y no por la tecnica -- es lo que
evita que en la etapa 4 alguien "reuse" este buscador metiendole productos:
el del catalogo va a ser otro puerto, con filtros duros (`en_stock`,
comercio vinculado) que la documentacion no tiene.

LO QUE ESTE PUERTO NUNCA DEVUELVE
----------------------------------
Una cifra con autoridad. Un fragmento de documentacion puede decir cualquier
monto -- y ya paso que la documentacion quedo desactualizada respecto del
codigo (paso con el tope duro por transaccion). Montos, topes y limites salen
siempre del objeto de dominio real (`Mandato`, `LibroDeConsumo`); quien
inyecta fragmentos en un prompt (`usecase/agente/contexto_documental.py`) les quita
las cifras antes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class DocumentoFuente:
    """Un documento entero antes de fragmentar. `fuente` es un identificador
    estable y legible (la ruta relativa al repo, en la practica): es lo que
    se le muestra al modelo para que diga de donde sale lo que responde."""

    fuente: str
    titulo: str
    texto: str


@dataclass(frozen=True)
class FragmentoRecuperado:
    """`puntaje` es una similitud: mayor es mas parecido. Sirve para ordenar
    y para descartar lo irrelevante; no es una probabilidad ni se compara
    entre proveedores de embeddings distintos."""

    fuente: str
    seccion: str
    texto: str
    puntaje: float


class ProveedorDeEmbeddings(Protocol):
    def embeber_documentos(self, textos: Sequence[str]) -> list[list[float]]:
        """Un vector por texto, en el mismo orden. Levanta
        `RecuperacionNoDisponible` si el proveedor no responde y
        `RespuestaDeEmbeddingsInvalida` si responde con otra forma."""
        ...

    def embeber_consulta(self, texto: str) -> list[float]:
        """Mismas excepciones que `embeber_documentos`. Algunos proveedores
        embeben distinto una consulta que un documento; por eso son dos
        metodos aunque hoy el adaptador de OpenAI los resuelva igual."""
        ...


class BuscadorDocumental(Protocol):
    def buscar(self, consulta: str, limite: int = 4) -> list[FragmentoRecuperado]:
        """Hasta `limite` fragmentos, del mas al menos parecido. Una consulta
        vacia devuelve lista vacia, no un error. Levanta
        `RecuperacionNoDisponible` si no se pudo consultar."""
        ...
