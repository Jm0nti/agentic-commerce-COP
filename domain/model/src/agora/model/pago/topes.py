"""Topes duros del experimento.

No son configurables por diseno: el control que protege dinero real no depende
ni del agente ni del mandato.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..commons.dinero import Dinero


@dataclass(frozen=True)
class TopesDuros:
    por_transaccion: Dinero = Dinero.de_pesos(20_000) #2_000_000
    por_dia: Dinero = Dinero.de_pesos(100_000) #10_000_000

    def excede(self, monto: Dinero) -> str | None:
        if monto.excede(self.por_transaccion):
            return (
                "tope_duro_transaccion: "
                f"{monto} supera el limite de {self.por_transaccion} por transaccion"
            )
        return None
