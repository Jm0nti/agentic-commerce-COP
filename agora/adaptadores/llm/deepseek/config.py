"""Configuracion de DeepSeek, leida UNA vez en `composicion/` (o en el script
que corre la generacion) y pasada por constructor -- mismo patron que
`adaptadores/pasarelas/wompi/config.py`.

DeepSeek expone una API compatible con Chat Completions de OpenAI
(`docs/arquitectura-v2.md`, seccion 4), asi que el adaptador usa el SDK
`openai` apuntado a otro `base_url` en vez de un cliente HTTP a mano.
"""

from __future__ import annotations

from dataclasses import dataclass

URL_BASE_POR_DEFECTO = "https://api.deepseek.com"
MODELO_POR_DEFECTO = "deepseek-chat"


class ConfiguracionInvalida(ValueError):
    """Falta la llave. DeepSeek no tiene el problema de Wompi de que el
    ambiente y el prefijo de la llave tengan que coincidir -- una sola
    llave sirve para todo, no hay sandbox separado."""


@dataclass(frozen=True)
class ConfiguracionDeepSeek:
    llave_api: str
    modelo: str = MODELO_POR_DEFECTO
    url_base: str = URL_BASE_POR_DEFECTO
    timeout_segundos: float = 60.0

    def __post_init__(self) -> None:
        if not self.llave_api:
            raise ConfiguracionInvalida(
                "falta DEEPSEEK_API_KEY -- sin ella no se puede generar "
                "catalogo simulado con DeepSeek"
            )
