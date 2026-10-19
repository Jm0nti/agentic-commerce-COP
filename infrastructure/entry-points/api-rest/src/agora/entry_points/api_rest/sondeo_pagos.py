"""`SondeoDePagosPendientes` (etapa 9): la pieza que le devuelve al chat web
la respuesta que el webhook de la pasarela ya sabe, pero que vive en otro
proceso.

EL PROBLEMA QUE RESUELVE
-------------------------
`usecase/ejecutar_intencion/ejecutar_intencion_use_case.py:_cobrar` nunca bloquea esperando el
desenlace de un cobro real contra Wompi -- devuelve 'PENDING' de inmediato,
y el desenlace final lo asienta despues `usecase/conciliar_evento/conciliar_evento_use_case.py`,
llamado desde el receptor HTTP del webhook (`entry_points/webhook_wompi/wompi.py`,
`app_service/servir_webhook_wompi.py`). Ese receptor corre en OTRO PROCESO que
el de este chat (`app_service/servir_api.py`) -- dos composition roots
deliberadamente separados (ver el docstring de `servir_webhook_wompi.py`).
Sin este modulo, la sesion de chat nunca se entera de que el webhook ya
resolvio nada: el agente le dijo a la persona "quedo pendiente" y ahi se
queda, hasta que alguien vuelva a escribirle.

COMO LO RESUELVE
-----------------
`usecase/consultar_estado/consultar_estado_use_case.py:ConsultarEstadoUseCase` ya lee el mismo sqlite que
`ConciliarEventoUseCase` escribe -- el estado SI esta compartido entre los dos
procesos, solo que nadie de este lado volvia a preguntar. Esta clase corre
en un hilo de fondo dentro del proceso del chat, sondea (a intervalos, sin
bloquear ninguna peticion HTTP) las intenciones que `AlmacenDeSesiones`
registro como "quedaron en PENDING", y en cuanto una llega a un estado
final le avisa a la sesion dueña exactamente como si la persona hubiese
hecho click en un popup (`AlmacenDeSesiones.resolver_pendiente`).

POR QUE SONDEO Y NO UNA NOTIFICACION DIRECTA DEL WEBHOOK
----------------------------------------------------------
Una notificacion directa (el webhook llamando a una ruta interna de esta
API en cuanto concilia) reaccionaria al instante, pero acoplaria dos
composition roots que hoy son independientes a proposito -- cada uno
necesitaria conocer la URL del otro, y habria que persistir el mapeo
intencion_id -> sesion_id en sqlite para que sobreviva a un reinicio. El
sondeo es la opcion mas simple: el estado ya esta compartido, alcanza con
volver a preguntar. El costo es la demora del intervalo (`intervalo_seg`),
aceptable para esta PoC.

POR QUE NO VIVE ADENTRO DE `crear_app` (`entry_points/api_rest/app.py`)
------------------------------------------------------------------
`crear_app` es una factoria pura que tambien arma un `TestClient` en las
pruebas (`tests/entry_points/test_api_app.py`) -- si arrancara un hilo de fondo ahi, cada
prueba que construye una app dejaria un hilo real corriendo con un
temporizador real. Por eso el composition root real (`scripts/
servir_api.py`) es quien decide si arrancar el sondeo, despues de llamar a
`crear_app`.
"""

from __future__ import annotations

import threading
from typing import Callable

from ...usecase.consultar_estado.consultar_estado_use_case import EstadoIntencion
from ...model.commons.errores import EstadoDesconocido
from .sesiones import AlmacenDeSesiones

_ESTADOS_FINALES = {"aprobado", "rechazado"}

_INTERVALO_SEG_DEFAULT = 5.0


class SondeoDePagosPendientes:
    def __init__(
        self,
        sesiones: AlmacenDeSesiones,
        consultar_estado: Callable[[str], EstadoIntencion],
        intervalo_seg: float = _INTERVALO_SEG_DEFAULT,
    ) -> None:
        self._sesiones = sesiones
        self._consultar_estado = consultar_estado
        self._intervalo = intervalo_seg
        self._detener = threading.Event()
        self._hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        """Arranca el hilo de fondo. `daemon=True`: si el proceso principal
        termina, este hilo no lo retiene -- coherente con que nada de lo que
        sondea es persistente de por si (el estado real ya esta a salvo en
        sqlite antes de que este hilo se entere de nada)."""
        self._hilo = threading.Thread(
            target=self._bucle, name="sondeo-pagos-pendientes", daemon=True,
        )
        self._hilo.start()

    def detener(self) -> None:
        self._detener.set()
        if self._hilo is not None:
            self._hilo.join(timeout=self._intervalo + 1)

    def _bucle(self) -> None:
        while not self._detener.wait(self._intervalo):
            self.una_pasada()

    def una_pasada(self) -> None:
        """Una vuelta de sondeo, expuesta aparte de `_bucle` para poder
        probarla sin hilos ni `time.sleep` real (ver `tests/
        test_sondeo_pagos.py`). Una intencion que revienta no debe tumbar
        el sondeo de las demas -- mismo criterio de tolerancia que
        `entry_points/webhook_wompi/wompi.py` ("WOMPI ESPERA UN 200, SIEMPRE"): un
        hilo de fondo que muere en silencio por una excepcion no atrapada
        es peor que uno que se salta un item y sigue."""
        for intencion_id in self._sesiones.pendientes():
            try:
                estado = self._consultar_estado(intencion_id)
                if estado.estado in _ESTADOS_FINALES:
                    self._sesiones.resolver_pendiente(intencion_id, estado.estado)
            except EstadoDesconocido:
                # No deberia pasar (si esta en `pendientes()` es porque ya
                # se le escribio un estado), pero un registro huerfano no
                # tiene por que tumbar el sondeo de los demas.
                continue
            except Exception as exc:  # noqa: BLE001 -- ver docstring de arriba
                print(f"[sondeo-pagos] error consultando '{intencion_id}': {exc}")
