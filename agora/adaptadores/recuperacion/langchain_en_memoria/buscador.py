"""Implementa `puertos.recuperacion.BuscadorDocumental` con LangChain:
`MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter` para
fragmentar, e `InMemoryVectorStore` para buscar por similitud.

POR QUE EN MEMORIA
--------------------
El corpus de soporte son unos pocos documentos: decenas de fragmentos. Un
vector store con disco (FAISS, Chroma) sumaria dependencias nativas al venv
de Windows para ganar una sola cosa -- no re-embeber al reiniciar -- que con
este tamaño cuesta centavos. Si el corpus crece, se cambia este adaptador;
el puerto no se entera.

CUANDO SE LLAMA A OPENAI
--------------------------
Fragmentar es local y ocurre al construir (rapido, deterministico, y asi un
Markdown roto falla al arrancar y no a mitad de una charla). Embeber no: el
indice se arma la PRIMERA vez que alguien busca. Construir el `Contenedor`
nunca toca la red -- ni las pruebas, ni un arranque sin conexion. Si esa
primera construccion falla (OpenAI caido), no queda un indice a medias: el
siguiente `buscar` lo vuelve a intentar.

LangChain queda entero adentro de este archivo. `_EmbeddingsDelPuerto` es el
puente: LangChain pide su propia interfaz `Embeddings`, y se la damos
envolviendo el `ProveedorDeEmbeddings` del proyecto -- asi el adaptador de
OpenAI no depende de LangChain, y este buscador no depende de OpenAI.
"""

from __future__ import annotations

import threading
from typing import Sequence

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from ....puertos.recuperacion import DocumentoFuente, FragmentoRecuperado, ProveedorDeEmbeddings

TAMANO_FRAGMENTO_POR_DEFECTO = 900
SOLAPAMIENTO_POR_DEFECTO = 150
_ENCABEZADOS = [("#", "h1"), ("##", "h2"), ("###", "h3")]


class _EmbeddingsDelPuerto(Embeddings):
    def __init__(self, proveedor: ProveedorDeEmbeddings) -> None:
        self._proveedor = proveedor

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._proveedor.embeber_documentos(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._proveedor.embeber_consulta(text)


class BuscadorDocumentalLangChain:
    """Implementa `puertos.recuperacion.BuscadorDocumental`."""

    def __init__(
        self,
        documentos: Sequence[DocumentoFuente],
        embeddings: ProveedorDeEmbeddings,
        tamano_fragmento: int = TAMANO_FRAGMENTO_POR_DEFECTO,
        solapamiento: int = SOLAPAMIENTO_POR_DEFECTO,
    ) -> None:
        if tamano_fragmento < 1 or not 0 <= solapamiento < tamano_fragmento:
            raise ValueError(
                f"fragmentacion invalida: tamano={tamano_fragmento}, solapamiento={solapamiento}"
            )
        self._embeddings = _EmbeddingsDelPuerto(embeddings)
        self._fragmentos = fragmentar(documentos, tamano_fragmento, solapamiento)
        self._almacen: InMemoryVectorStore | None = None
        self._lock = threading.Lock()

    @property
    def cantidad_de_fragmentos(self) -> int:
        return len(self._fragmentos)

    @property
    def indexado(self) -> bool:
        return self._almacen is not None

    def buscar(self, consulta: str, limite: int = 4) -> list[FragmentoRecuperado]:
        if limite < 1:
            raise ValueError(f"limite invalido: {limite}")
        consulta = consulta.strip()
        if not consulta or not self._fragmentos:
            return []
        resultados = self._indice().similarity_search_with_score(consulta, k=limite)
        return [
            FragmentoRecuperado(
                fuente=documento.metadata["fuente"],
                seccion=documento.metadata["seccion"],
                texto=documento.page_content,
                puntaje=float(puntaje),
            )
            for documento, puntaje in resultados
        ]

    def _indice(self) -> InMemoryVectorStore:
        # Lock: `entradas/api/` atiende turnos en un threadpool, y dos
        # preguntas de soporte simultaneas al arrancar no deberian embeber
        # el corpus dos veces.
        with self._lock:
            if self._almacen is None:
                almacen = InMemoryVectorStore(embedding=self._embeddings)
                almacen.add_documents(
                    list(self._fragmentos),
                    ids=[d.metadata["id"] for d in self._fragmentos],
                )
                # Se asigna recien si `add_documents` termino: una falla del
                # proveedor (`RecuperacionNoDisponible`) sube sin dejar un
                # indice a medias.
                self._almacen = almacen
            return self._almacen


def fragmentar(
    documentos: Sequence[DocumentoFuente], tamano_fragmento: int, solapamiento: int
) -> tuple[Document, ...]:
    """Primero por encabezados (cada fragmento sabe en que seccion vive),
    despues por tamaño. Los encabezados se conservan dentro del texto
    (`strip_headers=False`) para que un fragmento suelto siga siendo legible."""
    por_encabezado = MarkdownHeaderTextSplitter(_ENCABEZADOS, strip_headers=False)
    por_tamano = RecursiveCharacterTextSplitter(
        chunk_size=tamano_fragmento, chunk_overlap=solapamiento,
    )
    fragmentos: list[Document] = []
    for documento in documentos:
        secciones = por_encabezado.split_text(documento.texto)
        for i, pedazo in enumerate(por_tamano.split_documents(secciones)):
            encabezados = [pedazo.metadata[k] for _, k in _ENCABEZADOS if k in pedazo.metadata]
            pedazo.metadata = {
                "id": f"{documento.fuente}#{i}",
                "fuente": documento.fuente,
                "seccion": " > ".join(encabezados) or documento.titulo,
            }
            fragmentos.append(pedazo)
    return tuple(fragmentos)
