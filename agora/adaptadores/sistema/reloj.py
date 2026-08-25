"""El reloj real. La unica implementacion que llama a `datetime.now`.

Todo lo demas del dominio y de aplicacion recibe la hora como parametro
(ver `puertos/sistema.py`). Este adaptador es el unico sitio autorizado a
consultar el reloj del sistema operativo.
"""

from __future__ import annotations

from datetime import datetime, timezone


class RelojDelSistema:
    """Implementa `puertos.sistema.Reloj`."""

    def ahora(self) -> datetime:
        return datetime.now(timezone.utc)
