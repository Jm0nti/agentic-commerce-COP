"""Paso 3 de la Fase A: confirmar y guardar el medio.

Ver `enrolar_medio` para el porque de partir la Fase A en pasos.
"""

from __future__ import annotations

from ...model.commons.errores import MedioNoAprobado
from ...model.pago.modelo import MedioDePagoRef
from ...model.pago.gateways.pasarela import SelectorDePasarela
from ...model.pago.gateways.repositorios import RepositorioMedios
from ...model.commons.gateways.sistema import Bitacora



class ConfirmarEnrolamientoUseCase:
    """Paso 3: el cierre. Exige que quien llama YA sepa que el token esta
    en `APPROVED` (`estado_token`, el resultado de la ultima
    `ConsultarEnrolamientoUseCase`) -- no vuelve a sondear por su cuenta, porque
    eso agregaria una consulta que `EnrolarMedioUseCase` (mas abajo) no necesita y
    que un doble de pruebas escrito contra su secuencia exacta de llamadas
    no esperaria. Si el token esta en `APPROVED`, confirma la fuente de
    pago contra la pasarela de `comercio_id`, la guarda con ese mismo
    comercio (`RepositorioMedios.guardar` -- lo que hace posible
    `vinculado_con` despues), y deja constancia en la bitacora.
    """

    def __init__(
        self, selector_pasarela: SelectorDePasarela, medios: RepositorioMedios, bitacora: Bitacora,
    ) -> None:
        self._selector = selector_pasarela
        self._medios = medios
        self._bitacora = bitacora

    def __call__(
        self, token: str, correo: str, titular_id: str, estado_token: str, comercio_id: str,
    ) -> MedioDePagoRef:
        if estado_token != "APPROVED":
            raise MedioNoAprobado(
                f"el token quedo en '{estado_token}' y no en APPROVED -- sin "
                "aceptacion del titular no hay fuente de pago"
            )

        confirmado = self._selector.para(comercio_id).confirmar_medio(token, correo)
        if not confirmado.disponible or confirmado.ref is None:
            raise MedioNoAprobado(
                f"la fuente de pago quedo en '{confirmado.estado}', no disponible"
            )

        self._medios.guardar(confirmado.ref, titular_id, comercio_id)
        self._bitacora.anotar(
            "medio_enrolado",
            {
                "titular_id": titular_id,
                "comercio_id": comercio_id,
                "medio": confirmado.ref.to_json(),
                "estado": confirmado.estado,
            },
        )
        return confirmado.ref
