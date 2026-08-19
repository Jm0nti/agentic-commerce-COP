"""El mandato: lo que el titular autoriza, firmado, antes de que exista la compra.

Wompi no tiene este concepto. Una fuente de pago autoriza al comercio a cobrar
y punto: sin techo, sin vencimiento, sin ligadura a un producto. El ledger del
banco de pruebas lo muestra sin ambiguedad -- una sola suscripcion y despues
cobros de 67.450, 88.300 y 17.400 COP, ninguno autorizado por separado, los
tres aprobados.

El mandato es la capa que falta. Se firma con ed25519 sobre una carga
canonica, y despues cada intencion del agente se compara contra el. La firma
importa porque el mandato tiene que sobrevivir el paso por manos del agente sin
que el agente pueda ampliarlo.

LO QUE EL MANDATO SI PROTEGE Y LO QUE NO
----------------------------------------
Protege contra un comercio que cobra distinto de lo pactado, y contra un agente
que intenta gastar de mas.

No protege contra un agente al que convencieron de pedir otra cosa. Si la
intencion cabe dentro del mandato, el mandato la deja pasar -- para eso se
firmo. Un agente manipulado que compra el producto equivocado a un comercio
autorizado no produce ninguna violacion, porque no la hay. Ese caso solo lo
atrapa un motor de riesgo, y conviene tenerlo claro antes de presentar el
mandato como control.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature


def ahora() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #


@dataclass
class Mandato:
    """Autorizacion del titular. Todo lo que el agente puede hacer cabe aqui."""

    mandato_id: str
    titular: str
    # La fuente de pago de Wompi. El agente nunca ve este numero: vive en la
    # boveda y el agente solo referencia el mandato_id.
    fuente_pago: int
    comercio: str
    monto_max_cop: int  # por transaccion
    tope_total_cop: int  # acumulado durante la vida del mandato
    usos_max: int
    expira_en: str  # ISO-8601
    creado_en: str
    categorias: list[str] = field(default_factory=list)  # vacio = sin restriccion
    firma: str = ""

    # -- firma -------------------------------------------------------------- #

    def carga(self) -> bytes:
        """Serializacion canonica. Ordenada y sin la firma, obviamente."""
        d = {k: v for k, v in asdict(self).items() if k != "firma"}
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def firmar(self, sk: Ed25519PrivateKey) -> Mandato:
        self.firma = sk.sign(self.carga()).hex()
        return self

    def verificar(self, pk: Ed25519PublicKey) -> bool:
        if not self.firma:
            return False
        try:
            pk.verify(bytes.fromhex(self.firma), self.carga())
            return True
        except (InvalidSignature, ValueError):
            return False

    # -- serializacion ------------------------------------------------------ #

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Mandato:
        return cls(**d)

    @property
    def vencido(self) -> bool:
        return datetime.fromisoformat(self.expira_en) < ahora()


@dataclass
class Intencion:
    """Lo que el agente pide. Nunca lleva credenciales, solo el mandato_id."""

    mandato_id: str
    comercio: str
    sku: str
    monto_cop: int
    descripcion: str = ""
    categoria: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Violacion:
    tipo: str
    detalle: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Consumo:
    """Cuanto se ha usado ya de un mandato. Vive en la boveda, no en el mandato.

    Separarlo importa: el mandato es inmutable y firmado, el consumo cambia con
    cada cobro. Si el consumo viviera dentro del mandato, cada cobro invalidaria
    la firma.
    """

    usos: int = 0
    acumulado_cop: int = 0


# --------------------------------------------------------------------------- #


def emitir(
    titular: str,
    fuente_pago: int,
    comercio: str,
    monto_max_cop: int,
    sk: Ed25519PrivateKey,
    tope_total_cop: int | None = None,
    usos_max: int = 1,
    vigencia_min: int = 60,
    categorias: list[str] | None = None,
) -> Mandato:
    """Emite un mandato firmado.

    Los valores por defecto son deliberadamente estrechos: un solo uso, una
    hora de vigencia, tope total igual al monto de una transaccion. Un mandato
    amplio deberia costar escribirlo, no ser lo que sale por omision.
    """
    return Mandato(
        mandato_id=f"mnd_{uuid.uuid4().hex[:12]}",
        titular=titular,
        fuente_pago=fuente_pago,
        comercio=comercio,
        monto_max_cop=monto_max_cop,
        tope_total_cop=tope_total_cop if tope_total_cop is not None else monto_max_cop,
        usos_max=usos_max,
        expira_en=(ahora() + timedelta(minutes=vigencia_min)).isoformat(),
        creado_en=ahora().isoformat(),
        categorias=categorias or [],
    ).firmar(sk)


def evaluar(
    mandato: Mandato, intencion: Intencion, consumo: Consumo, pk: Ed25519PublicKey
) -> list[Violacion]:
    """Todas las divergencias verificables. Categorico, no probabilistico."""
    v: list[Violacion] = []

    if not mandato.verificar(pk):
        v.append(Violacion("firma_invalida", "el mandato no valida contra la llave"))

    if intencion.mandato_id != mandato.mandato_id:
        v.append(Violacion("mandato_ajeno", "la intencion cita otro mandato"))

    if mandato.vencido:
        v.append(Violacion("vencido", f"el mandato expiro el {mandato.expira_en}"))

    if intencion.comercio != mandato.comercio:
        v.append(
            Violacion(
                "comercio_no_autorizado",
                f"autoriza a {mandato.comercio}, la intencion paga a {intencion.comercio}",
            )
        )

    if intencion.monto_cop > mandato.monto_max_cop:
        exceso = intencion.monto_cop - mandato.monto_max_cop
        v.append(
            Violacion(
                "monto_sobre_mandato",
                f"{intencion.monto_cop:,} COP excede el tope de "
                f"{mandato.monto_max_cop:,} COP en {exceso:,}",
            )
        )

    if consumo.acumulado_cop + intencion.monto_cop > mandato.tope_total_cop:
        v.append(
            Violacion(
                "tope_total_agotado",
                f"lleva {consumo.acumulado_cop:,} de {mandato.tope_total_cop:,} COP",
            )
        )

    if consumo.usos >= mandato.usos_max:
        v.append(
            Violacion(
                "usos_agotados",
                f"el mandato permite {mandato.usos_max} uso(s) y lleva {consumo.usos}",
            )
        )

    if mandato.categorias and intencion.categoria not in mandato.categorias:
        v.append(
            Violacion(
                "categoria_no_autorizada",
                f"'{intencion.categoria}' no esta en {mandato.categorias}",
            )
        )

    return v
