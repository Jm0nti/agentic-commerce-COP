"""`AGORA_CLASIFICADOR` de punta a punta: la configuracion lo lee y lo valida,
`composicion/agente.py` arma el clasificador que corresponde, y el agente
real (herramientas reales, contenedor real) enruta con reglas sin tocar el
modelo cuando el mensaje es inequivoco."""

from __future__ import annotations

from dataclasses import replace

import pytest

from agora.agente.clasificacion import (
    ClasificadorConModelo,
    ClasificadorEnCadena,
    ClasificadorPorReglas,
)
from agora.agente.intencion import OrigenDeClasificacion, TipoDeIntencion
from agora.composicion.agente import construir_agente, construir_clasificador
from agora.composicion.configuracion import ConfiguracionInvalida, leer_configuracion
from agora.composicion.contenedor import construir
from agora.puertos.modelo_lenguaje import RespuestaModelo


class _ModeloQueContestaTexto:
    def __init__(self) -> None:
        self.generar_llamado = False
        self.definiciones: list = []

    def generar(self, sistema, instruccion):
        self.generar_llamado = True
        return '{"intencion": "soporte", "confianza": 0.9, "motivo": "x"}'

    def responder(self, mensajes, herramientas):
        self.definiciones.append({d.nombre for d in herramientas})
        return RespuestaModelo(contenido="ok")


def _entorno(tmp_path, **extra) -> dict:
    return {
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
        **extra,
    }


def test_por_defecto_el_clasificador_es_hibrido(tmp_path):
    assert leer_configuracion(_entorno(tmp_path)).clasificador_intencion == "hibrido"


@pytest.mark.parametrize("modo", ["hibrido", "reglas", "apagado"])
def test_los_tres_modos_se_aceptan(tmp_path, modo):
    config = leer_configuracion(_entorno(tmp_path, AGORA_CLASIFICADOR=modo))
    assert config.clasificador_intencion == modo


def test_un_modo_desconocido_no_deja_arrancar(tmp_path):
    with pytest.raises(ConfiguracionInvalida, match="AGORA_CLASIFICADOR"):
        leer_configuracion(_entorno(tmp_path, AGORA_CLASIFICADOR="magico"))


def test_construir_clasificador_por_modo():
    modelo = _ModeloQueContestaTexto()
    assert construir_clasificador("apagado", modelo) is None
    assert isinstance(construir_clasificador("reglas", modelo), ClasificadorPorReglas)
    hibrido = construir_clasificador("hibrido", modelo)
    assert isinstance(hibrido, ClasificadorEnCadena)
    assert [type(c) for c in hibrido._clasificadores] == [ClasificadorPorReglas, ClasificadorConModelo]
    with pytest.raises(ValueError):
        construir_clasificador("magico", modelo)


def _agente_real(tmp_path, modo: str):
    contenedor = construir(leer_configuracion(_entorno(tmp_path, AGORA_CLASIFICADOR=modo)))
    modelo = _ModeloQueContestaTexto()
    contenedor = replace(contenedor, modelo_lenguaje=modelo)
    agente = construir_agente(contenedor)
    assert agente is not None
    return agente, modelo


def test_hibrido_resuelve_por_reglas_sin_gastar_una_llamada_al_modelo(tmp_path):
    agente, modelo = _agente_real(tmp_path, "hibrido")
    conversacion = agente.iniciar()

    agente.turno(conversacion, "¿cual es el estado de mi pago?")

    assert modelo.generar_llamado is False
    assert conversacion.clasificaciones[-1].intencion is TipoDeIntencion.ESTADO
    assert modelo.definiciones[-1] == {"consultar_estado"}


def test_hibrido_consulta_al_modelo_cuando_las_reglas_se_abstienen(tmp_path):
    agente, modelo = _agente_real(tmp_path, "hibrido")
    conversacion = agente.iniciar()

    agente.turno(conversacion, "si, dale")

    assert modelo.generar_llamado is True
    assert conversacion.clasificaciones[-1].origen is OrigenDeClasificacion.MODELO
    assert modelo.definiciones[-1] == set()  # soporte: ninguna herramienta


def test_reglas_sin_certeza_va_por_respaldo_sin_llamar_al_modelo(tmp_path):
    agente, modelo = _agente_real(tmp_path, "reglas")
    conversacion = agente.iniciar()

    agente.turno(conversacion, "si, dale")

    assert modelo.generar_llamado is False
    assert conversacion.clasificaciones[-1].origen is OrigenDeClasificacion.RESPALDO
    assert len(modelo.definiciones[-1]) == 6


def test_apagado_es_el_agente_de_la_etapa_7(tmp_path):
    agente, modelo = _agente_real(tmp_path, "apagado")
    conversacion = agente.iniciar()

    agente.turno(conversacion, "¿cual es el estado de mi pago?")

    assert conversacion.clasificaciones == []
    assert len(modelo.definiciones[-1]) == 6
