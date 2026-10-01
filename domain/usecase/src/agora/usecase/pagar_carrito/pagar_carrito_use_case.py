"""`PagarCarritoUseCase`: cobrar un carrito ya guardado contra un mandato firmado.

Antes, cuatro puntos de entrada armaban la misma `Intencion` a mano (la
herramienta `pagar` del agente, `cli pagar`, `cli retomar` y la ruta
`/intenciones/{id}/retomar`), cada uno leyendo el carrito del repositorio por
su cuenta. Es la parte del camino del dinero donde una copia que se desvia no
la nota nadie, asi que vive en un solo lugar: comercio, monto y
`carrito_hash` salen SIEMPRE del carrito recien leido, nunca de quien llama
-- ni del modelo, ni de la terminal, ni del navegador (ver el docstring de
`EjecutarIntencionUseCase.__call__` sobre el Cart Mandate).

Tambien es lo que deja a los puntos de entrada sin tocar un repositorio
(Clean Architecture de Bancolombia: un entry point delega en un caso de uso).
"""

from __future__ import annotations

from ...model.mandato.modelo import Intencion
from ...model.catalogo.gateways.repositorios import RepositorioCarritos
from ...model.commons.gateways.sistema import GeneradorIds
from ..ejecutar_intencion.ejecutar_intencion_use_case import EjecutarIntencionUseCase, Recibo


class PagarCarritoUseCase:
    def __init__(
        self, ejecutar: EjecutarIntencionUseCase, carritos: RepositorioCarritos, ids: GeneradorIds
    ) -> None:
        self._ejecutar = ejecutar
        self._carritos = carritos
        self._ids = ids

    def __call__(self, mandato_id: str, carrito_id: str) -> Recibo:
        """Una intencion nueva. El `intencion_id` viaja en `recibo.intencion`."""
        intencion, carrito_hash = self._intencion(self._ids.nuevo("int"), mandato_id, carrito_id)
        return self._ejecutar(intencion, carrito_hash=carrito_hash)

    def retomar(
        self, intencion_id: str, mandato_id: str, carrito_id: str, aprueba: bool
    ) -> Recibo:
        """La decision humana sobre una intencion que quedo en CONFIRMAR --
        la misma `Intencion`, rearmada desde el carrito (ver
        `EjecutarIntencionUseCase.retomar`)."""
        intencion, carrito_hash = self._intencion(intencion_id, mandato_id, carrito_id)
        return self._ejecutar.retomar(intencion, aprueba=aprueba, carrito_hash=carrito_hash)

    def _intencion(
        self, intencion_id: str, mandato_id: str, carrito_id: str
    ) -> tuple[Intencion, str]:
        carrito = self._carritos.obtener(carrito_id)
        intencion = Intencion(
            intencion_id=intencion_id,
            mandato_id=mandato_id,
            comercio_id=carrito.comercio_id,
            carrito_id=carrito_id,
            monto=carrito.total,
        )
        return intencion, carrito.hash_canonico
