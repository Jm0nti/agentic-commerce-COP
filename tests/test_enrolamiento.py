"""Fase A contra una Wompi de mentiras.

No se puede probar el enrolamiento real sin un telefono y una persona. Lo que
si se puede probar es todo lo demas: que el sondeo termina, que un token
rechazado no produce fuente, que una fuente de produccion no se puede revocar
desde sandbox, y que el registro nunca cruza modos.

Ese ultimo es el que importa. Un `payment_source_id` es un entero, y el mismo
entero existe en los dos ambientes apuntando a cuentas distintas.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from boveda.enrolamiento import (
    Fuente,
    RegistroFuentes,
    enrolar_nequi,
    preflight,
    revocar,
)
from boveda.nucleo import BovedaError, ClienteWompi

COMERCIO = {
    "data": {
        "name": "Tienda Demo",
        "legal_name": "Demo SAS",
        "accepted_payment_methods": ["CARD", "NEQUI", "PSE"],
        "presigned_acceptance": {
            "acceptance_token": "tok_terminos",
            "permalink": "https://wompi.co/terminos",
        },
        "presigned_personal_data_auth": {
            "acceptance_token": "tok_datos",
            "permalink": "https://wompi.co/datos",
        },
    }
}


def _wompi(secuencia_token: list[str], falla_fuente: bool = False):
    """Devuelve un transporte que imita a Wompi. `secuencia_token` son los
    estados que va devolviendo el sondeo, en orden."""
    pendientes = list(secuencia_token)

    def responder(request: httpx.Request) -> httpx.Response:
        ruta = request.url.path
        if ruta.startswith("/v1/merchants/"):
            return httpx.Response(200, json=COMERCIO)
        if ruta == "/v1/tokens/nequi" and request.method == "POST":
            return httpx.Response(
                200, json={"data": {"id": "nequi_test_abc123", "status": "PENDING"}}
            )
        if ruta.startswith("/v1/tokens/nequi/"):
            estado = pendientes.pop(0) if pendientes else "PENDING"
            return httpx.Response(200, json={"data": {"status": estado}})
        if ruta == "/v1/payment_sources" and request.method == "POST":
            if falla_fuente:
                return httpx.Response(422, json={"error": {"type": "INPUT_VALIDATION"}})
            return httpx.Response(
                201, json={"data": {"id": 3891, "type": "NEQUI", "status": "AVAILABLE"}}
            )
        if ruta.endswith("/void") and request.method == "PUT":
            return httpx.Response(200, json={"data": {"id": 3891, "status": "VOIDED"}})
        return httpx.Response(404, json={"error": "ruta no simulada"})

    return httpx.MockTransport(responder)


@pytest.fixture
def entorno(monkeypatch):
    monkeypatch.setenv("WOMPI_PUBLIC_KEY", "pub_test_xxx")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_test_xxx")
    monkeypatch.setenv("WOMPI_INTEGRITY_SECRET", "test_integrity_xxx")


def _cliente(secuencia, falla_fuente=False) -> ClienteWompi:
    c = ClienteWompi("sandbox")
    c.http = httpx.Client(transport=_wompi(secuencia, falla_fuente), timeout=5)
    return c


# --------------------------------------------------------------------------- #


def test_preflight_reporta_nequi_habilitado(entorno):
    info = preflight(_cliente([]))
    assert info["nequi_habilitado"] is True
    assert info["permalink_terminos"] == "https://wompi.co/terminos"


def test_enrolamiento_feliz(entorno, tmp_path, monkeypatch):
    monkeypatch.setattr("boveda.enrolamiento.PAUSA_SONDEO_SEG", 0.0)
    reg = RegistroFuentes(tmp_path / "fuentes.json")
    f = enrolar_nequi(
        _cliente(["PENDING", "APPROVED"]),
        telefono="3001234567",
        email="a@b.co",
        registro=reg,
    )
    assert f.payment_source_id == 3891
    assert f.estado == "AVAILABLE"
    assert f.referencia_publica == "300****567"  # el telefono no queda en claro
    assert reg.pertenece("sandbox", 3891)


def test_token_rechazado_no_crea_fuente(entorno, tmp_path, monkeypatch):
    monkeypatch.setattr("boveda.enrolamiento.PAUSA_SONDEO_SEG", 0.0)
    reg = RegistroFuentes(tmp_path / "fuentes.json")
    with pytest.raises(BovedaError, match="DECLINED"):
        enrolar_nequi(
            _cliente(["DECLINED"]), telefono="3001234567", email="a@b.co", registro=reg
        )
    assert reg.listar("sandbox") == []


def test_sin_aceptar_el_push_no_hay_fuente(entorno, tmp_path, monkeypatch):
    """El caso realista: el titular no vio la notificacion."""
    monkeypatch.setattr("boveda.enrolamiento.PAUSA_SONDEO_SEG", 0.0)
    reg = RegistroFuentes(tmp_path / "fuentes.json")
    with pytest.raises(BovedaError, match="PENDING"):
        enrolar_nequi(
            _cliente(["PENDING"] * 5),
            telefono="3001234567",
            email="a@b.co",
            registro=reg,
            espera_seg=0,
        )
    assert reg.listar("sandbox") == []


def test_telefono_invalido_no_llega_a_la_red(entorno, tmp_path):
    reg = RegistroFuentes(tmp_path / "fuentes.json")
    for malo in ("+573001234567", "300123456", "abcdefghij", ""):
        with pytest.raises(BovedaError, match="celular colombiano"):
            enrolar_nequi(
                _cliente([]), telefono=malo, email="a@b.co", registro=reg
            )


def test_revocar_exige_que_la_fuente_sea_de_este_modo(entorno, tmp_path):
    """El control que evita apagar la cuenta equivocada."""
    reg = RegistroFuentes(tmp_path / "fuentes.json")
    reg.agregar(
        Fuente(
            payment_source_id=3891,
            tipo="NEQUI",
            modo="produccion",  # registrada en produccion
            referencia_publica="300****567",
            email="a@b.co",
            estado="AVAILABLE",
            creada_en="2026-08-18T00:00:00+00:00",
        )
    )
    # el cliente es de sandbox: la fuente no le pertenece
    with pytest.raises(BovedaError, match="no esta registrada en modo"):
        revocar(_cliente([]), 3891, reg)


def test_revocar_marca_el_registro(entorno, tmp_path):
    reg = RegistroFuentes(tmp_path / "fuentes.json")
    reg.agregar(
        Fuente(
            payment_source_id=3891,
            tipo="NEQUI",
            modo="sandbox",
            referencia_publica="300****567",
            email="a@b.co",
            estado="AVAILABLE",
            creada_en="2026-08-18T00:00:00+00:00",
        )
    )
    assert revocar(_cliente([]), 3891, reg) == "VOIDED"
    assert reg.listar("sandbox")[0]["estado"] == "VOIDED"


def test_el_registro_no_cruza_modos(tmp_path):
    """Dos fuentes con el mismo id, una por ambiente. No se pisan."""
    reg = RegistroFuentes(tmp_path / "fuentes.json")
    for modo in ("sandbox", "produccion"):
        reg.agregar(
            Fuente(
                payment_source_id=3891,
                tipo="NEQUI",
                modo=modo,
                referencia_publica="300****567",
                email="a@b.co",
                estado="AVAILABLE",
                creada_en="2026-08-18T00:00:00+00:00",
            )
        )
    assert len(reg.listar("sandbox")) == 1
    assert len(reg.listar("produccion")) == 1
    reg.marcar("sandbox", 3891, "VOIDED")
    assert reg.listar("sandbox")[0]["estado"] == "VOIDED"
    assert reg.listar("produccion")[0]["estado"] == "AVAILABLE"


def test_modo_y_llave_tienen_que_coincidir(monkeypatch):
    """Una llave de produccion con modo sandbox cobraria de verdad contra un
    endpoint que el codigo cree de mentiras."""
    monkeypatch.setenv("WOMPI_PUBLIC_KEY", "pub_prod_xxx")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_prod_xxx")
    monkeypatch.setenv("WOMPI_INTEGRITY_SECRET", "prod_integrity_xxx")
    with pytest.raises(BovedaError, match="exige una llave pub_test_"):
        ClienteWompi("sandbox")


def test_fuente_que_wompi_rechaza_no_queda_registrada(entorno, tmp_path, monkeypatch):
    monkeypatch.setattr("boveda.enrolamiento.PAUSA_SONDEO_SEG", 0.0)
    reg = RegistroFuentes(tmp_path / "fuentes.json")
    with pytest.raises(BovedaError, match="422"):
        enrolar_nequi(
            _cliente(["APPROVED"], falla_fuente=True),
            telefono="3001234567",
            email="a@b.co",
            registro=reg,
        )
    assert reg.listar("sandbox") == []
