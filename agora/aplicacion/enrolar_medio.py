"""`EnrolarMedio`: Fase A, igual que `boveda/enrolamiento.py:enrolar_nequi`,
pero orquestada contra `PasarelaDePagos` (puerto) en vez de contra
`ClienteWompi` (HTTP directo) -- por eso funciona igual con la simulada
(aprueba de inmediato) que con Wompi real (token -> push -> sondeo).

    preparar_medio()          nace el token, el titular recibe el push
        |
    estado_medio_por_token()  se sondea hasta un estado final
        |
    confirmar_medio()         nace la fuente de pago (el MedioDePagoRef)
        |
    RepositorioMedios.guardar()

No cobra nada -- eso es `aplicacion/ejecutar_intencion.py`. Igual que en la
v1 (`boveda/enrolamiento.py`, docstring del modulo): enrolar es un acto del
titular, cobrar es un acto del agente, y mezclarlos en un caso de uso haria
imposible distinguir cual de los dos fallo.

`agente/` no importa este modulo: no esta en `agente/herramientas.py:
CATALOGO_DE_HERRAMIENTAS` (`enrolar` esta en la lista de `PROHIBIDAS`). Lo
llama `entradas/cli/`, del lado del titular.
"""

from __future__ import annotations

import time

from ..dominio.comun.errores import MedioNoAprobado
from ..dominio.pago.modelo import Ambiente, MedioDePagoRef
from ..puertos.pasarela import PasarelaDePagos, SolicitudEnrolamiento
from ..puertos.repositorios import RepositorioMedios
from ..puertos.sistema import Bitacora

ESTADOS_FINALES_TOKEN = frozenset({"APPROVED", "DECLINED", "ERROR", "VOIDED"})
ESPERA_PUSH_SEG = 300
PAUSA_SONDEO_SEG = 3.0


class EnrolarMedio:
    def __init__(
        self,
        pasarela: PasarelaDePagos,
        medios: RepositorioMedios,
        bitacora: Bitacora,
        ambiente: Ambiente,
        espera_seg: float = ESPERA_PUSH_SEG,
        pausa_seg: float = PAUSA_SONDEO_SEG,
    ) -> None:
        self._pasarela = pasarela
        self._medios = medios
        self._bitacora = bitacora
        self._ambiente = ambiente
        self._espera_seg = espera_seg
        self._pausa_seg = pausa_seg

    def __call__(
        self, telefono: str, correo: str, titular_id: str, al_avanzar=None
    ) -> MedioDePagoRef:
        """`al_avanzar` recibe `(etapa, detalle)` para que quien llame (la
        CLI) narre el sondeo sin que este caso de uso sepa nada de como se
        imprime -- mismo patron que `boveda/enrolamiento.py:enrolar_nequi`.
        """
        aviso = al_avanzar or (lambda *_: None)

        solicitud = SolicitudEnrolamiento(telefono=telefono, correo=correo, ambiente=self._ambiente)
        proceso = self._pasarela.preparar_medio(solicitud)
        aviso("token", proceso.token)

        estado = proceso.estado
        limite = time.monotonic() + self._espera_seg
        while estado not in ESTADOS_FINALES_TOKEN and time.monotonic() < limite:
            time.sleep(self._pausa_seg)
            estado = self._pasarela.estado_medio_por_token(proceso.token).estado
            aviso("sondeo", estado)

        if estado != "APPROVED":
            raise MedioNoAprobado(
                f"el token quedo en '{estado}' y no en APPROVED -- sin aceptacion "
                "del titular no hay fuente de pago"
            )

        confirmado = self._pasarela.confirmar_medio(proceso.token, correo)
        if not confirmado.disponible or confirmado.ref is None:
            raise MedioNoAprobado(
                f"la fuente de pago quedo en '{confirmado.estado}', no disponible"
            )

        self._medios.guardar(confirmado.ref, titular_id)
        self._bitacora.anotar(
            "medio_enrolado",
            {
                "titular_id": titular_id,
                "medio": confirmado.ref.to_json(),
                "estado": confirmado.estado,
            },
        )
        aviso("lista", confirmado.estado)
        return confirmado.ref
