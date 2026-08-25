"""Lector y verificador de mandatos v1.

POR QUE EXISTE
--------------
`boveda/secretos/estado.json` tiene mandatos reales firmados con el formato v1,
y `boveda/recibos.jsonl` tiene el resultado del experimento: un cobro de 15.000
COP aprobado contra un mandato que autorizaba 8.000, con tres violaciones
anotadas.

Eso no es un log de aplicacion. Es la evidencia, y una evidencia que no se puede
reverificar no vale como evidencia. Si dentro de un ano alguien pregunta "como
saben que ese mandato decia 8.000", la respuesta tiene que ser "aqui esta la
firma y aqui el verificador", no "confien en el archivo".

QUE NO HACE
-----------
**No convierte un v1 en un v2 firmado.** No se puede: la carga canonica cambio
(`fuente_pago: int` paso a `medio: MedioDePagoRef`, los montos pasaron a
`Dinero`), y reescribirla romperia la firma. Cualquier funcion que ofreciera
"migrar" un mandato firmado estaria mintiendo.

Un `MandatoV1` se lee, se verifica y se evalua con las reglas v1. Se acabo. Los
mandatos nuevos nacen v2.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..comun.dinero import Dinero
from .modelo import Consumo, Intencion, Verificador, Violacion

VERSION = 1


@dataclass(frozen=True)
class MandatoV1:
    """Espejo exacto de `boveda/mandato.py:Mandato`.

    Los nombres de los campos y su orden en la carga canonica NO se pueden
    tocar: son parte de lo que se firmo.
    """

    mandato_id: str
    titular: str
    fuente_pago: int
    comercio: str
    monto_max_cop: int
    tope_total_cop: int
    usos_max: int
    expira_en: str
    creado_en: str
    categorias: list[str] = field(default_factory=list)
    firma: str = ""

    version: int = VERSION

    # -- carga canonica v1 --------------------------------------------------- #

    def canonico(self) -> bytes:
        """Reproduce byte a byte lo que firmo `boveda/mandato.py:carga`.

        Aquel construia el dict con `asdict(self)` menos `firma`, que en un
        dataclass respeta el orden de declaracion; aqui se escribe explicito
        porque `sort_keys=True` lo reordena igual y depender de un detalle de
        `dataclasses` para validar firmas seria fragil.
        """
        d = {
            "mandato_id": self.mandato_id,
            "titular": self.titular,
            "fuente_pago": self.fuente_pago,
            "comercio": self.comercio,
            "monto_max_cop": self.monto_max_cop,
            "tope_total_cop": self.tope_total_cop,
            "usos_max": self.usos_max,
            "expira_en": self.expira_en,
            "creado_en": self.creado_en,
            "categorias": self.categorias,
        }
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def verifica(self, verificador: Verificador, llave_publica: bytes) -> bool:
        if not self.firma:
            return False
        try:
            return verificador.verifica(
                bytes.fromhex(self.firma), self.canonico(), llave_publica
            )
        except ValueError:
            return False

    # -- montos como Dinero, para poder compararlos con los del v2 ---------- #

    @property
    def monto_max(self) -> Dinero:
        return Dinero.de_pesos(self.monto_max_cop)

    @property
    def tope_total(self) -> Dinero:
        return Dinero.de_pesos(self.tope_total_cop)

    def vencido(self, ahora: datetime) -> bool:
        return datetime.fromisoformat(self.expira_en) < ahora

    # -- evaluacion, con las MISMAS reglas de la v1 ------------------------- #

    def violaciones_contra(
        self,
        intencion: Intencion,
        consumo: Consumo,
        verificador: Verificador,
        ahora: datetime | None = None,
        carrito_hash: str | None = None,
        llave_publica: bytes = b"",
    ) -> list[Violacion]:
        """Misma firma que `Mandato.violaciones_contra` para que `politica.evaluar`
        acepte ambas versiones sin saber cual esta mirando.

        Las reglas son las de la v1, no las de la v2: un mandato se evalua con
        el contrato bajo el cual se firmo. Por eso no hay control de carrito
        aqui -- la v1 no lo tenia, y aplicarselo retroactivamente inventaria
        violaciones que nadie acepto.
        """
        v: list[Violacion] = []
        ahora = ahora or datetime.now(datetime.fromisoformat(self.expira_en).tzinfo)

        if not self.verifica(verificador, llave_publica):
            v.append(Violacion("firma_invalida", "el mandato no valida contra la llave"))

        if intencion.mandato_id != self.mandato_id:
            v.append(Violacion("mandato_ajeno", "la intencion cita otro mandato"))

        if self.vencido(ahora):
            v.append(Violacion("vencido", f"el mandato expiro el {self.expira_en}"))

        if intencion.comercio_id != self.comercio:
            v.append(
                Violacion(
                    "comercio_no_autorizado",
                    f"autoriza a {self.comercio}, la intencion paga a "
                    f"{intencion.comercio_id}",
                )
            )

        if intencion.monto.excede(self.monto_max):
            v.append(
                Violacion(
                    "monto_sobre_mandato",
                    f"{intencion.monto} excede el tope de {self.monto_max}",
                )
            )

        if (consumo.acumulado + intencion.monto).excede(self.tope_total):
            v.append(
                Violacion(
                    "tope_total_agotado",
                    f"lleva {consumo.acumulado} de {self.tope_total}",
                )
            )

        if consumo.usos >= self.usos_max:
            v.append(
                Violacion(
                    "usos_agotados",
                    f"el mandato permite {self.usos_max} uso(s) y lleva {consumo.usos}",
                )
            )

        if self.categorias and intencion.categoria not in self.categorias:
            v.append(
                Violacion(
                    "categoria_no_autorizada",
                    f"'{intencion.categoria}' no esta en {self.categorias}",
                )
            )

        return v


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #


CAMPOS_V1 = {
    "mandato_id", "titular", "fuente_pago", "comercio", "monto_max_cop",
    "tope_total_cop", "usos_max", "expira_en", "creado_en", "categorias", "firma",
}


def es_v1(crudo: dict[str, Any]) -> bool:
    """La v1 no tiene campo `version`; la v2 si, y siempre dentro de la firma."""
    return int(crudo.get("version", VERSION)) == VERSION and "fuente_pago" in crudo


def leer_v1(crudo: dict[str, Any]) -> MandatoV1:
    sobrantes = set(crudo) - CAMPOS_V1 - {"version"}
    if sobrantes:
        raise ValueError(
            f"campos desconocidos en un mandato v1: {sorted(sobrantes)}. "
            "Si el formato cambio, la firma ya no cuadra."
        )
    return MandatoV1(
        mandato_id=crudo["mandato_id"],
        titular=crudo["titular"],
        fuente_pago=int(crudo["fuente_pago"]),
        comercio=crudo["comercio"],
        monto_max_cop=int(crudo["monto_max_cop"]),
        tope_total_cop=int(crudo["tope_total_cop"]),
        usos_max=int(crudo["usos_max"]),
        expira_en=crudo["expira_en"],
        creado_en=crudo["creado_en"],
        categorias=list(crudo.get("categorias") or []),
        firma=crudo.get("firma", ""),
    )


def leer_estado_v1(estado: dict[str, Any]) -> dict[str, MandatoV1]:
    """Todos los mandatos de un `boveda/secretos/estado.json`."""
    return {
        mid: leer_v1(crudo)
        for mid, crudo in (estado.get("mandatos") or {}).items()
        if es_v1(crudo)
    }
