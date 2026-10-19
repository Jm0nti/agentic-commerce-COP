"""`LibroDeConsumo` en memoria: pruebas, y el unico respaldo hasta la etapa 3.

Evita el leer -> sumar -> escribir que rompe el tope diario bajo concurrencia,
con un lock y una reserva
condicional: el tope diario se comprueba y se aparta en la misma seccion
critica, asi que dos cobros que compiten por el ultimo tramo del cupo no
pueden los dos leer "90.000" y escribir "105.000" cada uno por su lado.

Su par con persistencia real es `persistencia-sqlite`. Este adaptador es el
que corre en pruebas para siempre (`driven_adapters/persistencia_*/
memoria/` esta en la estructura objetivo, no es un stub de paso) y el que
sostiene la demo mientras la 3 no aterriza.

**No usar este adaptador contra dinero real sin la etapa 3.** El consumo vive
en RAM: un restart pierde los topes acumulados, y el mandato que se creyo
agotado vuelve a estar fresco. Con la pasarela simulada eso es aceptable; con
`AdaptadorWompi` en `produccion`, no.
"""

from __future__ import annotations

import threading
from dataclasses import replace

from ...model.commons.dinero import CERO, Dinero
from ...model.mandato.modelo import Consumo, Mandato
from ...model.pago.modelo import Ambiente
from ...model.mandato.gateways.repositorios import Reserva, TopeAgotado
from ...model.commons.gateways.sistema import GeneradorIds, Reloj


class LibroDeConsumoEnMemoria:
    """Implementa `puertos.repositorios.LibroDeConsumo`."""

    def __init__(self, reloj: Reloj, ids: GeneradorIds) -> None:
        self._reloj = reloj
        self._ids = ids
        self._lock = threading.Lock()
        self._consumo: dict[str, Consumo] = {}
        # reserva_id -> (Reserva, ambiente). El ambiente no viaja dentro de
        # `Reserva` (el puerto no lo pide) pero hace falta para descontar del
        # cupo diario correcto al confirmar o liberar.
        self._reservas: dict[str, tuple[Reserva, Ambiente]] = {}
        self._gastado_dia: dict[tuple[Ambiente, str], Dinero] = {}

    # -- reserva -------------------------------------------------------------- #

    def reservar(
        self, mandato: Mandato, intencion_id: str, monto: Dinero, tope_dia: Dinero
    ) -> Reserva:
        ambiente = mandato.medio.ambiente
        with self._lock:
            hoy = self._reloj.ahora().date().isoformat()
            clave = (ambiente, hoy)
            gastado = self._gastado_dia.get(clave, CERO)
            if (gastado + monto).excede(tope_dia):
                # `gastado` nunca supera `tope_dia`: solo se acumula aqui
                # mismo, bajo el lock, y solo cuando cupo. La resta es segura.
                raise TopeAgotado("tope_duro_diario", tope_dia - gastado, monto)

            self._gastado_dia[clave] = gastado + monto
            reserva = Reserva(
                reserva_id=self._ids.nuevo("rsv"),
                intencion_id=intencion_id,
                mandato_id=mandato.mandato_id,
                monto=monto,
                dia=self._reloj.ahora().date(),
            )
            self._reservas[reserva.reserva_id] = (reserva, ambiente)
            return reserva

    def confirmar(self, reserva: Reserva) -> None:
        with self._lock:
            entrada = self._reservas.pop(reserva.reserva_id, None)
            if entrada is None:
                # Confirmar dos veces (reintento tras un timeout, por ejemplo)
                # no debe duplicar el consumo. Silenciosamente no-op: ya se
                # confirmo o ya se libero.
                return
            actual = self._consumo.get(reserva.mandato_id, Consumo())
            self._consumo[reserva.mandato_id] = replace(
                actual, usos=actual.usos + 1, acumulado=actual.acumulado + reserva.monto
            )

    def liberar(self, reserva: Reserva) -> None:
        with self._lock:
            entrada = self._reservas.pop(reserva.reserva_id, None)
            if entrada is None:
                return
            _, ambiente = entrada
            clave = (ambiente, reserva.dia.isoformat())
            gastado = self._gastado_dia.get(clave, CERO)
            self._gastado_dia[clave] = gastado - reserva.monto

    def reserva_pendiente_de(self, intencion_id: str) -> Reserva | None:
        """Barrido lineal: a esta escala (demo, pruebas) es mas simple que un
        segundo indice `intencion_id -> reserva_id`, y `_reservas` solo
        contiene reservas vivas (confirmar/liberar ya las sacan del dict)."""
        with self._lock:
            for reserva, _ambiente in self._reservas.values():
                if reserva.intencion_id == intencion_id:
                    return reserva
            return None

    # -- consultas -------------------------------------------------------------- #

    def consumo_de(self, mandato_id: str) -> Consumo:
        with self._lock:
            return self._consumo.get(mandato_id, Consumo())

    def gastado_hoy(self, ambiente: Ambiente) -> Dinero:
        with self._lock:
            hoy = self._reloj.ahora().date().isoformat()
            return self._gastado_dia.get((ambiente, hoy), CERO)
