"""`AGORA_ORQUESTACION` de punta a punta (migracion a agentes, etapa 3): la
configuracion lo lee y lo valida, `composicion/agente.py` devuelve el agente
envuelto en grafo o el de siempre, y un venv sin `langgraph` falla con un
mensaje que dice que hacer en vez de un `ImportError` pelado.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agora.usecase.agente.conversacion import Agente
from agora.usecase.agente.grafo import AgenteEnGrafo
from agora.model.agente.intencion import TipoDeIntencion
from agora.composicion import agente as composicion_agente
from agora.composicion.agente import construir_agente, envolver_en_grafo
from agora.composicion.configuracion import ConfiguracionInvalida, leer_configuracion
from agora.composicion.contenedor import construir
from agora.model.agente.gateways.modelo_lenguaje import RespuestaModelo


class _ModeloQueContestaTexto:
    def __init__(self) -> None:
        self.definiciones: list = []

    def generar(self, sistema, instruccion):
        raise AssertionError("las reglas resuelven estos mensajes: no se usa el modelo")

    def responder(self, mensajes, herramientas):
        self.definiciones.append({d.nombre for d in herramientas})
        return RespuestaModelo(contenido="ok")


def _entorno(tmp_path, **extra) -> dict:
    return {
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
        **extra,
    }


def _agente_real(tmp_path, modo: str | None = None):
    extra = {} if modo is None else {"AGORA_ORQUESTACION": modo}
    contenedor = construir(leer_configuracion(_entorno(tmp_path, **extra)))
    modelo = _ModeloQueContestaTexto()
    contenedor = replace(contenedor, modelo_lenguaje=modelo)
    agente = construir_agente(contenedor)
    assert agente is not None
    return agente, modelo


# -- la configuracion --------------------------------------------------- #


def test_por_defecto_la_orquestacion_es_grafo(tmp_path):
    assert leer_configuracion(_entorno(tmp_path)).orquestacion == "grafo"


@pytest.mark.parametrize("modo", ["grafo", "directo"])
def test_los_dos_modos_se_aceptan(tmp_path, modo):
    config = leer_configuracion(_entorno(tmp_path, AGORA_ORQUESTACION=modo))
    assert config.orquestacion == modo


def test_un_modo_desconocido_no_deja_arrancar(tmp_path):
    with pytest.raises(ConfiguracionInvalida, match="AGORA_ORQUESTACION"):
        leer_configuracion(_entorno(tmp_path, AGORA_ORQUESTACION="supervisor"))


def test_envolver_en_grafo_rechaza_un_modo_desconocido():
    """`ConfiguracionAgora` ya lo impide; esto cubre a quien llame directo
    sin pasar por la configuracion (mismo criterio que
    `construir_clasificador`)."""
    with pytest.raises(ValueError, match="modo de orquestacion desconocido"):
        envolver_en_grafo(object(), "supervisor")  # type: ignore[arg-type]


# -- lo que devuelve la composicion -------------------------------------- #


def test_por_defecto_construir_agente_devuelve_el_agente_en_grafo(tmp_path):
    agente, _ = _agente_real(tmp_path)

    assert isinstance(agente, AgenteEnGrafo)


def test_en_modo_directo_devuelve_el_agente_de_las_etapas_1_y_2(tmp_path):
    agente, _ = _agente_real(tmp_path, "directo")

    assert isinstance(agente, Agente)
    assert not isinstance(agente, AgenteEnGrafo)


def test_el_modo_grafo_envuelve_al_mismo_agente_no_a_otro():
    """`grafo` no reemplaza nada: adentro sigue estando el `Agente` de las
    etapas 1-2, con sus herramientas, su clasificador y sus contextos."""
    agente = Agente(modelo=_ModeloQueContestaTexto(), herramientas=[])

    envuelto = envolver_en_grafo(agente, "grafo")

    assert isinstance(envuelto, AgenteEnGrafo)
    assert envuelto._agente is agente
    assert envolver_en_grafo(agente, "directo") is agente


# -- que los dos modos hacen lo mismo con el contenedor real -------------- #


@pytest.mark.parametrize("modo", ["grafo", "directo"])
def test_los_dos_modos_enrutan_igual_con_el_contenedor_real(tmp_path, modo):
    agente, modelo = _agente_real(tmp_path, modo)
    conversacion = agente.iniciar()

    respuesta = agente.turno(conversacion, "¿cual es el estado de mi pago?")

    assert respuesta == "ok"
    assert conversacion.clasificaciones[-1].intencion is TipoDeIntencion.ESTADO
    assert modelo.definiciones[-1] == {"consultar_estado"}


@pytest.mark.parametrize("modo", ["grafo", "directo"])
def test_las_herramientas_reales_se_alcanzan_igual_en_los_dos_modos(tmp_path, modo):
    agente, _ = _agente_real(tmp_path, modo)

    assert set(agente._herramientas) == {
        "buscar_comercios", "buscar_productos", "ver_producto",
        "armar_carrito", "pagar", "consultar_estado",
    }


# -- un venv sin langgraph ------------------------------------------------ #


def test_sin_langgraph_el_modo_grafo_falla_con_un_mensaje_accionable(tmp_path, monkeypatch):
    """`_importar_compilador_langgraph` es el punto de import indirecto que
    existe justamente para poder simular esto sin desinstalar nada. Lo que se
    exige del mensaje: que nombre el paquete, el comando para instalarlo y la
    alternativa para seguir sin el."""

    def _no_esta():
        raise ImportError("No module named 'langgraph'")

    monkeypatch.setattr(composicion_agente, "_importar_compilador_langgraph", _no_esta)

    with pytest.raises(ConfiguracionInvalida) as excepcion:
        _agente_real(tmp_path, "grafo")

    mensaje = str(excepcion.value)
    assert "langgraph" in mensaje
    assert "pip install" in mensaje
    assert "AGORA_ORQUESTACION=directo" in mensaje
    assert isinstance(excepcion.value.__cause__, ImportError)


def test_sin_langgraph_el_modo_directo_sigue_funcionando(tmp_path, monkeypatch):
    """La razon de ser del import perezoso: un venv que todavia no corrio
    `pip install -r requirements.txt` despues de esta etapa levanta igual
    mientras no pida el grafo."""

    def _no_esta():
        raise ImportError("No module named 'langgraph'")

    monkeypatch.setattr(composicion_agente, "_importar_compilador_langgraph", _no_esta)

    agente, _ = _agente_real(tmp_path, "directo")

    assert agente.turno(agente.iniciar(), "¿cual es el estado de mi pago?") == "ok"
