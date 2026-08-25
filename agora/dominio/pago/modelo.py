"""Tipos de pago del dominio.

No contienen red ni SDKs: solo lenguaje comun entre casos de uso y puertos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..comun.dinero import Dinero


class Ambiente(str, Enum):
    SANDBOX = "sandbox"
    PRODUCCION = "produccion"


class Proveedor(str, Enum):
    WOMPI = "wompi"
    # Ciudadano de primera, no un mock (ADR-2, docs/arquitectura-v2.md).
    # Necesita su propio valor: la simulada y Wompi conviven en el mismo
    # proceso, y un MedioDePagoRef no puede fingir que es de otro proveedor.
    SIMULADA = "simulada"


@dataclass(frozen=True)
class MedioDePagoRef:
    proveedor: Proveedor
    ambiente: Ambiente
    id_externo: str

    def to_json(self) -> dict[str, str]:
        return {
            "proveedor": self.proveedor.value,
            "ambiente": self.ambiente.value,
            "id_externo": self.id_externo,
        }


class EstadoCobro(str, Enum):
    PENDIENTE = "PENDING"
    APROBADO = "APPROVED"
    RECHAZADO = "DECLINED"
    ANULADO = "VOIDED"
    ERROR = "ERROR"

    @property
    def es_final(self) -> bool:
        return self is not EstadoCobro.PENDIENTE


@dataclass(frozen=True)
class OrdenDeCobro:
    intencion_id: str
    medio: MedioDePagoRef
    monto: Dinero
    glosa: str
    correo_pagador: str
    datos_pagador: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "intencion_id": self.intencion_id,
            "medio": self.medio.to_json(),
            "monto": self.monto.to_json(),
            "glosa": self.glosa,
            "correo_pagador": self.correo_pagador,
            "datos_pagador": self.datos_pagador,
        }


@dataclass(frozen=True)
class ResultadoCobro:
    estado: EstadoCobro
    id_externo: str = ""
    referencia: str = ""
    status_message: str = ""
    afe_decision: str = ""
    detalle: dict[str, Any] = field(default_factory=dict)

    @property
    def detenido_por_antifraude(self) -> bool:
        return self.afe_decision.upper() == "DECLINE"

    def to_json(self) -> dict[str, Any]:
        return {
            "estado": self.estado.value,
            "id_externo": self.id_externo,
            "referencia": self.referencia,
            "status_message": self.status_message,
            "afe_decision": self.afe_decision,
            "detalle": self.detalle,
        }
