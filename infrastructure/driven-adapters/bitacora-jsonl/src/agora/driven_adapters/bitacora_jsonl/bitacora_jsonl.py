"""Bitacora de auditoria en `.jsonl`, en la convencion del repo.

No es logging: es evidencia. La bitacora de cobros (`agora_datos/recibos.jsonl`)
es donde queda registrado el hallazgo central de la PoC -- un cobro `APPROVED`
pese a violar el mandato -- y por eso nunca se sobreescribe ni se rota.

Cada linea es un evento independiente (`{"ts", "evento", "cuerpo"}`),
append-only, sin buffer: si el proceso muere a mitad de una corrida, las
lineas ya escritas siguen siendo validas.
"""

from __future__ import annotations

import dataclasses
import json
import threading
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ...model.commons.gateways.sistema import Reloj


def _serializable(valor: Any) -> Any:
    """Convierte cualquier cosa razonable del dominio a JSON.

    `dataclasses.asdict` ya recorre dataclasses anidados (Recibo -> Intencion
    -> Dinero, Dictamen -> [Violacion]). Lo que falta es lo que asdict deja tal
    cual: Enum, datetime y bytes. Los Enum de tipo `str` (Ambiente, EstadoCobro)
    ya son serializables solos; esto es para no romper si alguna vez dejan de
    serlo, o si aparece un campo `datetime`/`bytes` nuevo.
    """
    if dataclasses.is_dataclass(valor) and not isinstance(valor, type):
        return {k: _serializable(v) for k, v in dataclasses.asdict(valor).items()}
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, bytes):
        return valor.hex()
    if isinstance(valor, dict):
        return {k: _serializable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_serializable(v) for v in valor]
    return valor


class BitacoraJsonl:
    """Implementa `puertos.sistema.Bitacora`."""

    def __init__(self, ruta: Path, reloj: Reloj) -> None:
        self._ruta = ruta
        self._reloj = reloj
        self._lock = threading.Lock()

    def anotar(self, evento: str, cuerpo: Any) -> None:
        registro = {
            "ts": self._reloj.ahora().isoformat(timespec="seconds"),
            "evento": evento,
            "cuerpo": _serializable(cuerpo),
        }
        linea = json.dumps(registro, ensure_ascii=False)
        with self._lock:
            self._ruta.parent.mkdir(parents=True, exist_ok=True)
            with self._ruta.open("a", encoding="utf-8") as f:
                f.write(linea + "\n")
