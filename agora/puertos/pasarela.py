"""El puerto de pagos. Dos implementaciones desde el dia uno.

`adaptadores/pasarelas/wompi/` mueve dinero real.
`adaptadores/pasarelas/simulada/` no, y no es un mock de pruebas: es un
adaptador de produccion para el modo demo.

La simulada tiene que poder reproducir los cuatro desenlaces, incluido el
rechazo por antifraude. Sin eso no se puede mostrar el hallazgo del AFE en una
presentacion sin depender de que Wompi coopere ese dia -- y ese hallazgo es el
resultado mas interesante que tiene la PoC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..dominio.pago.modelo import (
    Ambiente,
    MedioDePagoRef,
    OrdenDeCobro,
    ResultadoCobro,
)


@dataclass(frozen=True)
class SolicitudEnrolamiento:
    telefono: str
    correo: str
    ambiente: Ambiente


@dataclass(frozen=True)
class MedioEnProceso:
    """El token existe; falta que el titular acepte el push.

    Se devuelve de inmediato en vez de bloquear sondeando: quien llame decide
    si espera, si consulta despues, o si le avisa al usuario por otro canal.
    """

    token: str
    estado: str
    ref: MedioDePagoRef | None = None


@dataclass(frozen=True)
class EstadoMedio:
    estado: str
    ref: MedioDePagoRef | None = None
    detalle: dict[str, Any] | None = None

    @property
    def disponible(self) -> bool:
        return self.estado.upper() in {"AVAILABLE", "APPROVED"}


class PasarelaDePagos(Protocol):
    """Ningun metodo bloquea esperando un estado final.

    `esperar()` con 40 iteraciones de `time.sleep(1.5)` (nucleo.py:214) es
    aceptable en un CLI y es inviable en una app: ocupa un worker hasta 60
    segundos por compra. El desenlace llega por webhook; el sondeo queda como
    respaldo, no como camino principal.
    """

    nombre: str

    def preparar_medio(self, solicitud: SolicitudEnrolamiento) -> MedioEnProceso: ...

    def estado_medio_por_token(self, token: str) -> EstadoMedio: ...

    def confirmar_medio(self, token: str, correo: str) -> EstadoMedio: ...

    def revocar_medio(self, ref: MedioDePagoRef) -> EstadoMedio: ...

    def cobrar(self, orden: OrdenDeCobro) -> ResultadoCobro: ...

    def consultar_cobro(self, id_externo: str) -> ResultadoCobro: ...

    def validar_evento(self, cuerpo: bytes, cabeceras: dict[str, str]) -> dict[str, Any]:
        """Devuelve el evento ya verificado, o levanta.

        Va en el puerto y no en un modulo aparte porque la forma de verificar es
        propia de cada pasarela. Sin verificar, cualquiera que conozca la URL
        puede inventar un APPROVED.
        """
        ...

    def resultado_desde_evento(self, evento: dict[str, Any]) -> tuple[str, ResultadoCobro] | None:
        """Traduce un evento YA VERIFICADO (`validar_evento`) a
        `(intencion_id, ResultadoCobro)`, o `None` si el evento no es un
        cobro que le pertenezca a esta app -- otro tipo de evento, o una
        referencia que esta pasarela no reconoce como propia.

        `None` no es un error: `ConciliarEvento` (etapa 4) lo trata como "nada
        que hacer aqui", no como algo que reintentar. Igual que
        `validar_evento`, la forma del evento es propia de cada pasarela (la
        manera de recuperar el `intencion_id` a partir de la referencia que
        Wompi devuelve, por ejemplo), asi que la traduccion vive aqui y no en
        `aplicacion/`.
        """
        ...
