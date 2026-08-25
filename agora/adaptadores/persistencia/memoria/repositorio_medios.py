"""`RepositorioMedios` en memoria.

No lo usa `EjecutarIntencion` (que solo necesita el `MedioDePagoRef` que ya
trae el mandato firmado), pero completa el puerto para cuando
`aplicacion/enrolar_medio.py` exista (etapa 5) y lo necesite para listar los
medios vivos de un titular.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ....dominio.pago.modelo import Ambiente, MedioDePagoRef


@dataclass
class _MedioRegistrado:
    ref: MedioDePagoRef
    titular_id: str
    estado: str = "AVAILABLE"


class RepositorioMediosEnMemoria:
    """Implementa `puertos.repositorios.RepositorioMedios`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._medios: list[_MedioRegistrado] = []

    def guardar(self, ref: MedioDePagoRef, titular_id: str) -> None:
        with self._lock:
            self._medios.append(_MedioRegistrado(ref=ref, titular_id=titular_id))

    def vivos(self, titular_id: str, ambiente: Ambiente) -> list[MedioDePagoRef]:
        with self._lock:
            return [
                m.ref
                for m in self._medios
                if m.titular_id == titular_id
                and m.ref.ambiente == ambiente
                and m.estado == "AVAILABLE"
            ]

    def marcar_estado(self, ref: MedioDePagoRef, estado: str) -> None:
        with self._lock:
            for m in self._medios:
                if m.ref == ref:
                    m.estado = estado
