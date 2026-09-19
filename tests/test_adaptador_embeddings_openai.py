"""`AdaptadorEmbeddingsOpenAI` contra un cliente de mentira con la forma
`.embeddings.create(...).data[i].{index,embedding}` -- sin red ni llave real
(mismo criterio que `tests/test_adaptador_deepseek.py`)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from openai import OpenAIError

from agora.adaptadores.embeddings.proveedor_openai import (
    AdaptadorEmbeddingsOpenAI,
    ConfiguracionEmbeddingsOpenAI,
    ConfiguracionInvalida,
)
from agora.dominio.comun.errores import RecuperacionNoDisponible, RespuestaDeEmbeddingsInvalida


class _OpenAICaido(OpenAIError):
    """Cualquier subclase de `OpenAIError` sirve: el adaptador traduce la
    jerarquia entera. No se usa `APIConnectionError` directo porque su
    constructor cambia entre versiones del SDK."""


class _ClienteFalso:
    def __init__(self, *, desordenar: bool = False, faltantes: int = 0, falla: Exception | None = None):
        self.pedidos: list[dict] = []
        self._desordenar = desordenar
        self._faltantes = faltantes
        self._falla = falla
        self.embeddings = SimpleNamespace(create=self._crear)

    def _crear(self, *, model, input):
        self.pedidos.append({"model": model, "input": list(input)})
        if self._falla is not None:
            raise self._falla
        datos = [
            SimpleNamespace(index=i, embedding=[float(len(texto)), float(i)])
            for i, texto in enumerate(input)
        ]
        if self._desordenar:
            datos.reverse()
        if self._faltantes:
            datos = datos[: -self._faltantes]
        return SimpleNamespace(data=datos)


def _adaptador(cliente, **config) -> AdaptadorEmbeddingsOpenAI:
    return AdaptadorEmbeddingsOpenAI(
        ConfiguracionEmbeddingsOpenAI(llave_api="sk-de-prueba", **config), cliente=cliente,
    )


def test_embeber_documentos_devuelve_un_vector_por_texto_en_orden():
    cliente = _ClienteFalso(desordenar=True)
    vectores = _adaptador(cliente).embeber_documentos(["a", "bbb", "cc"])
    assert vectores == [[1.0, 0.0], [3.0, 1.0], [2.0, 2.0]]
    assert cliente.pedidos[0]["model"] == "text-embedding-3-small"


def test_parte_en_lotes_segun_la_configuracion():
    cliente = _ClienteFalso()
    vectores = _adaptador(cliente, lote_maximo=2).embeber_documentos(["a", "b", "c", "d", "e"])
    assert len(vectores) == 5
    assert [len(p["input"]) for p in cliente.pedidos] == [2, 2, 1]


def test_sin_textos_no_llama_a_la_api():
    cliente = _ClienteFalso()
    assert _adaptador(cliente).embeber_documentos([]) == []
    assert cliente.pedidos == []


def test_embeber_consulta_devuelve_un_solo_vector():
    assert _adaptador(_ClienteFalso()).embeber_consulta("hola") == [4.0, 0.0]


def test_un_error_del_sdk_se_traduce_a_recuperacion_no_disponible():
    adaptador = _adaptador(_ClienteFalso(falla=_OpenAICaido("timeout")))
    with pytest.raises(RecuperacionNoDisponible) as exc:
        adaptador.embeber_consulta("hola")
    assert exc.value.reintentable


def test_menos_vectores_que_textos_es_respuesta_invalida():
    with pytest.raises(RespuestaDeEmbeddingsInvalida):
        _adaptador(_ClienteFalso(faltantes=1)).embeber_documentos(["a", "b"])


def test_un_vector_vacio_es_respuesta_invalida():
    cliente = _ClienteFalso()
    cliente.embeddings = SimpleNamespace(
        create=lambda **_: SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[])])
    )
    with pytest.raises(RespuestaDeEmbeddingsInvalida):
        _adaptador(cliente).embeber_consulta("hola")


def test_sin_llave_no_se_puede_configurar():
    with pytest.raises(ConfiguracionInvalida, match="OPENAI_API_KEY"):
        ConfiguracionEmbeddingsOpenAI(llave_api="")


def test_construir_el_adaptador_real_no_toca_la_red():
    """Sin cliente inyectado se arma un `OpenAI` de verdad -- y eso no hace
    ninguna peticion hasta que alguien pide un embedding."""
    adaptador = AdaptadorEmbeddingsOpenAI(ConfiguracionEmbeddingsOpenAI(llave_api="sk-de-prueba"))
    assert adaptador.nombre == "openai"
