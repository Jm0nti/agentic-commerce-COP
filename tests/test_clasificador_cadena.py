"""`ClasificadorEnCadena`: el primero que decide, gana -- y los siguientes
ni se consultan (el modelo cuesta una llamada de API)."""

from __future__ import annotations

import pytest

from agora.agente.clasificacion import ClasificadorEnCadena
from agora.agente.intencion import ClasificacionDeIntencion, OrigenDeClasificacion, TipoDeIntencion


class _Fijo:
    def __init__(self, resultado: ClasificacionDeIntencion) -> None:
        self._resultado = resultado
        self.llamadas = 0

    def clasificar(self, mensaje, historial=()):
        self.llamadas += 1
        return self._resultado


_ESTADO = ClasificacionDeIntencion(
    intencion=TipoDeIntencion.ESTADO, origen=OrigenDeClasificacion.REGLAS, confianza=1.0,
)
_SOPORTE = ClasificacionDeIntencion(
    intencion=TipoDeIntencion.SOPORTE, origen=OrigenDeClasificacion.MODELO, confianza=0.8,
)


def test_si_el_primero_decide_el_segundo_no_se_consulta():
    primero, segundo = _Fijo(_ESTADO), _Fijo(_SOPORTE)
    assert ClasificadorEnCadena(primero, segundo).clasificar("x") is _ESTADO
    assert segundo.llamadas == 0


def test_si_el_primero_se_abstiene_decide_el_segundo():
    primero = _Fijo(ClasificacionDeIntencion.respaldo("reglas: ambiguo"))
    segundo = _Fijo(_SOPORTE)
    assert ClasificadorEnCadena(primero, segundo).clasificar("x") is _SOPORTE
    assert primero.llamadas == 1


def test_si_nadie_decide_conserva_todos_los_motivos_en_orden():
    cadena = ClasificadorEnCadena(
        _Fijo(ClasificacionDeIntencion.respaldo("reglas: ambiguo")),
        _Fijo(ClasificacionDeIntencion.respaldo("modelo: ModeloNoDisponible")),
    )
    resultado = cadena.clasificar("x")
    assert not resultado.decidida
    assert resultado.motivo == "reglas: ambiguo | modelo: ModeloNoDisponible"


def test_una_cadena_vacia_no_tiene_sentido():
    with pytest.raises(ValueError):
        ClasificadorEnCadena()


def test_una_clasificacion_incoherente_no_se_puede_construir():
    with pytest.raises(ValueError):
        ClasificacionDeIntencion(intencion=None, origen=OrigenDeClasificacion.MODELO, confianza=0.5)
    with pytest.raises(ValueError):
        ClasificacionDeIntencion(
            intencion=TipoDeIntencion.ESTADO, origen=OrigenDeClasificacion.RESPALDO, confianza=0.0,
        )
    with pytest.raises(ValueError):
        ClasificacionDeIntencion(
            intencion=TipoDeIntencion.ESTADO, origen=OrigenDeClasificacion.REGLAS, confianza=1.2,
        )
