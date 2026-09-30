"""`Agente.turno` con clasificador (migracion a agentes, etapa 1): el turno
DECIDE la ruta antes de EJECUTAR, y la ruta manda sobre que ve y que puede
ejecutar el modelo.

Usa un clasificador fijo (no reglas ni modelo) para aislar lo que se prueba
aca -- el enrutamiento -- de como se clasifica, que ya tiene sus propias
pruebas (`test_clasificador_*.py`).
"""

from __future__ import annotations

import json

from agora.agente.conversacion import Agente
from agora.agente.herramientas import CATALOGO_DE_HERRAMIENTAS, construir_herramientas
from agora.agente.intencion import ClasificacionDeIntencion, OrigenDeClasificacion, TipoDeIntencion
from agora.model.agente.gateways.modelo_lenguaje import LlamadaHerramienta, Mensaje, RespuestaModelo


class _ModeloGuionado:
    def __init__(self, respuestas: list[RespuestaModelo]) -> None:
        self._respuestas = list(respuestas)
        self.llamadas: list[tuple[list[Mensaje], list]] = []

    def generar(self, sistema: str, instruccion: str) -> str:
        raise AssertionError("el clasificador de estas pruebas es fijo: no usa el modelo")

    def responder(self, mensajes, herramientas):
        self.llamadas.append((list(mensajes), list(herramientas)))
        return self._respuestas.pop(0)


class _ClasificadorFijo:
    def __init__(self, *resultados: ClasificacionDeIntencion) -> None:
        self._resultados = list(resultados)
        self.recibido: list[tuple[str, tuple[Mensaje, ...]]] = []

    def clasificar(self, mensaje, historial=()):
        self.recibido.append((mensaje, tuple(historial)))
        return self._resultados.pop(0)


class _Espias:
    """Una funcion por herramienta que registra si alguien la ejecuto de
    verdad -- la unica forma de probar "acceso fisico", no solo "anuncio"."""

    def __init__(self) -> None:
        self.ejecutadas: list[str] = []

    def funcion(self, nombre: str):
        def _f(**kwargs):
            self.ejecutadas.append(nombre)
            return {"herramienta": nombre, "ok": True}

        return _f

    def herramientas(self):
        return construir_herramientas(**{n: self.funcion(n) for n in CATALOGO_DE_HERRAMIENTAS})


def _decidida(intencion: TipoDeIntencion) -> ClasificacionDeIntencion:
    return ClasificacionDeIntencion(
        intencion=intencion, origen=OrigenDeClasificacion.REGLAS, confianza=1.0, motivo="prueba",
    )


def _agente(respuestas, *clasificaciones):
    espias = _Espias()
    modelo = _ModeloGuionado(respuestas)
    clasificador = _ClasificadorFijo(*clasificaciones)
    agente = Agente(modelo=modelo, herramientas=espias.herramientas(), clasificador=clasificador)
    return agente, modelo, clasificador, espias


def _nombres(definiciones) -> set[str]:
    return {d.nombre for d in definiciones}


def test_solo_se_anuncian_las_herramientas_de_la_ruta():
    agente, modelo, _, _ = _agente(
        [RespuestaModelo(contenido="hay dos tiendas")], _decidida(TipoDeIntencion.CATALOGO),
    )

    agente.turno(agente.iniciar(), "que tiendas hay")

    _, definiciones = modelo.llamadas[0]
    assert _nombres(definiciones) == {"buscar_comercios", "buscar_productos", "ver_producto"}


def test_la_ruta_de_compra_anuncia_catalogo_y_carrito_pero_no_estado():
    agente, modelo, _, _ = _agente(
        [RespuestaModelo(contenido="listo")], _decidida(TipoDeIntencion.CARRITO_PAGO),
    )

    agente.turno(agente.iniciar(), "quiero comprar")

    _, definiciones = modelo.llamadas[0]
    assert "consultar_estado" not in _nombres(definiciones)
    assert {"armar_carrito", "pagar", "buscar_productos"} <= _nombres(definiciones)


def test_soporte_no_ve_ni_puede_ejecutar_nada_que_mueva_dinero():
    """Aunque el modelo alucine una llamada a `pagar` en un turno de
    soporte, la funcion real nunca corre: se le devuelve un error de rol
    "tool" y el turno sigue."""
    alucinada = LlamadaHerramienta(
        id="c1", nombre="pagar", argumentos={"mandato_id": "mnd_x", "carrito_id": "car_x"},
    )
    agente, modelo, _, espias = _agente(
        [
            RespuestaModelo(contenido=None, llamadas=(alucinada,)),
            RespuestaModelo(contenido="un mandato es un permiso firmado"),
        ],
        _decidida(TipoDeIntencion.SOPORTE),
    )
    conversacion = agente.iniciar()

    respuesta = agente.turno(conversacion, "que es un mandato?")

    assert respuesta == "un mandato es un permiso firmado"
    assert _nombres(modelo.llamadas[0][1]) == set()
    assert espias.ejecutadas == []
    error = json.loads(conversacion.mensajes[-2].contenido)["error"]
    assert "no esta habilitada" in error and "soporte" in error


def test_una_herramienta_de_la_ruta_si_se_ejecuta():
    llamada = LlamadaHerramienta(id="c1", nombre="consultar_estado", argumentos={"intencion_id": "i"})
    agente, _, _, espias = _agente(
        [RespuestaModelo(contenido=None, llamadas=(llamada,)), RespuestaModelo(contenido="aprobado")],
        _decidida(TipoDeIntencion.ESTADO),
    )

    agente.turno(agente.iniciar(), "como va mi pago")

    assert espias.ejecutadas == ["consultar_estado"]


def test_la_instruccion_del_orquestador_va_en_el_sistema_de_la_vista_y_no_se_guarda():
    llamada = LlamadaHerramienta(id="c1", nombre="consultar_estado", argumentos={"intencion_id": "i"})
    agente, modelo, _, _ = _agente(
        [RespuestaModelo(contenido=None, llamadas=(llamada,)), RespuestaModelo(contenido="ok")],
        _decidida(TipoDeIntencion.ESTADO),
    )
    conversacion = agente.iniciar()
    prompt_general = conversacion.mensajes[0].contenido

    agente.turno(conversacion, "como va mi pago")

    # En CADA ronda del loop (no solo la primera) el modelo ve un unico
    # mensaje de sistema, al principio: el prompt general + la instruccion
    # de la ruta. Nunca un "system" suelto a mitad del historial.
    for vista, _ in modelo.llamadas:
        assert [m.rol for m in vista].count("system") == 1
        assert vista[0].rol == "system"
        assert vista[0].contenido.startswith(prompt_general)
        assert "Intencion clasificada: estado" in vista[0].contenido
    # ...pero la conversacion guardada no la tiene.
    assert conversacion.mensajes[0].contenido == prompt_general
    assert [m.rol for m in conversacion.mensajes] == ["system", "user", "assistant", "tool", "assistant"]


def test_en_el_segundo_turno_la_instruccion_vieja_no_se_arrastra():
    agente, modelo, _, _ = _agente(
        [RespuestaModelo(contenido="hay tiendas"), RespuestaModelo(contenido="ok")],
        _decidida(TipoDeIntencion.CATALOGO),
        _decidida(TipoDeIntencion.SOPORTE),
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "que tiendas hay")
    agente.turno(conversacion, "que es un mandato")

    sistema_segundo_turno = modelo.llamadas[1][0][0].contenido
    assert "Intencion clasificada: soporte" in sistema_segundo_turno
    assert "Intencion clasificada: catalogo" not in sistema_segundo_turno


def test_cada_turno_queda_registrado_en_clasificaciones():
    primera, segunda = _decidida(TipoDeIntencion.CATALOGO), _decidida(TipoDeIntencion.ESTADO)
    agente, _, _, _ = _agente(
        [RespuestaModelo(contenido="a"), RespuestaModelo(contenido="b")], primera, segunda,
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "uno")
    agente.turno(conversacion, "dos")

    assert conversacion.clasificaciones == [primera, segunda]


def test_el_clasificador_recibe_el_historial_previo_sin_el_mensaje_actual():
    agente, _, clasificador, _ = _agente(
        [RespuestaModelo(contenido="a"), RespuestaModelo(contenido="b")],
        _decidida(TipoDeIntencion.CATALOGO),
        _decidida(TipoDeIntencion.CARRITO_PAGO),
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "que tiendas hay")
    agente.turno(conversacion, "si, dale")

    mensaje, historial = clasificador.recibido[1]
    assert mensaje == "si, dale"
    assert [m.contenido for m in historial if m.rol == "user"] == ["que tiendas hay"]


def test_respaldo_se_comporta_como_el_agente_de_antes():
    agente, modelo, _, _ = _agente(
        [RespuestaModelo(contenido="ok")], ClasificacionDeIntencion.respaldo("ambiguo"),
    )
    conversacion = agente.iniciar()

    agente.turno(conversacion, "mmm")

    vista, definiciones = modelo.llamadas[0]
    assert _nombres(definiciones) == set(CATALOGO_DE_HERRAMIENTAS)
    assert [m.rol for m in vista] == ["system", "user"]
    assert conversacion.clasificaciones[0].origen is OrigenDeClasificacion.RESPALDO


def test_sin_clasificador_no_hay_instruccion_ni_clasificaciones():
    espias = _Espias()
    modelo = _ModeloGuionado([RespuestaModelo(contenido="hola")])
    agente = Agente(modelo=modelo, herramientas=espias.herramientas())
    conversacion = agente.iniciar()

    agente.turno(conversacion, "hola")

    vista, definiciones = modelo.llamadas[0]
    assert _nombres(definiciones) == set(CATALOGO_DE_HERRAMIENTAS)
    assert [m.rol for m in vista] == ["system", "user"]
    assert conversacion.clasificaciones == []
