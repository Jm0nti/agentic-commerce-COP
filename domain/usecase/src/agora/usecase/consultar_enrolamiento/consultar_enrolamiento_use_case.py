"""Paso 2 de la Fase A: un sondeo del estado del token.

Ver `enrolar_medio` para el porque de partir la Fase A en pasos.
"""

from __future__ import annotations

from ...model.pago.gateways.pasarela import EstadoMedio, SelectorDePasarela



class ConsultarEnrolamientoUseCase:
    """Paso 2: un sondeo, una sola vez. Quien orqueste el ritmo (el bucle
    bloqueante de `EnrolarMedioUseCase`, o un `GET` que el navegador repite cada
    pocos segundos en `entradas/api/`) decide cuando volver a llamar --
    esta clase no sabe ni le importa si es la primera consulta o la
    numero cien. `comercio_id` tiene que ser el MISMO que se uso en
    `IniciarEnrolamientoUseCase` para este token -- quien orquesta el sondeo es
    quien lo recuerda entre llamadas."""

    def __init__(self, selector_pasarela: SelectorDePasarela) -> None:
        self._selector = selector_pasarela

    def __call__(self, token: str, comercio_id: str) -> EstadoMedio:
        return self._selector.para(comercio_id).estado_medio_por_token(token)
