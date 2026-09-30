"""La trazabilidad de punta a punta: el `Contenedor` real escribe el
`.jsonl`, y el comando `trazas` lo lee.

El archivo es la fuente de verdad; la terminal que lo mira es solo una
ventana. Estas pruebas cubren esa separacion: quien escribe no imprime, y
quien imprime no escribe.
"""

from __future__ import annotations

import json
from dataclasses import replace

from agora.composicion.agente import construir_agente
from agora.composicion.configuracion import NOMBRE_DE_TRAZAS, leer_configuracion
from agora.composicion.contenedor import construir
from agora.entradas.cli.__main__ import cmd_trazas
from agora.model.agente.gateways.modelo_lenguaje import LlamadaHerramienta, RespuestaModelo


def _entorno(tmp_path, **extra) -> dict:
    return {
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
        "DEEPSEEK_API_KEY": "sk-de-mentira",
        **extra,
    }


class _ModeloQuePideUnaHerramientaProhibida:
    """Pide `pagar` en un turno de catalogo: es el caso que la traza tiene
    que dejar documentado."""

    def __init__(self, comercio_id: str) -> None:
        self._comercio_id = comercio_id

    def generar(self, sistema, instruccion):
        raise AssertionError("las reglas resuelven este mensaje")

    def responder(self, mensajes, herramientas):
        if mensajes[-1].rol == "tool":
            return RespuestaModelo(contenido="Estos son los productos.")
        return RespuestaModelo(
            contenido=None,
            llamadas=(
                LlamadaHerramienta(
                    id="c1", nombre="pagar",
                    argumentos={"mandato_id": "mnd_x", "carrito_id": "car_x"},
                ),
                LlamadaHerramienta(
                    id="c2", nombre="buscar_productos",
                    argumentos={"comercio_id": self._comercio_id},
                ),
            ),
        )


def _un_turno(tmp_path, **extra):
    contenedor = construir(leer_configuracion(_entorno(tmp_path, **extra)))
    comercio = contenedor.catalogo.buscar_comercios()[0]
    contenedor = replace(
        contenedor, modelo_lenguaje=_ModeloQuePideUnaHerramientaProhibida(comercio.comercio_id),
    )
    agente = construir_agente(contenedor)
    assert agente is not None
    agente.turno(agente.iniciar(), f"que productos tiene {comercio.nombre}?")
    return contenedor


def _lineas(ruta) -> list[dict]:
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


# -- donde queda el archivo --------------------------------------------------- #


def test_las_trazas_van_al_lado_de_la_bitacora_por_defecto(tmp_path):
    """Derivarlo de `AGORA_BITACORA` hace que quien ya aisla la bitacora
    aisle las trazas tambien, sin enterarse de que existe otra variable."""
    config = leer_configuracion(_entorno(tmp_path))

    assert config.trazas_path == tmp_path / NOMBRE_DE_TRAZAS


def test_agora_trazas_manda_si_esta(tmp_path):
    otra = tmp_path / "auditoria" / "chat.jsonl"

    config = leer_configuracion(_entorno(tmp_path, AGORA_TRAZAS=str(otra)))

    assert config.trazas_path == otra


def test_las_trazas_no_se_mezclan_con_los_recibos(tmp_path):
    """`recibos.jsonl` es la evidencia del experimento de dinero: no se
    diluye con transcripciones de chat."""
    contenedor = _un_turno(tmp_path)

    assert contenedor.config.trazas_path != contenedor.config.bitacora_path
    assert contenedor.config.trazas_path.exists()
    assert not contenedor.config.bitacora_path.exists()


# -- que quedo escrito -------------------------------------------------------- #


def test_un_turno_deja_una_linea_con_la_cadena_completa(tmp_path):
    contenedor = _un_turno(tmp_path)

    lineas = _lineas(contenedor.config.trazas_path)
    assert len(lineas) == 1
    cuerpo = lineas[0]["cuerpo"]
    assert lineas[0]["evento"] == "turno_del_agente"
    assert lineas[0]["ts"]
    # Los cuatro pasos, en una sola linea.
    assert cuerpo["clasificacion"]["intencion"] == "catalogo"
    assert cuerpo["agente"] == "catalogo"
    assert cuerpo["herramientas_habilitadas"] == [
        "buscar_comercios", "buscar_productos", "ver_producto",
    ]
    assert cuerpo["respuesta"] == "Estos son los productos."


def test_la_linea_documenta_que_pagar_se_rechazo(tmp_path):
    """La evidencia que le contesta a "¿y como se yo que el agente no cobro
    solo?": el modelo lo pidio, el sistema se lo negó, y quedo escrito."""
    contenedor = _un_turno(tmp_path)

    cuerpo = _lineas(contenedor.config.trazas_path)[0]["cuerpo"]
    llamadas = cuerpo["llamadas"]
    pagar = next(l for l in llamadas if l["herramienta"] == "pagar")
    buscar = next(l for l in llamadas if l["herramienta"] == "buscar_productos")

    assert pagar["fuera_de_ruta"] is True
    assert "no esta habilitada" in pagar["error"]
    # Nunca se le ofrecio: la traza deja las dos mitades de la historia.
    assert "pagar" not in cuerpo["herramientas_habilitadas"]
    assert "fuera_de_ruta" not in buscar


def test_cada_linea_es_json_valido_e_independiente(tmp_path):
    """La convencion del repo: append-only, sin buffer, una linea por
    evento -- si el proceso muere, lo escrito sigue siendo valido."""
    contenedor = _un_turno(tmp_path)

    crudo = contenedor.config.trazas_path.read_text(encoding="utf-8")
    assert crudo.endswith("\n")
    for linea in crudo.splitlines():
        json.loads(linea)


# -- el lector ---------------------------------------------------------------- #


class _Args:
    def __init__(self, **kw):
        self.seguir = False
        self.ultimas = 5
        self.crudo = False
        self.__dict__.update(kw)


def test_el_comando_trazas_imprime_el_turno_legible(tmp_path, capsys):
    contenedor = _un_turno(tmp_path)

    assert cmd_trazas(_Args(), contenedor) == 0

    salida = capsys.readouterr().out
    assert "1. DECIDIR" in salida
    assert "intencion=catalogo" in salida
    assert "2. ENRUTAR" in salida
    assert "RECHAZADA (fuera de ruta)" in salida
    assert "Estos son los productos." in salida


def test_el_comando_trazas_en_crudo_devuelve_el_jsonl(tmp_path, capsys):
    contenedor = _un_turno(tmp_path)

    assert cmd_trazas(_Args(crudo=True), contenedor) == 0

    salida = capsys.readouterr().out.strip()
    assert json.loads(salida)["evento"] == "turno_del_agente"


def test_el_comando_trazas_sin_archivo_avisa_y_no_falla(tmp_path, capsys):
    contenedor = construir(leer_configuracion(_entorno(tmp_path)))

    assert cmd_trazas(_Args(), contenedor) == 0
    assert "todavia no hay trazas" in capsys.readouterr().out


def test_el_lector_no_escribe_nada(tmp_path):
    """Quien mira no produce: por eso se puede correr en otra terminal, o
    despues de que todo termino."""
    contenedor = _un_turno(tmp_path)
    antes = contenedor.config.trazas_path.read_bytes()

    cmd_trazas(_Args(), contenedor)

    assert contenedor.config.trazas_path.read_bytes() == antes
