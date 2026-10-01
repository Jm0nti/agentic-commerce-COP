"""Configuracion de Wompi, leida UNA vez en `composicion/` y pasada por
constructor.

En la v1, `ClienteWompi.__init__` leia `os.environ` directo en el
constructor. Era imposible tener dos configuraciones en el mismo proceso, y
las pruebas necesitaban `monkeypatch.setenv` para simular credenciales.
`docs/historico/analisis-codigo.md` (hallazgo 5) llama a esto: el entorno se
lee en un solo lugar del programa, y este objeto, inmutable, es lo que
circula despues.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...model.pago.modelo import Ambiente

URLS: dict[Ambiente, str] = {
    Ambiente.SANDBOX: "https://sandbox.wompi.co/v1",
    Ambiente.PRODUCCION: "https://production.wompi.co/v1",
}

_PREFIJO_PUB_ESPERADO: dict[Ambiente, str] = {
    Ambiente.SANDBOX: "pub_test_",
    Ambiente.PRODUCCION: "pub_prod_",
}


class ConfiguracionInvalida(ValueError):
    """Credenciales ausentes, o que no coinciden con el ambiente declarado."""


@dataclass(frozen=True)
class ConfiguracionWompi:
    ambiente: Ambiente
    llave_publica: str
    llave_privada: str
    secreto_integridad: str
    # Separado de `secreto_integridad` a proposito: son dos secretos
    # distintos de Wompi (uno firma cobros, el otro valida webhooks). Vacio
    # es valido si el proceso nunca va a validar eventos.
    secreto_eventos: str = ""

    def __post_init__(self) -> None:
        faltan = [
            nombre
            for nombre, valor in (
                ("llave_publica", self.llave_publica),
                ("llave_privada", self.llave_privada),
                ("secreto_integridad", self.secreto_integridad),
            )
            if not valor
        ]
        if faltan:
            raise ConfiguracionInvalida(
                f"faltan credenciales de Wompi: {', '.join(faltan)}"
            )

        # El ambiente y el prefijo de la llave tienen que coincidir. Una
        # llave de produccion con ambiente sandbox no falla sola: cobra de
        # verdad contra un endpoint que el codigo cree de mentiras
        # (comportamiento heredado de `nucleo.py:131-139`, ahora en la
        # construccion del objeto en vez de en el constructor del cliente
        # HTTP).
        esperado = _PREFIJO_PUB_ESPERADO[self.ambiente]
        if not self.llave_publica.startswith(esperado):
            raise ConfiguracionInvalida(
                f"ambiente '{self.ambiente.value}' exige una llave publica "
                f"'{esperado}...' y la cargada no lo es. Revise las "
                "credenciales antes de seguir."
            )

    @property
    def url_base(self) -> str:
        return URLS[self.ambiente]
