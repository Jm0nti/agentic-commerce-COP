"""Implementa `puertos.recuperacion.ProveedorDeEmbeddings` contra la API de
embeddings de OpenAI, con el SDK `openai` (el mismo que ya usa
`adaptadores/llm/deepseek/`).

Usa el SDK directo y no `langchain_openai.OpenAIEmbeddings`: LangChain entra
en esta etapa solo donde aporta algo (fragmentar Markdown y el vector store,
`adaptadores/recuperacion/langchain_en_memoria/`). Envolver un SDK que ya es
dependencia del proyecto en otra capa de LangChain sumaria un paquete mas
sin quitar nada.

`cliente` se puede inyectar -- mismo patron que `AdaptadorDeepSeek` -- para
que las pruebas no necesiten red ni una llave real. Solo se le pide la
forma `.embeddings.create(model=..., input=[...]).data[i].{index,embedding}`.
"""

from __future__ import annotations

from typing import Any, Sequence

from openai import OpenAI, OpenAIError

from ....dominio.comun.errores import RecuperacionNoDisponible, RespuestaDeEmbeddingsInvalida
from .config import ConfiguracionEmbeddingsOpenAI


class AdaptadorEmbeddingsOpenAI:
    """Implementa `puertos.recuperacion.ProveedorDeEmbeddings`."""

    nombre = "openai"

    def __init__(self, config: ConfiguracionEmbeddingsOpenAI, cliente: Any | None = None) -> None:
        self._config = config
        # Construir el cliente no toca la red: la primera peticion sale
        # recien cuando alguien busca en la documentacion.
        self._cliente = cliente or OpenAI(api_key=config.llave_api, timeout=config.timeout_segundos)

    def embeber_documentos(self, textos: Sequence[str]) -> list[list[float]]:
        vectores: list[list[float]] = []
        lote = self._config.lote_maximo
        for inicio in range(0, len(textos), lote):
            vectores.extend(self._pedir(list(textos[inicio : inicio + lote])))
        return vectores

    def embeber_consulta(self, texto: str) -> list[float]:
        return self._pedir([texto])[0]

    def _pedir(self, textos: list[str]) -> list[list[float]]:
        try:
            respuesta = self._cliente.embeddings.create(model=self._config.modelo, input=textos)
        except OpenAIError as exc:
            # Red, timeout, 5xx, llave invalida: la jerarquia del SDK se
            # traduce a la nuestra, igual que `AdaptadorDeepSeek`. El mensaje
            # del SDK no incluye la llave.
            raise RecuperacionNoDisponible(f"OpenAI (embeddings) no respondio: {exc}") from exc

        datos = sorted(getattr(respuesta, "data", None) or [], key=lambda d: d.index)
        if len(datos) != len(textos):
            raise RespuestaDeEmbeddingsInvalida(
                f"OpenAI devolvio {len(datos)} vectores para {len(textos)} textos",
                detalle_proveedor={"modelo": self._config.modelo},
            )
        vectores = [list(d.embedding) for d in datos]
        if any(not v for v in vectores):
            raise RespuestaDeEmbeddingsInvalida(
                "OpenAI devolvio un vector vacio",
                detalle_proveedor={"modelo": self._config.modelo},
            )
        return vectores
