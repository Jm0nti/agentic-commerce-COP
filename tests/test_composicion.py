"""`composicion/`: que arme lo correcto segun la configuracion, y que sea
efectivamente el unico lugar que lee el entorno.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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
