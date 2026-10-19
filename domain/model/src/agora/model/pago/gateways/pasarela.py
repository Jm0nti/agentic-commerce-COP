"""El puerto de pagos. Dos implementaciones desde el dia uno.

`driven_adapters/pasarela_wompi/` mueve dinero real.
`driven_adapters/pasarela_simulada/` no, y no es un mock de pruebas: es un
adaptador de produccion para el modo demo.

La simulada tiene que poder reproducir los cuatro desenlaces, incluido el
rechazo por antifraude. Sin eso no se puede mostrar el hallazgo del AFE en una
presentacion sin depender de que Wompi coopere ese dia -- y ese hallazgo es el
resultado mas interesante que tiene la PoC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..modelo import Ambiente, MedioDePagoRef, OrdenDeCobro, ResultadoCobro


@dataclass(frozen=True)
class SolicitudEnrolamiento:
    telefono: str
    correo: str
    ambiente: Ambiente
    # Multi-comercio: bajo que comercio se crea el token. Un `payment_
    # source_id` de Wompi queda atado al comercio (a la llave publica) que
    # lo creo -- no es portable entre comercios aunque los tres usen Wompi.
    # `SelectorDePasarela.para(comercio_id)` es quien de verdad enruta esto;
    # el campo viaja igual en la solicitud para que quede en la bitacora y
    # para que un `PasarelaDePagos` de un solo comercio (la simulada, o un
    # `AdaptadorWompi` ya construido con las credenciales de un comercio) lo
    # pueda ignorar sin problema.
    comercio_id: str = ""


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

    Sondear con `time.sleep` hasta un estado final es aceptable en un CLI e
    inviable en una app: ocuparia un worker hasta 60 segundos por compra. El desenlace llega por webhook; el sondeo queda como
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

        `None` no es un error: `ConciliarEventoUseCase` (etapa 4) lo trata como "nada
        que hacer aqui", no como algo que reintentar. Igual que
        `validar_evento`, la forma del evento es propia de cada pasarela (la
        manera de recuperar el `intencion_id` a partir de la referencia que
        Wompi devuelve, por ejemplo), asi que la traduccion vive aqui y no en
        `usecase/`.
        """
        ...



class SelectorDePasarela(Protocol):
    """Resuelve que `PasarelaDePagos` usar para un comercio dado.

    Antes de multi-comercio, `app_service/config/contenedor.py` armaba UNA sola
    `PasarelaDePagos` por proceso y la inyectaba fija en el constructor de
    cada caso de uso (`EjecutarIntencionUseCase`, `ConciliarEventoUseCase`, `EnrolarMedioUseCase`
    y sus tres pasos, `RevocarMedioUseCase`). Eso alcanzaba mientras solo existiera
    un comercio real por proceso. Con N comercios reales de Wompi, cada uno
    con sus propias credenciales (`WOMPI_PUBLIC_KEY`/`PRIVATE_KEY`/
    `INTEGRITY_SECRET`/`EVENTS_SECRET`), hace falta resolver la pasarela
    correcta en el momento de cada operacion, no una sola vez al armar el
    contenedor -- por eso este puerto reemplaza a la `pasarela` fija que
    esos casos de uso recibian antes.

    Con `AGORA_PASARELA=simulada` (el default) todo comercio, real o
    inventado, resuelve a la MISMA pasarela simulada -- no hace falta
    credenciales por comercio para una demo sin dinero real. Con
    `AGORA_PASARELA=wompi`, cada comercio necesita su propia entrada en el
    registro de credenciales; pedir uno que no esta ahi levanta
    `ComercioSinCredencialesWompi` en vez de fallar en silencio contra las
    credenciales de otro comercio.
    """

    def para(self, comercio_id: str) -> PasarelaDePagos: ...
