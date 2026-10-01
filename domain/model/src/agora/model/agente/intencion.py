"""La intencion de un mensaje, con schema -- no texto libre.

Migracion a agentes, etapa 1 (`docs/arquitectura-agentes-langgraph.md`,
"Migracion incremental", paso 1): separar DECIDIR a que dominio pertenece un
mensaje de EJECUTAR el turno. Este modulo es solo el contrato de esa
decision; quien la toma vive en `agente/clasificacion/`, y que significa
cada intencion en terminos de herramientas vive en `agente/nodos.py`.

POR QUE EN `agente/` Y NO EN `dominio/` NI EN `puertos/`
----------------------------------------------------------
"El mensaje es sobre el estado de un pago" es un concepto de la
conversacion, no del negocio: un `Mandato` o una `Intencion` de pago
(`dominio/mandato/modelo.py`) existen igual sin chat. Por eso no va en
`dominio/`. Tampoco hace falta un puerto nuevo: ninguna libreria externa
entra en esta etapa -- el clasificador con modelo usa el puerto que ya
existe (`ModeloDeLenguaje.generar`), y `ClasificadorDeIntencion` es una
estrategia interna del agente, igual que el loop de turnos. El puerto que
aisle LangGraph llega en la etapa 3, cuando LangGraph llegue.

`TipoDeIntencion` y no `Intencion` a secas: `dominio.mandato.modelo.
Intencion` (una intencion de PAGO) ya existe y `composicion/agente.py`
importa las dos.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence

from .gateways.modelo_lenguaje import Mensaje


class TipoDeIntencion(str, Enum):
    """Las seis salidas del orquestador (decision 3 del documento). Un
    saludo o un agradecimiento cae en `FUERA_DE_ALCANCE`: no hay ninguna
    herramienta de dominio que aplique, y eso es lo unico que esta categoria
    afirma -- no que el mensaje este mal."""

    CATALOGO = "catalogo"
    CARRITO_PAGO = "carrito_pago"
    MEDIOS_DE_PAGO = "medios_de_pago"
    ESTADO = "estado"
    SOPORTE = "soporte"
    FUERA_DE_ALCANCE = "fuera_de_alcance"


class OrigenDeClasificacion(str, Enum):
    """Quien decidio. `RESPALDO` no es una intencion: es "nadie pudo
    decidir con suficiente certeza", y lleva al turno por la ruta de
    respaldo (`agente/nodos.py:RUTA_DE_RESPALDO`) -- el comportamiento
    exacto de antes de esta etapa."""

    REGLAS = "reglas"
    MODELO = "modelo"
    RESPALDO = "respaldo"


@dataclass(frozen=True)
class ClasificacionDeIntencion:
    intencion: TipoDeIntencion | None
    origen: OrigenDeClasificacion
    confianza: float
    motivo: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confianza <= 1.0:
            raise ValueError(f"confianza fuera de [0, 1]: {self.confianza}")
        # Las dos formas validas, y ninguna otra: una clasificacion decidida
        # siempre trae intencion; un respaldo nunca la trae. Sin esto, un
        # "respaldo con intencion=pagar" podria colarse y nadie sabria cual
        # de los dos campos manda.
        if (self.intencion is None) != (self.origen is OrigenDeClasificacion.RESPALDO):
            raise ValueError(
                "intencion=None si y solo si origen=respaldo "
                f"(llego intencion={self.intencion}, origen={self.origen})"
            )

    @classmethod
    def respaldo(cls, motivo: str) -> "ClasificacionDeIntencion":
        return cls(
            intencion=None, origen=OrigenDeClasificacion.RESPALDO, confianza=0.0, motivo=motivo,
        )

    @property
    def decidida(self) -> bool:
        return self.origen is not OrigenDeClasificacion.RESPALDO

    def to_json(self) -> dict[str, object]:
        return {
            "intencion": self.intencion.value if self.intencion else None,
            "origen": self.origen.value,
            "confianza": round(self.confianza, 3),
            "motivo": self.motivo,
        }


class ClasificadorDeIntencion(Protocol):
    def clasificar(
        self, mensaje: str, historial: Sequence[Mensaje] = ()
    ) -> ClasificacionDeIntencion:
        """Decide a que dominio pertenece `mensaje` (el ultimo de la
        persona). `historial` son los mensajes ANTERIORES de la charla --
        sin incluir `mensaje` -- para que un "si, dale" pueda leerse como la
        continuacion de lo que se venia hablando.

        Nunca levanta por no poder decidir: devuelve
        `ClasificacionDeIntencion.respaldo(motivo)`. Un turno de chat no se
        cae porque el clasificador no este seguro."""
        ...
