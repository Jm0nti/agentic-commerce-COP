"""Reloj, identificadores y bitacora.

Parecen ceremonia y no lo son. Si el dominio llamara a `datetime.now` y a
`uuid4` directo, probar un vencimiento obligaria a trucos como emitir un
mandato con vigencia negativa.

Con el tiempo como parametro, la prueba dice lo que quiere decir.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class Reloj(Protocol):
    def ahora(self) -> datetime: ...


class GeneradorIds(Protocol):
    def nuevo(self, prefijo: str = "") -> str: ...


class Bitacora(Protocol):
    """Auditoria, no logging.

    Registra decisiones, no diagnostico. Lo que escribe aqui es la evidencia
    del experimento: `recibos.jsonl` no es un log de aplicacion, es el
    resultado, y por eso el original nunca se sobreescribe ni se rota.
    """

    def anotar(self, evento: str, cuerpo: Any) -> None: ...
