"""El mandato: la autorizacion firmada que limita lo que el agente puede cobrar.

Dos decisiones de forma que tocan la carga firmada:

    medio: MedioDePagoRef     el dominio no conoce a Wompi: una referencia
                              opaca (proveedor, ambiente, id_externo)
    monto_max: Dinero         unidad explicita, nunca un int suelto

El mandato lleva su `version` DENTRO de la carga firmada (hoy, 2): una carga
firmada nunca se puede reinterpretar bajo otras reglas, aunque cambie el
modelo.

LO QUE EL MANDATO PROTEGE Y LO QUE NO
-------------------------------------
Protege contra un comercio que cobra distinto de lo pactado y contra un agente
que intenta gastar de mas.

No protege contra un agente al que convencieron de pedir otra cosa. Si la
intencion cabe dentro del mandato, el mandato la deja pasar: para eso se firmo.
Ese caso lo atrapa `politica.CONFIRMAR` o un motor de riesgo, no la firma.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from ..commons.dinero import CERO, Dinero
from ..pago.modelo import MedioDePagoRef
from .gateways.firma import Verificador

VERSION = 2


@dataclass
class Consumo:
    """Cuanto se ha usado ya. Vive fuera del mandato a proposito: el mandato es
    inmutable y firmado, el consumo cambia con cada cobro."""

    usos: int = 0
    acumulado: Dinero = CERO


@dataclass(frozen=True)
class Violacion:
    tipo: str
    detalle: str

    def to_json(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class Intencion:
    """Lo que el agente pide. Nunca lleva credenciales, solo el mandato_id."""

    intencion_id: str
    mandato_id: str
    comercio_id: str
    carrito_id: str
    monto: Dinero
    descripcion: str = ""
    categoria: str = ""
    turno_id: str | None = None  # el hilo hasta el chat que lo origino


@dataclass(frozen=True)
class Mandato:
    mandato_id: str
    titular_id: str
    medio: MedioDePagoRef
    comercio_id: str
    monto_max: Dinero
    tope_total: Dinero
    usos_max: int
    expira_en: datetime
    creado_en: datetime
    llave_publica: bytes
    categorias: tuple[str, ...] = ()
    carrito_hash: str | None = None
    version: int = VERSION
    firma: bytes = b""

    # -- carga canonica ----------------------------------------------------- #

    def canonico(self) -> bytes:
        """Serializacion estable. Ordenada, sin la firma, con la version dentro.

        La version va DENTRO de la carga: si no, alguien podria tomar una carga
        firmada bajo otra version y presentarla como de esta sin romper la firma.
        """
        d = {
            "version": self.version,
            "mandato_id": self.mandato_id,
            "titular_id": self.titular_id,
            "medio": self.medio.to_json(),
            "comercio_id": self.comercio_id,
            "monto_max": self.monto_max.to_json(),
            "tope_total": self.tope_total.to_json(),
            "usos_max": self.usos_max,
            "expira_en": self.expira_en.isoformat(),
            "creado_en": self.creado_en.isoformat(),
            "categorias": sorted(self.categorias),
            "carrito_hash": self.carrito_hash,
            "llave_publica": self.llave_publica.hex(),
        }
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def vencido(self, ahora: datetime) -> bool:
        return self.expira_en < ahora

    # -- evaluacion --------------------------------------------------------- #

    def violaciones_contra(
        self,
        intencion: Intencion,
        consumo: Consumo,
        verificador: Verificador,
        ahora: datetime | None = None,
        carrito_hash: str | None = None,
        llave_publica: bytes = b"",
    ) -> list[Violacion]:
        """Todas las divergencias verificables. Categorico, no probabilistico.

        `llave_publica` se ignora: el mandato lleva la suya adentro y dentro de
        la firma, que es lo correcto. El parametro es vestigial -- se puede
        quitar cuando se toque esta firma.
        """
        v: list[Violacion] = []
        ahora = ahora or datetime.now(self.expira_en.tzinfo)

        if not self.firma or not verificador.verifica(
            self.firma, self.canonico(), self.llave_publica
        ):
            v.append(Violacion("firma_invalida", "el mandato no valida"))

        if intencion.mandato_id != self.mandato_id:
            v.append(Violacion("mandato_ajeno", "la intencion cita otro mandato"))

        if self.vencido(ahora):
            v.append(Violacion("vencido", f"expiro el {self.expira_en.isoformat()}"))

        if intencion.comercio_id != self.comercio_id:
            v.append(
                Violacion(
                    "comercio_no_autorizado",
                    f"autoriza a {self.comercio_id}, la intencion paga a "
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
                    f"permite {self.usos_max} uso(s) y lleva {consumo.usos}",
                )
            )

        if self.categorias and intencion.categoria not in self.categorias:
            v.append(
                Violacion(
                    "categoria_no_autorizada",
                    f"'{intencion.categoria}' no esta en {list(self.categorias)}",
                )
            )

        # Solo para mandatos atados a un carrito concreto (el Cart Mandate de
        # AP2). Alterar el carrito despues de firmar rompe aqui.
        if self.carrito_hash and carrito_hash != self.carrito_hash:
            v.append(
                Violacion("carrito_alterado", "el carrito cambio despues de la firma")
            )

        return v


@dataclass(frozen=True)
class PropuestaDeMandato:
    """Lo que el AGENTE pide. Todavia no lo firmo nadie.

    Existe como tipo propio para que sea imposible confundirla con un mandato:
    no tiene firma, no tiene llave publica, y ningun caso de uso la acepta donde
    espera un `Mandato`. La frontera entre proponer y autorizar queda en el
    sistema de tipos, no en la disciplina de quien escribe.
    """

    propuesta_id: str
    carrito_id: str
    comercio_id: str
    monto_max: Dinero
    usos_max: int = 1
    vigencia_minutos: int = 30
    categorias: tuple[str, ...] = ()
    justificacion: str = ""
