"""`composicion/`: que arme lo correcto segun la configuracion, y que sea
efectivamente el unico lugar que lee el entorno.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agora.aplicacion.navegar_catalogo import ItemPedido
from agora.composicion.configuracion import (
    CORREO_POR_DEFECTO,
    ConfiguracionInvalida,
    leer_configuracion,
)
from agora.composicion.contenedor import construir
from agora.dominio.comun.dinero import Dinero
from agora.dominio.mandato.modelo import Intencion, Mandato
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor


def test_configuracion_por_defecto_es_sandbox_y_simulada():
    config = leer_configuracion({})
    assert config.ambiente is Ambiente.SANDBOX
    assert config.pasarela == "simulada"
    assert config.correo_pagador == CORREO_POR_DEFECTO


def test_pasarela_wompi_sin_credenciales_es_invalida():
    with pytest.raises(ConfiguracionInvalida):
        leer_configuracion({"AGORA_PASARELA": "wompi"})


def test_pasarela_wompi_con_credenciales_arma_configuracion_wompi():
    config = leer_configuracion({
        "AGORA_PASARELA": "wompi",
        "AGORA_AMBIENTE": "sandbox",
        "WOMPI_PUBLIC_KEY": "pub_test_x",
        "WOMPI_PRIVATE_KEY": "prv_test_x",
        "WOMPI_INTEGRITY_SECRET": "s",
    })
    assert config.wompi is not None
    assert config.wompi.llave_publica == "pub_test_x"


def test_perfil_del_pagador_omite_tipo_de_documento_sin_documento():
    """Igual que `boveda/nucleo.py:perfil_pagador`: `legal_id_type` solo
    tiene sentido acompanado del documento."""
    config = leer_configuracion({"PAGADOR_NOMBRE": "Juan"})
    assert "legal_id_type" not in config.datos_pagador
    assert config.datos_pagador["full_name"] == "Juan"


def test_persistencia_por_defecto_es_memoria():
    config = leer_configuracion({})
    assert config.persistencia == "memoria"


def test_persistencia_invalida_es_invalida():
    with pytest.raises(ConfiguracionInvalida):
        leer_configuracion({"AGORA_PERSISTENCIA": "redis"})


def test_wompi_en_produccion_con_persistencia_en_memoria_es_invalida():
    """El guardarrail de la etapa 3: `LibroDeConsumoEnMemoria` pierde el
    consumo acumulado si el proceso reinicia, y contra dinero real
    (wompi + produccion) eso permitiria reusar un mandato agotado."""
    with pytest.raises(ConfiguracionInvalida, match="AGORA_PERSISTENCIA=sqlite"):
        leer_configuracion({
            "AGORA_PASARELA": "wompi",
            "AGORA_AMBIENTE": "produccion",
            "AGORA_PERSISTENCIA": "memoria",
            "WOMPI_PUBLIC_KEY": "pub_prod_x",
            "WOMPI_PRIVATE_KEY": "prv_prod_x",
            "WOMPI_INTEGRITY_SECRET": "s",
        })


def test_wompi_en_produccion_con_sqlite_es_valida():
    config = leer_configuracion({
        "AGORA_PASARELA": "wompi",
        "AGORA_AMBIENTE": "produccion",
        "AGORA_PERSISTENCIA": "sqlite",
        "WOMPI_PUBLIC_KEY": "pub_prod_x",
        "WOMPI_PRIVATE_KEY": "prv_prod_x",
        "WOMPI_INTEGRITY_SECRET": "s",
    })
    assert config.persistencia == "sqlite"


def test_wompi_en_sandbox_con_persistencia_en_memoria_sigue_siendo_valida():
    """El guardarrail es especifico de produccion: en sandbox, memoria sigue
    siendo una eleccion legitima (pruebas, demos)."""
    config = leer_configuracion({
        "AGORA_PASARELA": "wompi",
        "AGORA_AMBIENTE": "sandbox",
        "WOMPI_PUBLIC_KEY": "pub_test_x",
        "WOMPI_PRIVATE_KEY": "prv_test_x",
        "WOMPI_INTEGRITY_SECRET": "s",
    })
    assert config.persistencia == "memoria"


def test_construir_con_sqlite_ejecuta_una_intencion_de_punta_a_punta_y_persiste(tmp_path):
    """Igual que la prueba con `simulada` + memoria de mas abajo, pero con
    `persistencia=sqlite`: ademas de ejecutar, el mandato y el consumo tienen
    que sobrevivir a una reconexion -- eso es lo nuevo en la etapa 3."""
    config = leer_configuracion({
        "AGORA_PASARELA": "simulada",
        "AGORA_AMBIENTE": "sandbox",
        "AGORA_PERSISTENCIA": "sqlite",
        "AGORA_SQLITE_PATH": str(tmp_path / "agora.db"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
    })
    contenedor = construir(config)

    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    ahora = contenedor.reloj.ahora()
    mandato = Mandato(
        mandato_id="mnd_1", titular_id="tit_1",
        medio=MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_1"),
        comercio_id="com_x",
        monto_max=Dinero.de_pesos(20_000), tope_total=Dinero.de_pesos(20_000),
        usos_max=5, expira_en=ahora + timedelta(hours=1), creado_en=ahora,
        llave_publica=pub,
    )
    mandato = replace(mandato, firma=sk.sign(mandato.canonico()))
    contenedor.mandatos.guardar(mandato, Ambiente.SANDBOX)

    intencion = Intencion(
        intencion_id="int_1", mandato_id="mnd_1", comercio_id="com_x",
        carrito_id="car_1", monto=Dinero.de_pesos(2_050),
    )
    recibo = contenedor.ejecutar_intencion(intencion)
    assert recibo.ejecutado

    # Lo que la memoria no puede ofrecer: un contenedor NUEVO, apuntando al
    # mismo archivo, ve el mandato y el consumo que dejo el anterior.
    otro_contenedor = construir(config)
    assert otro_contenedor.mandatos.obtener("mnd_1", Ambiente.SANDBOX) == mandato
    assert otro_contenedor.consumo.consumo_de("mnd_1").usos == 1


def test_construir_con_simulada_ejecuta_una_intencion_de_punta_a_punta(tmp_path):
    config = leer_configuracion({
        "AGORA_PASARELA": "simulada",
        "AGORA_AMBIENTE": "sandbox",
        "PAGADOR_EMAIL": "juan@correo-real.com",
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
    })
    contenedor = construir(config)

    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    ahora = contenedor.reloj.ahora()
    mandato = Mandato(
        mandato_id="mnd_1", titular_id="tit_1",
        medio=MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_1"),
        comercio_id="com_x",
        monto_max=Dinero.de_pesos(20_000), tope_total=Dinero.de_pesos(20_000),
        usos_max=5, expira_en=ahora + timedelta(hours=1), creado_en=ahora,
        llave_publica=pub,
    )
    mandato = replace(mandato, firma=sk.sign(mandato.canonico()))
    contenedor.mandatos.guardar(mandato, Ambiente.SANDBOX)

    intencion = Intencion(
        intencion_id="int_1", mandato_id="mnd_1", comercio_id="com_x",
        carrito_id="car_1", monto=Dinero.de_pesos(2_050),
    )
    recibo = contenedor.ejecutar_intencion(intencion)

    assert recibo.ejecutado
    # La bitacora escribio de verdad al archivo configurado.
    assert (tmp_path / "recibos.jsonl").exists()
    contenido = (tmp_path / "recibos.jsonl").read_text(encoding="utf-8")
    assert "int_1" in contenido


def test_construir_arma_el_catalogo_sin_depender_de_la_pasarela_ni_la_persistencia():
    """`contenedor.catalogo` (etapa 5) lee `datos/catalogo.json` sin red y sin
    tocar `config.pasarela`/`config.persistencia` -- se arma igual sin
    importar el resto de la configuracion."""
    contenedor = construir(leer_configuracion({}))
    assert contenedor.catalogo.buscar_comercios() != []


def test_construir_encadena_navegar_emitir_pagar_y_consultar_de_punta_a_punta(tmp_path):
    """El flujo completo de la etapa 5, con las piezas que arma `Contenedor`
    de verdad (sin wiring manual): enrolar -> armar_carrito -> firmar ->
    pagar -> consultar_estado. Usa el catalogo placeholder que se entrega
    con el repo (`docs/catalogo-simulado-deepseek.md`)."""
    config = leer_configuracion({
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "AGORA_LLAVE_FIRMA_SK": str(tmp_path / "firma.sk"),
        "AGORA_LLAVE_FIRMA_PK": str(tmp_path / "firma.pk"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
    })
    contenedor = construir(config)

    ref = contenedor.enrolar_medio("3001234567", "titular@correo.com", "tit_1")
    assert contenedor.medios.vivos("tit_1", Ambiente.SANDBOX) == [ref]

    # La libreta (12.000 COP) y no los audifonos (120.000 COP): tiene que
    # caber bajo el tope duro por transaccion (20.000 COP, `TopesDuros`) para
    # que esta prueba llegue hasta `aprobado` sin toparselo.
    carrito, propuesta = contenedor.navegar_catalogo.armar_carrito(
        "com_placeholder_librosur", [ItemPedido("prd_placeholder_libreta")],
    )
    mandato = contenedor.emitir_mandato(propuesta.propuesta_id, "tit_1")
    assert mandato.medio == ref
    assert mandato.carrito_hash == carrito.hash_canonico

    intencion = Intencion(
        intencion_id=contenedor.ids.nuevo("int"), mandato_id=mandato.mandato_id,
        comercio_id=carrito.comercio_id, carrito_id=carrito.carrito_id, monto=carrito.total,
    )
    recibo = contenedor.ejecutar_intencion(intencion, carrito_hash=carrito.hash_canonico)
    # `EmitirMandato` corta el mandato exacto al carrito (monto_max ==
    # carrito.total, usos_max=1): eso siempre dispara las senales blandas de
    # `dominio/mandato/politica.py` ("agota el mandato de una sola vez", "es
    # el ultimo uso") y deja la intencion en `CONFIRMAR`, no en `PERMITIR`.
    # No es un fallo de esta prueba -- es la consecuencia esperada de firmar
    # un mandato tan angosto, y `retomar()` es como un humano lo resuelve.
    assert recibo.esperando_confirmacion
    recibo = contenedor.ejecutar_intencion.retomar(
        intencion, aprueba=True, carrito_hash=carrito.hash_canonico,
    )
    assert recibo.ejecutado

    estado = contenedor.consultar_estado(intencion.intencion_id)
    assert estado.estado == "aprobado"
