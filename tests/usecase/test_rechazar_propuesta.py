"""`RechazarPropuestaUseCase`: el contrapunto de `EmitirMandatoUseCase` cuando el humano
no firma. Mismo estilo que `test_emitir_mandato.py` -- una propuesta y un
`_BitacoraEnLista` de prueba, sin sqlite ni HTTP de por medio."""

from __future__ import annotations

import pytest

from agora.driven_adapters.persistencia_memoria import RepositorioPropuestasEnMemoria
from agora.usecase.rechazar_propuesta.rechazar_propuesta_use_case import RechazarPropuestaUseCase
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import PropuestaDesconocida
from agora.model.mandato.modelo import PropuestaDeMandato


class _BitacoraEnLista:
    def __init__(self) -> None:
        self.eventos: list[tuple[str, object]] = []

    def anotar(self, evento: str, cuerpo: object) -> None:
        self.eventos.append((evento, cuerpo))


def _propuesta(**kw) -> PropuestaDeMandato:
    base = dict(
        propuesta_id="prp_1", carrito_id="car_1", comercio_id="com_1",
        monto_max=Dinero.de_pesos(1_500),
    )
    base.update(kw)
    return PropuestaDeMandato(**base)


def _armar():
    propuestas = RepositorioPropuestasEnMemoria()
    propuestas.guardar(_propuesta())
    bitacora = _BitacoraEnLista()
    return RechazarPropuestaUseCase(propuestas=propuestas, bitacora=bitacora), bitacora


def test_rechazar_anota_en_bitacora_y_no_toca_nada_mas():
    rechazar, bitacora = _armar()

    rechazar("prp_1", "tit_1")

    assert len(bitacora.eventos) == 1
    evento, cuerpo = bitacora.eventos[0]
    assert evento == "propuesta_rechazada"
    assert cuerpo == {
        "propuesta_id": "prp_1", "carrito_id": "car_1",
        "comercio_id": "com_1", "titular_id": "tit_1",
    }


def test_rechazar_propuesta_desconocida_levanta():
    rechazar, bitacora = _armar()

    with pytest.raises(PropuestaDesconocida):
        rechazar("prp_nunca_existio", "tit_1")

    # Nada que anotar si la propuesta ni existia.
    assert bitacora.eventos == []
