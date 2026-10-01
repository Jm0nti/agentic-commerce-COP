"""Paso 1 de la Fase A: crear el token y disparar el push.

Ver `enrolar_medio` para el porque de partir la Fase A en pasos.
"""

from __future__ import annotations

from ...model.pago.modelo import Ambiente
from ...model.pago.gateways.pasarela import (
    MedioEnProceso,
    SelectorDePasarela,
    SolicitudEnrolamiento,
)



class IniciarEnrolamientoUseCase:
    """Paso 1: crea el token con la pasarela DEL COMERCIO indicado y le
    dispara el push al titular. No guarda nada todavia -- no hay fuente de
    pago hasta que el titular acepte, asi que no hay nada que persistir en
    este paso."""

    def __init__(self, selector_pasarela: SelectorDePasarela, ambiente: Ambiente) -> None:
        self._selector = selector_pasarela
        self._ambiente = ambiente

    def __call__(self, telefono: str, correo: str, comercio_id: str) -> MedioEnProceso:
        solicitud = SolicitudEnrolamiento(
            telefono=telefono, correo=correo, ambiente=self._ambiente, comercio_id=comercio_id,
        )
        return self._selector.para(comercio_id).preparar_medio(solicitud)
