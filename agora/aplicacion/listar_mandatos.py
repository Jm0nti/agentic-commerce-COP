"""`ListarMandatos`: cada mandato del ambiente de este proceso, con cuanto se
lleva consumido (`cli mandatos`)."""

from __future__ import annotations

from ..dominio.mandato.modelo import Consumo, Mandato
from ..dominio.pago.modelo import Ambiente
from ..puertos.repositorios import LibroDeConsumo, RepositorioMandatos


class ListarMandatos:
    def __init__(
        self, mandatos: RepositorioMandatos, consumo: LibroDeConsumo, ambiente: Ambiente
    ) -> None:
        self._mandatos = mandatos
        self._consumo = consumo
        self._ambiente = ambiente

    def __call__(self) -> list[tuple[Mandato, Consumo]]:
        return [(m, self._consumo.consumo_de(m.mandato_id)) for m in self._mandatos.listar(self._ambiente)]
