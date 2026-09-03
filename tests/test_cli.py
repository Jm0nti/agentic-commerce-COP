"""`entradas/cli/__main__.py`: no reimplementa `argparse` en la prueba --
llama a las funciones `cmd_*` directo, con un `Contenedor` real (`sqlite`,
para que carritos/mandatos sobrevivan como lo harian entre dos invocaciones
separadas de la CLI) y un `Namespace` armado a mano en vez de parsear texto.
Es lo mas cerca de "correr la CLI de punta a punta" sin lanzar un subproceso
de verdad por cada comando.
"""

from __future__ import annotations

from types import SimpleNamespace

from agora.aplicacion.navegar_catalogo import ItemPedido
from agora.composicion.configuracion import leer_configuracion
from agora.composicion.contenedor import construir
from agora.dominio.pago.modelo import Ambiente
from agora.entradas.cli.__main__ import (
    _parsear_item,
    cmd_comercios,
    cmd_emitir,
    cmd_enrolar,
    cmd_estado,
    cmd_firmar,
    cmd_pagar,
    cmd_retomar,
)


def test_parsear_item_con_y_sin_cantidad():
    assert _parsear_item("prd_1") == _parsear_item("prd_1:1")
    item = _parsear_item("prd_1:3")
    assert item.producto_id == "prd_1"
    assert item.cantidad == 3


def _config(tmp_path) -> dict:
    return {
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "AGORA_LLAVE_FIRMA_SK": str(tmp_path / "firma.sk"),
        "AGORA_LLAVE_FIRMA_PK": str(tmp_path / "firma.pk"),
        "AGORA_PERSISTENCIA": "sqlite",
        "AGORA_SQLITE_PATH": str(tmp_path / "agora.db"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
    }


def _contenedor(tmp_path):
    return construir(leer_configuracion(_config(tmp_path)))


def test_flujo_completo_enrolar_emitir_pagar_retomar(tmp_path, capsys):
    contenedor = _contenedor(tmp_path)

    # El catalogo semilla no es un dato fijo de esta prueba (hallazgo del
    # 1 de septiembre de 2026: dos pruebas quedaron rotas cuando alguien
    # regenero `catalogo.json` con otros ids) -- se descubre el comercio y
    # el producto en el momento, contra lo que `Contenedor` de verdad trae
    # cargado.
    comercio = contenedor.navegar_catalogo.buscar_comercios()[0]
    producto = contenedor.navegar_catalogo.buscar_productos(comercio.comercio_id)[0]

    assert cmd_comercios(SimpleNamespace(buscar=""), contenedor) == 0
    salida = capsys.readouterr().out
    assert comercio.comercio_id in salida

    assert cmd_enrolar(
        SimpleNamespace(
            telefono="3001234567", correo="t@correo.com", titular="tit_1",
            comercio=comercio.comercio_id,
        ),
        contenedor,
    ) == 0
    assert contenedor.medios.vivos("tit_1", Ambiente.SANDBOX)

    assert cmd_emitir(
        SimpleNamespace(
            comercio_id=comercio.comercio_id, titular="tit_1",
            item=[producto.producto_id], justificacion="",
        ),
        contenedor,
    ) == 0
    salida = capsys.readouterr().out
    mandato_id = next(l.split()[1] for l in salida.splitlines() if l.startswith("Mandato"))
    carrito_id = next(l.split()[1] for l in salida.splitlines() if l.strip().startswith("Carrito"))

    assert cmd_pagar(SimpleNamespace(mandato_id=mandato_id, carrito_id=carrito_id), contenedor) == 0
    salida = capsys.readouterr().out
    assert "esperando_confirmacion_humana" in salida
    intencion_id = next(l for l in salida.splitlines() if l.strip().startswith("intencion")).split()[1]

    assert cmd_retomar(
        SimpleNamespace(
            intencion_id=intencion_id, mandato_id=mandato_id, carrito_id=carrito_id, rechazar=False,
        ),
        contenedor,
    ) == 0
    salida = capsys.readouterr().out
    assert "ejecutado    True" in salida

    assert cmd_estado(SimpleNamespace(intencion_id=intencion_id), contenedor) == 0
    assert "aprobado" in capsys.readouterr().out



def test_chat_arma_propuesta_y_titular_la_firma_en_otro_proceso(tmp_path, capsys):
    """Etapa 6, el bug que motivo el cambio: el carrito que arma
    `NavegarCatalogo.armar_carrito` (lo que hace el chat, `composicion/
    agente.py:armar_carrito`) tiene que poder firmarse desde un `Contenedor`
    DISTINTO -- otro proceso, otra terminal, la misma sqlite -- y el
    `carrito_id` que resulta tiene que ser el MISMO que ya tiene quien
    arranco la conversacion. Antes de esta etapa no habia forma de firmar
    una propuesta que no se hubiera armado en el mismo proceso que firma.
    """
    config = _config(tmp_path)

    # Proceso 1: "el chat". Enrola el medio y arma un carrito+propuesta,
    # exactamente como haria `armar_carrito` de `composicion/agente.py` --
    # sin pasar por `emitir`, que es el camino del humano operando la CLI
    # de punta a punta.
    proceso_chat = construir(leer_configuracion(config))
    comercio = proceso_chat.navegar_catalogo.buscar_comercios()[0]
    producto = proceso_chat.navegar_catalogo.buscar_productos(comercio.comercio_id)[0]
    # Multi-comercio: enrolar vincula el medio con ESTE comercio (ver el
    # docstring de aplicacion/enrolar_medio.py) -- se descubre antes de
    # enrolar, no despues.
    proceso_chat.enrolar_medio("3001234567", "titular@correo.com", "tit_1", comercio.comercio_id)
    carrito_chat, propuesta = proceso_chat.navegar_catalogo.armar_carrito(
        comercio.comercio_id, [ItemPedido(producto.producto_id)],
    )

    # Proceso 2: "otra terminal". Un `Contenedor` nuevo, misma sqlite -- lo
    # unico que tiene en comun con el proceso del chat es el archivo.
    proceso_terminal = construir(leer_configuracion(config))
    assert cmd_firmar(
        SimpleNamespace(propuesta_id=propuesta.propuesta_id, titular="tit_1"),
        proceso_terminal,
    ) == 0
    salida = capsys.readouterr().out
    mandato_id = next(l.split()[1] for l in salida.splitlines() if l.startswith("Mandato"))
    carrito_id_impreso = next(
        l.split()[-1] for l in salida.splitlines() if l.strip().startswith("python")
    ).rsplit(" ", 1)[-1]

    # El corazon de la prueba: `firmar` firmo sobre el MISMO carrito que
    # armo el chat, no uno nuevo.
    assert carrito_id_impreso == carrito_chat.carrito_id

    # Y por eso `pagar` (la herramienta del agente, `composicion/
    # agente.py:pagar`) puede usar el `carrito_id` que el chat ya tiene --
    # sin que la persona tenga que pasarle uno distinto -- y no choca contra
    # `carrito_alterado`.
    assert cmd_pagar(
        SimpleNamespace(mandato_id=mandato_id, carrito_id=carrito_chat.carrito_id),
        proceso_terminal,
    ) == 0
    salida = capsys.readouterr().out
    assert "carrito_alterado" not in salida
