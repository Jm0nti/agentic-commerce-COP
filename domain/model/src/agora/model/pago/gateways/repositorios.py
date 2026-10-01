"""Persistencia de los medios de pago y del estado de cada intencion.

Salio de `puertos/repositorios.py` (Fase 2 del refactor a la Clean
Architecture de Bancolombia): cada agregado tiene sus gateways.
"""

from __future__ import annotations

from typing import Protocol

from ..modelo import Ambiente, MedioDePagoRef


class RepositorioMedios(Protocol):
    """Multi-comercio (evaluacion del 1 de septiembre de 2026, `docs/
    viabilidad-multi-comercio-wompi.md`): un `payment_source_id` de Wompi
    esta atado al comercio (a la llave publica) que lo creo, no es portable
    entre comercios aunque los tres usen Wompi -- asi que "vinculo" no es
    "vivo": un titular puede tener varios medios vivos y ninguno vinculado
    al comercio en el que quiere comprar ahora. `guardar` registra bajo que
    comercio nacio cada medio; `vinculado_con` es la pregunta que evita
    pedirle al titular un enrolamiento (un push mas) que ya hizo antes para
    ese comercio puntual."""

    def guardar(self, ref: MedioDePagoRef, titular_id: str, comercio_id: str) -> None: ...

    def vivos(self, titular_id: str, ambiente: Ambiente) -> list[MedioDePagoRef]: ...

    def vinculado_con(
        self, titular_id: str, comercio_id: str, ambiente: Ambiente
    ) -> MedioDePagoRef | None:
        """El medio vivo mas reciente que este titular ya vinculo con este
        comercio, o `None` si nunca enrolo uno para el -- en ese caso hace
        falta un enrolamiento nuevo, dirigido a `comercio_id`
        (`aplicacion/enrolar_medio.py`), antes de poder firmar un mandato
        contra el (`aplicacion/emitir_mandato.py`)."""
        ...

    def comercio_de(self, ref: MedioDePagoRef) -> str | None:
        """Bajo que comercio se creo este medio, o `None` si el medio no
        esta registrado. Lo usa `RevocarMedioUseCase` para resolver con que
        pasarela pedir la revocacion sin que quien llame tenga que volver a
        pasar el `comercio_id` a mano."""
        ...

    def marcar_estado(self, ref: MedioDePagoRef, estado: str) -> None: ...


class RegistroDeEstados(Protocol):
    """Etapa 5. Resuelve un vacio que `LibroDeConsumo.reserva_pendiente_de`
    deja a proposito (ver su docstring): esa reserva vuelve `None` tanto si
    la intencion nunca existio como si ya se resolvio, y no dice si se
    resolvio en `APROBADO` o en `RECHAZADO`. `consultar_estado` (la
    herramienta del agente) necesita esa distincion, y ni `LibroDeConsumo`
    ni `Bitacora` -- que es auditoria de solo escritura, no estado de
    aplicacion (`puertos/sistema.py`) -- estan pensados para contestarla.

    `EjecutarIntencionUseCase` y `ConciliarEventoUseCase` escriben aqui en cada uno de sus
    puntos de decision ya existentes (parametro opcional, `None` por
    defecto: no cambia su comportamiento si nadie lo provee). `estado` es
    texto libre y corto -- "pendiente", "aprobado", "rechazado",
    "esperando_confirmacion" -- no un enum nuevo: es el mismo vocabulario
    que ya usa `Recibo.motivo`/`EstadoCobro`, no una taxonomia paralela.

    Etapa 6 (segunda parte): tiene adaptador SQLite ademas del de memoria.
    La etapa 5 penso esto como "vocabulario para que el agente se
    autoconsulte dentro de UNA conversacion" y lo dejo sin sqlite a
    proposito -- pero `retomar` nunca es herramienta del agente (resolver
    un CONFIRMAR es decision humana, igual que firmar), asi que SIEMPRE
    corre en otra terminal. Sin persistencia entre procesos, el chat
    quedaria diciendo "esperando confirmacion humana" para siempre aunque
    la persona ya hubiera confirmado en la otra terminal -- exactamente el
    bug que motivo agregar la tabla `estado_intencion`.
    """

    def fijar(self, intencion_id: str, estado: str, detalle: str = "") -> None: ...

    def obtener(self, intencion_id: str) -> tuple[str, str] | None:
        """`(estado, detalle)`, o `None` si nunca se fijo nada para este id."""
        ...
