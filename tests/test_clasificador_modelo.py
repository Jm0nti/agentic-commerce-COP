"""`ClasificadorConModelo`: contra un `ModeloDeLenguaje` de mentira que
devuelve el texto que la prueba le indique -- sin DeepSeek, sin red.

Lo central: el contrato de salida es cerrado. Cualquier desvio (JSON roto,
intencion inventada, confianza fuera de rango, campo faltante, proveedor
caido) termina en respaldo, nunca en una intencion "parecida".
"""

from __future__ import annotations

import json

import pytest

from agora.agente.clasificacion.modelo import (
    SISTEMA_CLASIFICADOR,
    ClasificadorConModelo,
    armar_instruccion,
    interpretar_respuesta,
)
from agora.agente.intencion import OrigenDeClasificacion, TipoDeIntencion
from agora.model.commons.errores import ModeloNoDisponible, RespuestaModeloInvalida
from agora.model.agente.gateways.modelo_lenguaje import LlamadaHerramienta, Mensaje


class _ModeloFijo:
    def __init__(self, respuesta: str | Exception) -> None:
        self._respuesta = respuesta
        self.pedidos: list[tuple[str, str]] = []

    def generar(self, sistema: str, instruccion: str) -> str:
        self.pedidos.append((sistema, instruccion))
        if isinstance(self._respuesta, Exception):
            raise self._respuesta
        return self._respuesta

    def responder(self, mensajes, herramientas):
        raise AssertionError("clasificar no es un turno: nunca debe usar responder()")


def _json(**campos) -> str:
    return json.dumps(campos)


def test_respuesta_valida_se_convierte_en_clasificacion_de_modelo():
    modelo = _ModeloFijo(_json(intencion="carrito_pago", confianza=0.9, motivo="continua la compra"))

    clasificacion = ClasificadorConModelo(modelo).clasificar("si, dale")

    assert clasificacion.intencion is TipoDeIntencion.CARRITO_PAGO
    assert clasificacion.origen is OrigenDeClasificacion.MODELO
    assert clasificacion.confianza == 0.9
    assert modelo.pedidos[0][0] == SISTEMA_CLASIFICADOR


@pytest.mark.parametrize(
    "crudo",
    [
        "no es json",
        "[1, 2, 3]",
        _json(intencion="pagar_ya", confianza=0.9, motivo="x"),        # intencion inventada
        _json(intencion="soporte", confianza=1.5, motivo="x"),          # fuera de rango
        _json(intencion="soporte", confianza=True, motivo="x"),         # bool no es numero
        _json(intencion="soporte", confianza="alta", motivo="x"),
        _json(intencion="soporte", motivo="x"),                          # falta confianza
        _json(intencion="soporte", confianza=0.9),                       # falta motivo
        _json(intencion="soporte", confianza=0.9, motivo=["x"]),
        '{"intencion": "soporte", "confianza": NaN, "motivo": "x"}',
    ],
)
def test_cualquier_desvio_del_contrato_es_respaldo(crudo):
    clasificacion = ClasificadorConModelo(_ModeloFijo(crudo)).clasificar("algo")
    assert not clasificacion.decidida
    assert clasificacion.intencion is None
    assert "RespuestaModeloInvalida" in clasificacion.motivo


def test_interpretar_respuesta_levanta_en_vez_de_reparar():
    with pytest.raises(RespuestaModeloInvalida):
        interpretar_respuesta(_json(intencion="Soporte", confianza=0.9, motivo="x"))


def test_proveedor_caido_es_respaldo_y_no_tumba_el_turno():
    modelo = _ModeloFijo(ModeloNoDisponible("DeepSeek no respondio: timeout"))
    clasificacion = ClasificadorConModelo(modelo).clasificar("algo")
    assert not clasificacion.decidida
    assert "ModeloNoDisponible" in clasificacion.motivo


def test_un_bug_que_no_es_error_de_dominio_no_se_esconde():
    with pytest.raises(KeyError):
        ClasificadorConModelo(_ModeloFijo(KeyError("bug"))).clasificar("algo")


def test_confianza_bajo_el_umbral_es_respaldo():
    modelo = _ModeloFijo(_json(intencion="estado", confianza=0.4, motivo="no se"))
    clasificacion = ClasificadorConModelo(modelo, umbral_confianza=0.6).clasificar("mmm")
    assert not clasificacion.decidida
    assert "confianza 0.40 < 0.60" in clasificacion.motivo


def test_confianza_justo_en_el_umbral_se_acepta():
    modelo = _ModeloFijo(_json(intencion="estado", confianza=0.6, motivo="ok"))
    assert ClasificadorConModelo(modelo, umbral_confianza=0.6).clasificar("x").decidida


def test_umbral_invalido_se_rechaza_al_construir():
    with pytest.raises(ValueError):
        ClasificadorConModelo(_ModeloFijo("{}"), umbral_confianza=2)


def test_la_instruccion_lleva_contexto_de_persona_y_asistente_pero_no_system_ni_tool():
    historial = [
        Mensaje(rol="system", contenido="PROMPT GENERAL SECRETO"),
        Mensaje(rol="user", contenido="busca cuadernos"),
        Mensaje(
            rol="assistant", contenido=None,
            llamadas=(LlamadaHerramienta(id="c1", nombre="buscar_productos"),),
        ),
        Mensaje(rol="tool", contenido='{"nota": "CONTENIDO DE HERRAMIENTA"}', id_llamada="c1"),
        Mensaje(rol="assistant", contenido="Hay un cuaderno a 5.000. ¿Lo compro?"),
    ]

    instruccion = armar_instruccion("si, dale", historial)

    assert "[persona] busca cuadernos" in instruccion
    assert "[asistente] (uso herramientas: buscar_productos)" in instruccion
    assert "[asistente] Hay un cuaderno a 5.000. ¿Lo compro?" in instruccion
    assert "PROMPT GENERAL SECRETO" not in instruccion
    assert "CONTENIDO DE HERRAMIENTA" not in instruccion
    assert instruccion.rstrip().endswith("<<<\nsi, dale\n>>>")


def test_la_instruccion_solo_lleva_los_ultimos_mensajes_y_los_recorta():
    historial = [Mensaje(rol="user", contenido=f"mensaje {i} " + "x" * 1000) for i in range(20)]
    instruccion = armar_instruccion("ultimo", historial)
    assert "mensaje 0 " not in instruccion
    assert "mensaje 19 " in instruccion
    assert "x" * 400 not in instruccion


def test_sin_historial_lo_dice_explicitamente():
    assert "(sin contexto previo)" in armar_instruccion("hola", [])
