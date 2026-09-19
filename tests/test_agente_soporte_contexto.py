"""`Agente` con contexto por nodo (migracion a agentes, etapa 2): soporte
inyecta documentacion en su turno sin ganar ninguna herramienta, y ninguna
ruta que pueda mover dinero recibe contexto recuperado."""

from __future__ import annotations

import json

import pytest

from agora.agente.contexto import ContextoInyectado
from agora.agente.conversacion import Agente
from agora.agente.herramientas import CATALOGO_DE_HERRAMIENTAS, construir_herramientas
from agora.agente.intencion import ClasificacionDeIntencion, OrigenDeClasificacion, TipoDeIntencion
from agora.puertos.modelo_lenguaje import LlamadaHerramienta, Mensaje, RespuestaModelo


class _ModeloGuionado:
    def __init__(self, respuestas):
        self._respuestas = list(respuestas)
        self.llamadas: list[tuple[list[Mensaje], list]] = []

    def generar(self, sistema, instruccion):
        raise AssertionError("no se usa")

    def responder(self, mensajes, herramientas):
        self.llamadas.append((list(mensajes), list(herramientas)))
        return self._respuestas.pop(0)


class _ClasificadorFijo:
    def __init__(self, *intenciones):
        self._pendientes = list(intenciones)

    def clasificar(self, mensaje, historial=()):
        intencion = self._pendientes.pop(0)
        if intencion is None:
            return ClasificacionDeIntencion.respaldo("prueba")
        return ClasificacionDeIntencion(
            intencion=intencion, origen=OrigenDeClasificacion.REGLAS, confianza=1.0,
        )


class _ContextoEspia:
    def __init__(self, texto="DOCUMENTACION DE PRUEBA", fuentes=("docs/soporte/a.md",)):
        self.pedidos: list[tuple[str, tuple]] = []
        self._contexto = ContextoInyectado(texto=texto, fuentes=fuentes)

    def contexto_para(self, mensaje, historial=()):
        self.pedidos.append((mensaje, tuple(historial)))
        return self._contexto


class _Espias:
    def __init__(self):
        self.ejecutadas: list[str] = []

    def herramientas(self):
        def funcion(nombre):
            def _f(**_):
                self.ejecutadas.append(nombre)
                return {"ok": True}
            return _f
        return construir_herramientas(**{n: funcion(n) for n in CATALOGO_DE_HERRAMIENTAS})


def _agente(respuestas, intenciones, contextos):
    espias = _Espias()
    modelo = _ModeloGuionado(respuestas)
    agente = Agente(
        modelo=modelo,
        herramientas=espias.herramientas(),
        clasificador=_ClasificadorFijo(*intenciones),
        contextos=contextos,
    )
    return agente, modelo, espias


def test_soporte_inyecta_su_contexto_en_el_sistema_de_la_vista_y_no_en_el_historial():
    espia = _ContextoEspia()
    agente, modelo, _ = _agente(
        [RespuestaModelo(contenido="un mandato es un permiso")], [TipoDeIntencion.SOPORTE],
        {"soporte": espia},
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "que es un mandato?")

    vista, definiciones = modelo.llamadas[0]
    assert "DOCUMENTACION DE PRUEBA" in vista[0].contenido
    assert "Intencion clasificada: soporte" in vista[0].contenido
    assert definiciones == []  # soporte sigue sin herramientas
    assert all("DOCUMENTACION DE PRUEBA" not in (m.contenido or "") for m in conversacion.mensajes)
    assert conversacion.contextos == [("soporte", espia._contexto)]
    assert espia.pedidos == [("que es un mandato?", tuple(conversacion.mensajes[:1]))]


def test_el_contexto_se_pide_una_sola_vez_por_turno_aunque_el_loop_de_varias_vueltas():
    """Soporte no tiene herramientas, pero si el modelo alucina una, el loop
    da una vuelta mas: el contexto no se vuelve a pedir, y la herramienta
    alucinada sigue sin ejecutarse."""
    espia = _ContextoEspia()
    alucinada = LlamadaHerramienta(id="c1", nombre="pagar", argumentos={"mandato_id": "m", "carrito_id": "c"})
    agente, modelo, espias = _agente(
        [RespuestaModelo(contenido=None, llamadas=(alucinada,)), RespuestaModelo(contenido="ok")],
        [TipoDeIntencion.SOPORTE],
        {"soporte": espia},
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "que es un mandato?")

    assert len(espia.pedidos) == 1
    assert len(modelo.llamadas) == 2
    assert all("DOCUMENTACION DE PRUEBA" in vista[0].contenido for vista, _ in modelo.llamadas)
    assert espias.ejecutadas == []
    assert "no esta habilitada" in json.loads(conversacion.mensajes[-2].contenido)["error"]


@pytest.mark.parametrize(
    "intencion",
    [TipoDeIntencion.CATALOGO, TipoDeIntencion.CARRITO_PAGO, TipoDeIntencion.ESTADO, None],
)
def test_las_rutas_sin_soporte_no_piden_contexto(intencion):
    espia = _ContextoEspia()
    agente, modelo, _ = _agente(
        [RespuestaModelo(contenido="ok")], [intencion], {"soporte": espia},
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "hola")

    assert espia.pedidos == []
    assert "DOCUMENTACION DE PRUEBA" not in modelo.llamadas[0][0][0].contenido
    assert conversacion.contextos == []


def test_un_proveedor_de_contexto_no_puede_colgarse_del_nodo_de_dinero():
    with pytest.raises(RuntimeError, match="flujo de dinero"):
        _agente([], [], {"carrito_pago": _ContextoEspia()})


def test_un_proveedor_de_contexto_no_puede_colgarse_de_un_nodo_desconocido():
    with pytest.raises(RuntimeError, match="nodo desconocido"):
        _agente([], [], {"tesoreria": _ContextoEspia()})


def test_una_ruta_con_el_nodo_de_dinero_no_recibe_contexto_de_ningun_otro_nodo():
    """La ruta de compra junta catalogo + carrito_pago. Aunque catalogo
    tuviera contexto (hoy no lo tiene), no puede llegar al turno donde
    esta `pagar`."""
    espia = _ContextoEspia()
    agente, modelo, _ = _agente(
        [RespuestaModelo(contenido="ok"), RespuestaModelo(contenido="ok")],
        [TipoDeIntencion.CARRITO_PAGO, TipoDeIntencion.CATALOGO],
        {"catalogo": espia},
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "quiero comprar")
    assert espia.pedidos == []
    assert "DOCUMENTACION DE PRUEBA" not in modelo.llamadas[0][0][0].contenido

    agente.turno(conversacion, "que tiendas hay")
    assert len(espia.pedidos) == 1


def test_un_proveedor_que_no_tiene_nada_que_agregar_no_deja_rastro():
    class _Nada:
        def contexto_para(self, mensaje, historial=()):
            return None

    agente, modelo, _ = _agente(
        [RespuestaModelo(contenido="ok")], [TipoDeIntencion.SOPORTE], {"soporte": _Nada()},
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "que es un mandato?")

    assert conversacion.contextos == []
    assert "Intencion clasificada: soporte" in modelo.llamadas[0][0][0].contenido
