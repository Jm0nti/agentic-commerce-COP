"""`RepositorioMedios` en memoria.

No lo usa `EjecutarIntencion` (que solo necesita el `MedioDePagoRef` que ya
trae el mandato firmado), pero completa el puerto para cuando
`aplicacion/enrolar_medio.py` exista (etapa 5) y lo necesite para listar los
medios vivos de un titular.

Multi-comercio: cada medio guarda tambien bajo que `comercio_id` se enrolo
-- ver el docstring de `puertos.repositorios.RepositorioMedios`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ....dominio.pago.modelo import Ambiente, MedioDePagoRef


@dataclass
class _MedioRegistrado:
    ref: MedioDePagoRef
    titular_id: str
    comercio_id: str
    estado: str = "AVAILABLE"


class RepositorioMediosEnMemoria:
    """Implementa `puertos.repositorios.RepositorioMedios`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._medios: list[_MedioRegistrado] = []

    def guardar(self, ref: MedioDePagoRef, titular_id: str, comercio_id: str) -> None:
        with self._lock:
            self._medios.append(
                _MedioRegistrado(ref=ref, titular_id=titular_id, comercio_id=comercio_id)
            )

    def vivos(self, titular_id: str, ambiente: Ambiente) -> list[MedioDePagoRef]:
        with self._lock:
            return [
                m.ref
                for m in self._medios
                if m.titular_id == titular_id
                and m.ref.ambiente == ambiente
                and m.estado == "AVAILABLE"
            ]

    def vinculado_con(
        self, titular_id: str, comercio_id: str, ambiente: Ambiente
    ) -> MedioDePagoRef | None:
        with self._lock:
            # El mas reciente: mismo criterio que `EmitirMandato` usaba para
            # "el ultimo enrolado" antes de que existiera este metodo --
            # `_medios` agrega al final, asi que se recorre al reves.
            for m in reversed(self._medios):
                if (
                    m.titular_id == titular_id
                    and m.comercio_id == comercio_id
                    and m.ref.ambiente == ambiente
                    and m.estado == "AVAILABLE"
                ):
                    return m.ref
            return None

    def comercio_de(self, ref: MedioDePagoRef) -> str | None:
        with self._lock:
            for m in self._medios:
                if m.ref == ref:
                    return m.comercio_id
            return None

    def marcar_estado(self, ref: MedioDePagoRef, estado: str) -> None:
        with self._lock:
            for m in self._medios:
                if m.ref == ref:
                    m.estado = estado
