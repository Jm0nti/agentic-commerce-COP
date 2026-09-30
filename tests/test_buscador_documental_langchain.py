"""`BuscadorDocumentalLangChain` con un proveedor de embeddings de mentira
(bolsa de palabras con hash): deterministico, sin red, y suficiente para que
"quien firma" quede mas cerca de la seccion de firma que de la de pagos."""

from __future__ import annotations

import hashlib
import unicodedata

import pytest

from agora.adaptadores.recuperacion.langchain_en_memoria import BuscadorDocumentalLangChain
from agora.model.commons.errores import RecuperacionNoDisponible
from agora.model.agente.gateways.recuperacion import DocumentoFuente

_DIMENSIONES = 128


class _EmbeddingsDeBolsa:
    def __init__(self) -> None:
        self.lotes_de_documentos = 0
        self.consultas = 0
        self.falla: Exception | None = None

    def _vector(self, texto: str) -> list[float]:
        vector = [0.0] * _DIMENSIONES
        normal = "".join(
            c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c)
        )
        for palabra in normal.split():
            palabra = palabra.strip(".,:;¿?¡!()#*")
            if len(palabra) > 3:
                vector[int(hashlib.md5(palabra.encode()).hexdigest(), 16) % _DIMENSIONES] += 1.0
        return vector

    def embeber_documentos(self, textos):
        if self.falla:
            raise self.falla
        self.lotes_de_documentos += 1
        return [self._vector(t) for t in textos]

    def embeber_consulta(self, texto):
        if self.falla:
            raise self.falla
        self.consultas += 1
        return self._vector(texto)


_DOCUMENTOS = [
    DocumentoFuente(
        fuente="docs/soporte/compra.md",
        titulo="Compra",
        texto=(
            "# Compra\n\n"
            "## Firma\nLa persona titular firma el mandato con su llave; el asistente no firma.\n\n"
            "## Pago\nCon el mandato firmado, la boveda cobra al comercio autorizado.\n"
        ),
    ),
    DocumentoFuente(
        fuente="docs/soporte/medios.md",
        titulo="Medios",
        texto="Vincular Nequi se hace desde la app, aceptando la notificacion del celular.",
    ),
]


def test_fragmenta_al_construir_pero_no_embebe_hasta_la_primera_busqueda():
    embeddings = _EmbeddingsDeBolsa()
    buscador = BuscadorDocumentalLangChain(_DOCUMENTOS, embeddings)

    assert buscador.cantidad_de_fragmentos == 3
    assert not buscador.indexado
    assert embeddings.lotes_de_documentos == 0


def test_devuelve_el_fragmento_mas_parecido_primero_con_fuente_y_seccion():
    buscador = BuscadorDocumentalLangChain(_DOCUMENTOS, _EmbeddingsDeBolsa())

    resultados = buscador.buscar("quien firma el mandato, la persona titular?", limite=2)

    assert len(resultados) == 2
    primero = resultados[0]
    assert primero.fuente == "docs/soporte/compra.md"
    assert primero.seccion == "Compra > Firma"
    assert "firma el mandato" in primero.texto
    assert resultados[0].puntaje >= resultados[1].puntaje


def test_un_documento_sin_encabezados_usa_su_titulo_como_seccion():
    buscador = BuscadorDocumentalLangChain(_DOCUMENTOS, _EmbeddingsDeBolsa())
    resultado = buscador.buscar("vincular nequi notificacion celular", limite=1)[0]
    assert resultado.fuente == "docs/soporte/medios.md"
    assert resultado.seccion == "Medios"


def test_el_indice_se_arma_una_sola_vez():
    embeddings = _EmbeddingsDeBolsa()
    buscador = BuscadorDocumentalLangChain(_DOCUMENTOS, embeddings)

    buscador.buscar("firma")
    buscador.buscar("pago")

    assert embeddings.lotes_de_documentos == 1
    assert embeddings.consultas == 2


def test_si_el_proveedor_falla_al_indexar_no_queda_un_indice_a_medias():
    embeddings = _EmbeddingsDeBolsa()
    embeddings.falla = RecuperacionNoDisponible("OpenAI caido")
    buscador = BuscadorDocumentalLangChain(_DOCUMENTOS, embeddings)

    with pytest.raises(RecuperacionNoDisponible):
        buscador.buscar("firma")
    assert not buscador.indexado

    embeddings.falla = None
    assert buscador.buscar("firma")
    assert buscador.indexado


def test_consulta_vacia_o_corpus_vacio_no_llaman_al_proveedor():
    embeddings = _EmbeddingsDeBolsa()
    assert BuscadorDocumentalLangChain(_DOCUMENTOS, embeddings).buscar("   ") == []
    assert BuscadorDocumentalLangChain([], embeddings).buscar("firma") == []
    assert embeddings.lotes_de_documentos == 0 and embeddings.consultas == 0


def test_limite_y_fragmentacion_invalidos_se_rechazan():
    with pytest.raises(ValueError):
        BuscadorDocumentalLangChain(_DOCUMENTOS, _EmbeddingsDeBolsa()).buscar("firma", limite=0)
    with pytest.raises(ValueError):
        BuscadorDocumentalLangChain(_DOCUMENTOS, _EmbeddingsDeBolsa(), tamano_fragmento=100, solapamiento=100)


def test_un_documento_largo_se_parte_en_varios_fragmentos_de_la_misma_seccion():
    largo = DocumentoFuente(
        fuente="docs/soporte/largo.md", titulo="Largo",
        texto="# Largo\n\n" + ("Una oracion sobre mandatos y firmas. " * 80),
    )
    buscador = BuscadorDocumentalLangChain([largo], _EmbeddingsDeBolsa(), tamano_fragmento=300, solapamiento=50)
    assert buscador.cantidad_de_fragmentos > 1
    assert {f.seccion for f in buscador.buscar("mandatos firmas", limite=10)} == {"Largo"}
