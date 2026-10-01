"""La etapa 2 armada de punta a punta: `OPENAI_API_KEY` -> `Contenedor.
buscador_documental` -> contexto del nodo de soporte en el `Agente` real.

Nunca toca la red: con llave, el `Contenedor` arma el adaptador de OpenAI
pero no lo llama (el indice se construye en la primera busqueda), y las
pruebas que buscan reemplazan el buscador por uno de mentira."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from agora.driven_adapters.recuperacion_langchain import BuscadorDocumentalLangChain
from agora.app_service.config.agente import construir_agente, construir_contextos
from agora.app_service.config.configuracion import (
    SOPORTE_DOCUMENTOS_POR_DEFECTO,
    ConfiguracionInvalida,
    leer_configuracion,
)
from agora.app_service.config.contenedor import construir
from agora.entry_points.cli.cli import cmd_chat
from agora.model.agente.gateways.modelo_lenguaje import RespuestaModelo
from agora.model.agente.gateways.recuperacion import FragmentoRecuperado


def _entorno(tmp_path, **extra) -> dict:
    return {
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
        **extra,
    }


class _Modelo:
    def __init__(self):
        self.vistas = []

    def generar(self, sistema, instruccion):
        raise AssertionError("los mensajes de estas pruebas se resuelven por reglas")

    def responder(self, mensajes, herramientas):
        self.vistas.append((list(mensajes), list(herramientas)))
        return RespuestaModelo(contenido="respuesta de prueba")


class _BuscadorFijo:
    def __init__(self):
        self.consultas = []

    def buscar(self, consulta, limite=4):
        self.consultas.append(consulta)
        return [
            FragmentoRecuperado(
                fuente="docs/soporte/el-mandato-y-sus-controles.md",
                seccion="El mandato y sus controles > Vigencia",
                texto="Un mandato vencido no autoriza nada. Tope de 20.000 COP.",
                puntaje=0.9,
            )
        ]


# -- configuracion -------------------------------------------------------------- #


def test_sin_openai_api_key_no_hay_buscador_ni_contexto(tmp_path):
    contenedor = construir(leer_configuracion(_entorno(tmp_path)))
    assert contenedor.config.openai_llave_api == ""
    assert contenedor.buscador_documental is None
    assert construir_contextos(contenedor) == {}


def test_con_llave_se_arma_el_buscador_real_sobre_el_corpus_sin_tocar_la_red(tmp_path):
    contenedor = construir(leer_configuracion(_entorno(tmp_path, OPENAI_API_KEY="sk-de-prueba")))

    buscador = contenedor.buscador_documental
    assert isinstance(buscador, BuscadorDocumentalLangChain)
    assert buscador.cantidad_de_fragmentos > 0
    assert not buscador.indexado
    assert contenedor.config.soporte_documentos_path == SOPORTE_DOCUMENTOS_POR_DEFECTO
    assert contenedor.config.embeddings_modelo == "text-embedding-3-small"
    assert set(construir_contextos(contenedor)) == {"soporte"}


def test_llave_con_carpeta_de_documentos_inexistente_no_deja_arrancar(tmp_path):
    with pytest.raises(ConfiguracionInvalida, match="documentos de soporte"):
        leer_configuracion(_entorno(
            tmp_path, OPENAI_API_KEY="sk-de-prueba", AGORA_SOPORTE_DOCUMENTOS=str(tmp_path / "no-existe"),
        ))


def test_sin_llave_la_carpeta_de_documentos_ni_se_mira(tmp_path):
    config = leer_configuracion(_entorno(tmp_path, AGORA_SOPORTE_DOCUMENTOS=str(tmp_path / "no-existe")))
    assert config.openai_llave_api == ""


def test_se_puede_apuntar_a_otra_carpeta_y_otro_modelo(tmp_path):
    carpeta = tmp_path / "corpus"
    carpeta.mkdir()
    (carpeta / "faq.md").write_text("# FAQ\n\nUna pregunta frecuente.", encoding="utf-8")

    contenedor = construir(leer_configuracion(_entorno(
        tmp_path, OPENAI_API_KEY="sk-de-prueba", AGORA_SOPORTE_DOCUMENTOS=str(carpeta),
        AGORA_EMBEDDINGS_MODELO="text-embedding-3-large",
    )))

    assert contenedor.buscador_documental.cantidad_de_fragmentos == 1
    assert contenedor.config.embeddings_modelo == "text-embedding-3-large"


# -- agente real ------------------------------------------------------------------ #


def _agente_con_buscador_fijo(tmp_path):
    contenedor = construir(leer_configuracion(_entorno(tmp_path)))
    buscador, modelo = _BuscadorFijo(), _Modelo()
    contenedor = replace(contenedor, modelo_lenguaje=modelo, buscador_documental=buscador)
    agente = construir_agente(contenedor)
    assert agente is not None
    return contenedor, agente, buscador, modelo


def test_una_pregunta_de_soporte_llega_al_modelo_con_documentacion_y_sin_cifras(tmp_path):
    _, agente, buscador, modelo = _agente_con_buscador_fijo(tmp_path)
    conversacion = agente.iniciar()

    agente.turno(conversacion, "¿qué es un mandato?")

    sistema, definiciones = modelo.vistas[-1][0][0].contenido, modelo.vistas[-1][1]
    assert buscador.consultas == ["¿qué es un mandato?"]
    assert "Un mandato vencido no autoriza nada" in sistema
    assert "20.000" not in sistema
    assert definiciones == []


def test_una_compra_no_consulta_la_documentacion(tmp_path):
    _, agente, buscador, modelo = _agente_con_buscador_fijo(tmp_path)
    conversacion = agente.iniciar()

    agente.turno(conversacion, "quiero comprar algo barato")

    assert buscador.consultas == []
    assert "Documentacion recuperada" not in modelo.vistas[-1][0][0].contenido


def test_chat_mostrar_intencion_imprime_las_fuentes_del_contexto(tmp_path, monkeypatch, capsys):
    contenedor, _, _, _ = _agente_con_buscador_fijo(tmp_path)
    pendientes = ["¿qué es un mandato?", "salir"]
    monkeypatch.setattr("builtins.input", lambda _prompt="": pendientes.pop(0))

    assert cmd_chat(SimpleNamespace(mostrar_intencion=True), construir_agente(contenedor)) == 0

    salida = capsys.readouterr().out
    assert "[intencion: soporte | reglas" in salida
    assert "[contexto de soporte: docs/soporte/el-mandato-y-sus-controles.md]" in salida
