"""`chat --mostrar-intencion` (migracion a agentes, etapa 1): la decision del
orquestador se imprime en cada turno, y solo si se pide. Contenedor real,
modelo de mentira, `input()` guionado -- sin DeepSeek ni terminal."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from agora.composicion.configuracion import leer_configuracion
from agora.composicion.contenedor import construir
from agora.entradas.cli.__main__ import cmd_chat
from agora.puertos.modelo_lenguaje import RespuestaModelo


class _ModeloDeTexto:
    def generar(self, sistema, instruccion):
        raise AssertionError("los mensajes de esta prueba se resuelven por reglas")

    def responder(self, mensajes, herramientas):
        return RespuestaModelo(contenido="respuesta de prueba")


def _contenedor(tmp_path):
    config = leer_configuracion({
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
    })
    return replace(construir(config), modelo_lenguaje=_ModeloDeTexto())


def _guion(monkeypatch, *lineas):
    pendientes = list(lineas) + ["salir"]
    monkeypatch.setattr("builtins.input", lambda _prompt="": pendientes.pop(0))


def test_con_la_bandera_imprime_la_intencion_de_cada_turno(tmp_path, monkeypatch, capsys):
    _guion(monkeypatch, "¿que tiendas hay?", "¿cual es el estado de mi pago?")

    assert cmd_chat(SimpleNamespace(mostrar_intencion=True), _contenedor(tmp_path)) == 0

    salida = capsys.readouterr().out
    assert "[intencion: catalogo | reglas | confianza 1.00" in salida
    assert "[intencion: estado | reglas | confianza 1.00" in salida
    assert salida.count("agente> respuesta de prueba") == 2


def test_sin_la_bandera_no_imprime_nada_extra(tmp_path, monkeypatch, capsys):
    _guion(monkeypatch, "¿que tiendas hay?")

    assert cmd_chat(SimpleNamespace(mostrar_intencion=False), _contenedor(tmp_path)) == 0

    assert "[intencion:" not in capsys.readouterr().out
