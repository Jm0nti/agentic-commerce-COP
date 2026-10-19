"""Configuracion de los embeddings de OpenAI, leida UNA vez en `app_service/config/`
y pasada por constructor -- mismo patron que `driven_adapters/llm_deepseek/
config.py`.

POR QUE `text-embedding-3-small`
----------------------------------
Es el modelo de embeddings mas barato de OpenAI, maneja español, y el
corpus de soporte es chico (unas decenas de fragmentos): no hay volumen que
justifique `text-embedding-3-large`. Se puede cambiar con
`AGORA_EMBEDDINGS_MODELO` sin tocar codigo -- pero cambiarlo obliga a
reindexar, porque vectores de dos modelos distintos no son comparables
(el indice vive en memoria y se reconstruye al arrancar, asi que en la
practica basta con reiniciar).
"""

from __future__ import annotations

from dataclasses import dataclass

MODELO_POR_DEFECTO = "text-embedding-3-small"


class ConfiguracionInvalida(ValueError):
    pass


@dataclass(frozen=True)
class ConfiguracionEmbeddingsOpenAI:
    llave_api: str
    modelo: str = MODELO_POR_DEFECTO
    timeout_segundos: float = 30.0
    # Cuantos textos por peticion. Muy por debajo del limite de la API: el
    # corpus es chico y un lote menor hace que un error de red pierda menos.
    lote_maximo: int = 64

    def __post_init__(self) -> None:
        if not self.llave_api:
            raise ConfiguracionInvalida(
                "falta OPENAI_API_KEY -- sin ella no hay embeddings para la "
                "documentacion de soporte"
            )
        if self.lote_maximo < 1:
            raise ConfiguracionInvalida(f"lote_maximo invalido: {self.lote_maximo}")
