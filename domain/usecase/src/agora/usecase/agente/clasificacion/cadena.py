"""Clasificadores en cadena: el primero que decide, gana.

Es la forma del clasificador hibrido del documento (reglas primero, modelo
despues) sin que ninguno de los dos sepa que el otro existe:
`app_service/config/agente.py` decide el orden y cuales entran, segun
`AGORA_CLASIFICADOR`.
"""

from __future__ import annotations

from typing import Sequence

from ....model.agente.gateways.modelo_lenguaje import Mensaje
from ....model.agente.intencion import ClasificacionDeIntencion, ClasificadorDeIntencion


class ClasificadorEnCadena:
    """Implementa `agente.intencion.ClasificadorDeIntencion`."""

    def __init__(self, *clasificadores: ClasificadorDeIntencion) -> None:
        if not clasificadores:
            raise ValueError("una cadena de clasificadores necesita al menos uno")
        self._clasificadores = clasificadores

    def clasificar(
        self, mensaje: str, historial: Sequence[Mensaje] = ()
    ) -> ClasificacionDeIntencion:
        motivos: list[str] = []
        for clasificador in self._clasificadores:
            clasificacion = clasificador.clasificar(mensaje, historial)
            if clasificacion.decidida:
                return clasificacion
            motivos.append(clasificacion.motivo)
        # Nadie decidio: se conservan TODOS los motivos, en orden, para que
        # quien lea la bitacora de la charla sepa por que se fue a respaldo
        # (ambiguo por reglas Y modelo caido no es lo mismo que ambiguo por
        # reglas Y modelo poco seguro).
        return ClasificacionDeIntencion.respaldo(" | ".join(m for m in motivos if m))
