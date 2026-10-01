"""`composicion/agente.py`: que las "nota" que ven la persona y el modelo
traigan el comando EXACTO a correr (etapa 6), y que el estado de una
intencion resuelta con `retomar` en OTRO proceso (`Contenedor` separado, la
misma sqlite) se vea desde `consultar_estado` en el proceso original -- el
bug que motivo agregar `RegistroDeEstadosSQLite`.

Construye el `Agente` con un `modelo_lenguaje` de mentira (`object()`): las
pruebas de aca abajo llaman directo a `agente._herramientas[...].ejecutar`,
nunca a `agente.turno`, asi que el modelo real nunca se toca.
"""

from __future__ import annotations

from dataclasses import replace

from agora.composicion.agente import construir_agente
from agora.composicion.configuracion import leer_configuracion
from agora.composicion.contenedor import construir
from agora.model.mandato.modelo import Intencion


def _producto_barato(contenedor):
    """Cualquier producto EN_STOCK por 20.000 COP o menos -- tiene que caber
    bajo `TopesDuros.por_transaccion` para que `pagar()` llegue hasta la
    politica blanda (`esperando_confirmacion_humana`) en vez de rechazarse
    de una por el tope duro. Mismo criterio que `tests/test_composicion.py`.
    """
    from agora.model.catalogo.modelo import Disponibilidad

    for comercio in contenedor.navegar_catalogo.buscar_comercios():
        for producto in contenedor.navegar_catalogo.buscar_productos(comercio.comercio_id):
            if producto.disponibilidad is Disponibilidad.EN_STOCK and producto.precio.pesos <= 20_000:
                return comercio.comercio_id, producto.producto_id
    raise AssertionError("el catalogo no tiene ningun producto <= 20.000 COP")


def _contenedor_con_agente(tmp_path):
    config = leer_configuracion({
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "AGORA_PERSISTENCIA": "sqlite",
        "AGORA_SQLITE_PATH": str(tmp_path / "agora.db"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
    })
    contenedor = construir(config)
    # Multi-usuario: "tit_1" necesita un usuario (y su llave) creado de
    # antemano para que `emitir_mandato` pueda resolverle un Firmante --
    # igual que exigiria `scripts/crear_usuario.py` en produccion.
    contenedor.registrar_usuario("tit_1", "clave-de-prueba", titular_id="tit_1")
    # Multi-comercio: enrolar vincula el medio con ESTE comercio (ver el
    # docstring de aplicacion/enrolar_medio.py) -- el comercio se descubre
    # antes de enrolar, no despues, para que quede vinculado con el mismo
    # comercio que usan las pruebas de aca abajo.
    comercio_id, producto_id = _producto_barato(contenedor)
    contenedor.enrolar_medio("3001234567", "titular@correo.com", "tit_1", comercio_id)
    # `construir_agente` solo mira si `modelo_lenguaje` es `None` -- con
    # cualquier otra cosa arma el Agente de verdad, con las herramientas de
    # verdad. Las pruebas de aca abajo nunca llaman a `agente.turno`
    # (lo unico que de verdad hablaria con un modelo), asi que un stub
    # alcanza.
    contenedor = replace(contenedor, modelo_lenguaje=object())
    agente = construir_agente(contenedor)
    assert agente is not None
    return contenedor, agente, comercio_id, producto_id


def test_armar_carrito_le_pasa_a_la_persona_el_comando_firmar_exacto(tmp_path):
    contenedor, agente, comercio_id, producto_id = _contenedor_con_agente(tmp_path)

    resultado = agente._herramientas["armar_carrito"].ejecutar(
        comercio_id=comercio_id, items=[{"producto_id": producto_id, "cantidad": 1}],
    )

    propuesta_id = resultado["propuesta"]["propuesta_id"]
    assert f"firmar {propuesta_id}" in resultado["nota"]
    # La propuesta tiene que poder encontrarse de verdad -- si no, el
    # comando que se le paso a la persona no serviria de nada.
    assert contenedor.propuestas.obtener(propuesta_id).propuesta_id == propuesta_id


def test_pagar_le_pasa_a_la_persona_el_comando_retomar_exacto_si_queda_esperando(tmp_path):
    contenedor, agente, comercio_id, producto_id = _contenedor_con_agente(tmp_path)

    armado = agente._herramientas["armar_carrito"].ejecutar(
        comercio_id=comercio_id, items=[{"producto_id": producto_id, "cantidad": 1}],
    )
    propuesta_id = armado["propuesta"]["propuesta_id"]
    carrito_id = armado["carrito_id"]
    mandato = contenedor.emitir_mandato(propuesta_id, "tit_1")

    resultado = agente._herramientas["pagar"].ejecutar(
        mandato_id=mandato.mandato_id, carrito_id=carrito_id,
    )

    # `EmitirMandatoUseCase` corta el mandato exacto al carrito -- dispara casi
    # siempre las senales blandas (ver docs/etapa-5-agente-y-cli.md).
    assert resultado["esperando_confirmacion"] is True
    intencion_id = resultado["intencion_id"]
    esperado = f"retomar {intencion_id} {mandato.mandato_id} {carrito_id}"
    assert esperado in resultado["nota"]


def test_estado_confirmado_en_otro_proceso_se_ve_desde_consultar_estado(tmp_path):
    """El corazon de esta etapa: `retomar` corre en un `Contenedor`
    SEPARADO (misma sqlite) -- nunca en el que tiene el chat -- y aun asi
    `consultar_estado` del chat original tiene que ver el resultado."""
    contenedor, agente, comercio_id, producto_id = _contenedor_con_agente(tmp_path)

    armado = agente._herramientas["armar_carrito"].ejecutar(
        comercio_id=comercio_id, items=[{"producto_id": producto_id, "cantidad": 1}],
    )
    carrito_id = armado["carrito_id"]
    mandato = contenedor.emitir_mandato(armado["propuesta"]["propuesta_id"], "tit_1")

    pagado = agente._herramientas["pagar"].ejecutar(
        mandato_id=mandato.mandato_id, carrito_id=carrito_id,
    )
    intencion_id = pagado["intencion_id"]
    assert pagado["esperando_confirmacion"] is True

    estado_antes = agente._herramientas["consultar_estado"].ejecutar(intencion_id=intencion_id)
    assert estado_antes["estado"] == "esperando_confirmacion"

    # "Otra terminal": un Contenedor nuevo, misma sqlite -- ni el proceso ni
    # el objeto Python tienen nada en comun con el del chat.
    config_repetida = leer_configuracion({
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "AGORA_PERSISTENCIA": "sqlite",
        "AGORA_SQLITE_PATH": str(tmp_path / "agora.db"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
    })
    proceso_terminal = construir(config_repetida)
    carrito = proceso_terminal.carritos.obtener(carrito_id)
    intencion = Intencion(
        intencion_id=intencion_id, mandato_id=mandato.mandato_id,
        comercio_id=carrito.comercio_id, carrito_id=carrito_id, monto=carrito.total,
    )
    recibo = proceso_terminal.ejecutar_intencion.retomar(
        intencion, aprueba=True, carrito_hash=carrito.hash_canonico,
    )
    assert recibo.ejecutado

    estado_despues = agente._herramientas["consultar_estado"].ejecutar(intencion_id=intencion_id)
    assert estado_despues["estado"] == "aprobado"
