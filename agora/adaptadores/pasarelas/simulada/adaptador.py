"""La pasarela simulada. Ciudadano de primera, no un mock (ADR-2).

Vive en `adaptadores/pasarelas/simulada/` al lado de `wompi/`, implementa el
mismo `PasarelaDePagos` y se elige por configuracion en `composicion/`. No
hace red ni disco propio (mas alla de lo que le pase la bitacora por fuera):
todo su estado es un par de `dict` en memoria, protegidos por un lock.

Reemplaza a `wompi_lab/lab.py` (`docs/mapa-del-proyecto.md`, seccion "se va
sola en su etapa"): aquel banco de pruebas hablaba con el sandbox real de
Wompi; este adaptador no habla con nadie y por eso puede reproducir cualquier
desenlace sin gastar, sin red y sin que a Wompi le toque cooperar.
"""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from typing import Any

from ....dominio.comun.errores import ErrorDePasarela
from ....dominio.pago.modelo import (
    Ambiente,
    MedioDePagoRef,
    OrdenDeCobro,
    Proveedor,
    ResultadoCobro,
)
from ....puertos.pasarela import EstadoMedio, MedioEnProceso, SolicitudEnrolamiento
from ....puertos.sistema import GeneradorIds
from .guion import Desenlace, GuionSimulado


class AdaptadorSimulado:
    """Implementa `puertos.pasarela.PasarelaDePagos`."""

    nombre = "simulada"

    def __init__(
        self,
        ids: GeneradorIds,
        ambiente: Ambiente,
        guion: GuionSimulado | None = None,
    ) -> None:
        self._ids = ids
        self._ambiente = ambiente
        self._guion = guion or GuionSimulado()
        self._lock = threading.Lock()
        self._tokens: dict[str, EstadoMedio] = {}
        self._cobros: dict[str, ResultadoCobro] = {}

    # -- enrolamiento ----------------------------------------------------------- #

    def preparar_medio(self, solicitud: SolicitudEnrolamiento) -> MedioEnProceso:
        """No hay push que esperar: la simulada aprueba el token de inmediato.

        Sigue devolviendo de inmediato (sin bloquear) porque asi lo exige el
        puerto -- no porque haga falta aqui, sino para que un caso de uso
        escrito contra la simulada tambien funcione contra Wompi real.
        """
        token = self._ids.nuevo("simtok")
        with self._lock:
            self._tokens[token] = EstadoMedio(estado="APPROVED")
        return MedioEnProceso(token=token, estado="APPROVED")

    def estado_medio_por_token(self, token: str) -> EstadoMedio:
        with self._lock:
            return self._tokens.get(token, EstadoMedio(estado="PENDING"))

    def confirmar_medio(self, token: str, correo: str) -> EstadoMedio:
        with self._lock:
            previo = self._tokens.get(token)
            if previo is None or previo.estado != "APPROVED":
                return EstadoMedio(estado="DECLINED")
            ref = MedioDePagoRef(Proveedor.SIMULADA, self._ambiente, self._ids.nuevo("simsrc"))
            estado = EstadoMedio(estado="AVAILABLE", ref=ref)
            self._tokens[token] = estado
            return estado

    def revocar_medio(self, ref: MedioDePagoRef) -> EstadoMedio:
        return EstadoMedio(estado="VOIDED", ref=ref)

    # -- cobro ----------------------------------------------------------- #

    def cobrar(self, orden: OrdenDeCobro) -> ResultadoCobro:
        if orden.medio.proveedor is not Proveedor.SIMULADA:
            raise ErrorDePasarela(
                f"la pasarela simulada no puede cobrar un medio de "
                f"'{orden.medio.proveedor.value}'"
            )
        desenlace = self._guion.decidir(orden)
        id_externo = f"sim_{self._ids.nuevo('tx')}"
        resultado = ResultadoCobro(
            estado=desenlace.estado,
            id_externo=id_externo,
            # ADR-6: la referencia se deriva de la intencion, nunca de un uuid
            # nuevo por intento. Reintentar es seguro por construccion.
            referencia=orden.intencion_id,
            status_message=desenlace.status_message,
            afe_decision=desenlace.afe_decision,
            detalle={"orden": orden.to_json(), "simulado": True},
        )
        with self._lock:
            self._cobros[id_externo] = resultado
        return resultado

    def consultar_cobro(self, id_externo: str) -> ResultadoCobro:
        with self._lock:
            resultado = self._cobros.get(id_externo)
        if resultado is None:
            raise ErrorDePasarela(f"la simulada no conoce el cobro '{id_externo}'")
        return resultado

    def resolver_pendiente(self, id_externo: str, desenlace: Desenlace) -> ResultadoCobro:
        """Solo para demos y pruebas.

        Convierte un cobro `PENDIENTE` en su desenlace final, imitando el
        webhook `transaction.updated` que en Wompi real cierra el ciclo
        (`docs/arquitectura-v2.md`, seccion 6, pasos 7d-8). No existe en el
        `Protocol` -- nada de `aplicacion/` puede depender de este metodo, o
        dejaria de funcionar contra `AdaptadorWompi`.
        """
        with self._lock:
            actual = self._cobros.get(id_externo)
            if actual is None:
                raise ErrorDePasarela(f"la simulada no conoce el cobro '{id_externo}'")
            nuevo = replace(
                actual,
                estado=desenlace.estado,
                status_message=desenlace.status_message or actual.status_message,
                afe_decision=desenlace.afe_decision or actual.afe_decision,
            )
            self._cobros[id_externo] = nuevo
            return nuevo

    # -- eventos ----------------------------------------------------------- #

    def validar_evento(self, cuerpo: bytes, cabeceras: dict[str, str]) -> dict[str, Any]:
        """La simulada no tiene webhook de verdad: el cuerpo se acepta tal
        cual, sin checksum. **No representa la seguridad de
        `AdaptadorWompi.validar_evento`** -- eso si valida contra un secreto,
        porque contra dinero real un checksum sin validar es la superficie de
        ataque mas barata del sistema (ver `boveda/eventos.py`)."""
        return json.loads(cuerpo)
