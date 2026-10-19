"""`RegistroDePasarelas`: implementa `puertos.pasarela.SelectorDePasarela`.

Ver el docstring del puerto para el porque. Aca solo la resolucion:

    con `por_defecto`      TODO comercio_id resuelve a esa unica pasarela
                           (el caso `AGORA_PASARELA=simulada`: no hace
                           falta credenciales por comercio para una demo).

    sin `por_defecto`      solo los comercio_id que esten en `por_comercio`
                           resuelven -- cualquier otro levanta
                           `ComercioSinCredencialesWompi` (el caso
                           `AGORA_PASARELA=wompi`: pedir un comercio sin
                           credenciales configuradas es un error real, no
                           algo que deba caer de vuelta en otra pasarela
                           -- eso escondería exactamente el tipo de
                           descuido que esta PoC existe para exponer).

Un `comercio_id` presente en `por_comercio` SIEMPRE gana sobre
`por_defecto`, aunque los dos esten seteados -- hoy `app_service/config/
contenedor.py` nunca arma las dos cosas a la vez, pero la prioridad queda
explicita por si algun dia conviven (por ejemplo, unos comercios reales de
Wompi y otros todavia simulados en el mismo catalogo).
"""

from __future__ import annotations

from ...model.commons.errores import ComercioSinCredencialesWompi
from ...model.pago.gateways.pasarela import PasarelaDePagos


class RegistroDePasarelas:
    """Implementa `puertos.pasarela.SelectorDePasarela`."""

    def __init__(
        self,
        por_comercio: dict[str, PasarelaDePagos],
        por_defecto: PasarelaDePagos | None = None,
    ) -> None:
        self._por_comercio = por_comercio
        self._por_defecto = por_defecto

    def para(self, comercio_id: str) -> PasarelaDePagos:
        if comercio_id in self._por_comercio:
            return self._por_comercio[comercio_id]
        if self._por_defecto is not None:
            return self._por_defecto
        raise ComercioSinCredencialesWompi(
            f"no hay credenciales de Wompi configuradas para el comercio "
            f"'{comercio_id}' -- agreguelas al registro (`agora_datos/"
            "secretos/comercios_wompi.json`) antes de operar contra el"
        )
