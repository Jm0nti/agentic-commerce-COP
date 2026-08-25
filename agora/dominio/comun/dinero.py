"""Valor de dinero explicito y seguro.

Evita mezclar pesos con centavos o monedas distintas usando `int` sueltos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Dinero:
    centavos: int
    moneda: str = "COP"

    def __post_init__(self) -> None:
        if self.centavos < 0:
            raise ValueError("el dinero no puede ser negativo")
        if not self.moneda:
            raise ValueError("la moneda es obligatoria")

    @classmethod
    def de_pesos(cls, pesos: int, moneda: str = "COP") -> "Dinero":
        if pesos < 0:
            raise ValueError("el dinero no puede ser negativo")
        return cls(pesos * 100, moneda)

    @classmethod
    def de_centavos(cls, centavos: int, moneda: str = "COP") -> "Dinero":
        return cls(centavos, moneda)

    @property
    def pesos(self) -> int:
        return self.centavos // 100

    def excede(self, otro: "Dinero") -> bool:
        self._validar_moneda(otro)
        return self.centavos > otro.centavos

    def to_json(self) -> dict[str, Any]:
        return {"centavos": self.centavos, "moneda": self.moneda}

    def _validar_moneda(self, otro: "Dinero") -> None:
        if self.moneda != otro.moneda:
            raise ValueError(
                f"no se pueden mezclar {self.moneda} con {otro.moneda}"
            )

    def __add__(self, otro: "Dinero") -> "Dinero":
        self._validar_moneda(otro)
        return Dinero(self.centavos + otro.centavos, self.moneda)

    def __sub__(self, otro: "Dinero") -> "Dinero":
        self._validar_moneda(otro)
        diferencia = self.centavos - otro.centavos
        if diferencia < 0:
            raise ValueError("el dinero no puede ser negativo")
        return Dinero(diferencia, self.moneda)

    def __mul__(self, factor: int) -> "Dinero":
        if factor < 0:
            raise ValueError("el factor no puede ser negativo")
        return Dinero(self.centavos * factor, self.moneda)

    def __rmul__(self, factor: int) -> "Dinero":
        return self.__mul__(factor)

    def __str__(self) -> str:
        return f"{self.pesos:,} {self.moneda}"


CERO = Dinero(0)
