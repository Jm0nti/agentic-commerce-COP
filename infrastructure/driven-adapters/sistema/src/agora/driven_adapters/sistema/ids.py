"""Generador de identificadores real. La unica implementacion que llama `uuid4`.

`GeneradorIds.nuevo(prefijo)` deja el prefijo a cargo de quien pide el id, para
que coincida con las convenciones de `model/commons/identidad.py` (`mnd_`,
`int_`, `rsv_`, ...) sin que este adaptador tenga que conocerlas todas.
"""

from __future__ import annotations

import uuid


class GeneradorIdsUuid:
    """Implementa `puertos.sistema.GeneradorIds`."""

    def nuevo(self, prefijo: str = "") -> str:
        cuerpo = uuid.uuid4().hex[:12]
        return f"{prefijo}_{cuerpo}" if prefijo else cuerpo
