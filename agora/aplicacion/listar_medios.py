"""`ListarMediosVivos`: los medios de pago vivos de un titular, en el ambiente
de este proceso. El ambiente lo fija la configuracion del servidor, nunca
quien pregunta (ver `entradas/api/app.py:listar_medios`)."""

from __future__ import annotations

from ..dominio.pago.modelo import Ambiente, MedioDePagoRef
from ..puertos.repositorios import RepositorioMedios


class ListarMediosVivos:
    def __init__(self, medios: RepositorioMedios, ambiente: Ambiente) -> None:
        self._medios = medios
        self._ambiente = ambiente

    def __call__(self, titular_id: str) -> list[MedioDePagoRef]:
        return self._medios.vivos(titular_id, self._ambiente)
