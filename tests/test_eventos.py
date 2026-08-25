"""Validacion del checksum de los eventos de Wompi.

El evento de abajo es real: el cobro de 2.000 COP del 19 de agosto de 2026 que
el motor antifraude declino. Se conserva tal cual porque es el unico ejemplar
verificado de la forma del evento en produccion, incluido el `afe_decision` que
no aparece en ninguna documentacion publica.

El checksum original no se puede reproducir aqui: haria falta el secreto de
eventos, que no vive en el repo. Lo que si se prueba es que el calculo respeta
el orden que Wompi especifica -- valores de `signature.properties`, luego el
timestamp, luego el secreto -- y que una firma alterada no pasa.
"""

from __future__ import annotations

import hashlib

import pytest

from boveda.eventos import checksum_esperado, validar

# Capturado del dashboard de Wompi. environment: prod.
EVENTO_REAL = {
    "data": {
        "transaction": {
            "id": "1509872-1787154512-67009",
            "origin": None,
            "status": "DECLINED",
            "currency": "COP",
            "reference": "bov-e5407c7d743649",
            "created_at": "2026-08-19T15:48:33.012Z",
            "billing_data": None,
            "finalized_at": "2026-08-19T15:48:33.000Z",
            "redirect_url": None,
            "customer_data": None,
            "customer_email": "boveda+poc@example.com",
            "payment_method": {
                "type": "NEQUI",
                "extra": {"is_three_ds": False, "three_ds_auth_type": None},
                "afe_decision": "DECLINE",
                "phone_number": "3232014944",
            },
            "status_message": (
                "Por motivos de seguridad no pudimos procesar tu pago. Te "
                "recomendamos intentar con otro metodo o contactar a tu comercio "
                "si el problema persiste."
            ),
            "amount_in_cents": 200000,
            "payment_link_id": None,
            "shipping_address": None,
            "payment_source_id": 22620436,
            "payment_method_type": "NEQUI",
        }
    },
    "event": "transaction.updated",
    "sent_at": "2026-08-19T15:50:39.188Z",
    "signature": {
        "checksum": "2fab1c21082322f1e06f10ec29248e05fd16ae775a71d2143e5b853f65fa8783",
        "properties": [
            "transaction.id",
            "transaction.status",
            "transaction.amount_in_cents",
        ],
    },
    "timestamp": 1787154639,
    "environment": "prod",
}

SECRETO = "secreto_de_pruebas"


def _con_checksum(evento: dict, secreto: str = SECRETO) -> dict:
    e = {**evento, "signature": {**evento["signature"]}}
    e["signature"]["checksum"] = checksum_esperado(e, secreto)
    return e


def test_el_orden_de_concatenacion_es_el_que_wompi_especifica():
    """valores de properties, luego timestamp, luego secreto."""
    a_mano = hashlib.sha256(
        ("1509872-1787154512-67009" + "DECLINED" + "200000" + "1787154639" + SECRETO).encode()
    ).hexdigest()
    assert checksum_esperado(EVENTO_REAL, SECRETO) == a_mano


def test_evento_bien_firmado_pasa():
    ok, motivo = validar(_con_checksum(EVENTO_REAL), SECRETO)
    assert ok, motivo


def test_secreto_equivocado_no_pasa():
    ok, motivo = validar(_con_checksum(EVENTO_REAL), "otro_secreto")
    assert not ok
    assert "no coincide" in motivo


def test_monto_alterado_no_pasa():
    """El ataque util: cambiar el monto o el estado despues de firmar."""
    e = _con_checksum(EVENTO_REAL)
    e["data"]["transaction"]["amount_in_cents"] = 1
    ok, _ = validar(e, SECRETO)
    assert not ok
    e["data"]["transaction"]["amount_in_cents"] = 200000  # dejarlo como estaba


def test_estado_alterado_no_pasa():
    """Un APPROVED falso es lo que haria creer a la boveda que cobro."""
    e = _con_checksum(EVENTO_REAL)
    e["data"]["transaction"]["status"] = "APPROVED"
    ok, _ = validar(e, SECRETO)
    assert not ok
    e["data"]["transaction"]["status"] = "DECLINED"


def test_evento_sin_checksum_no_pasa():
    e = {**EVENTO_REAL, "signature": {"properties": ["transaction.id"]}}
    ok, motivo = validar(e, SECRETO)
    assert not ok
    assert "no trae checksum" in motivo


def test_properties_se_leen_del_evento_no_del_codigo():
    """Wompi advierte que la lista puede cambiar entre eventos."""
    e = {**EVENTO_REAL, "signature": {**EVENTO_REAL["signature"]}}
    e["signature"]["properties"] = ["transaction.reference", "transaction.status"]
    esperado = hashlib.sha256(
        ("bov-e5407c7d743649" + "DECLINED" + "1787154639" + SECRETO).encode()
    ).hexdigest()
    assert checksum_esperado(e, SECRETO) == esperado


def test_propiedad_inexistente_no_produce_checksum():
    e = {**EVENTO_REAL, "signature": {**EVENTO_REAL["signature"]}}
    e["signature"]["properties"] = ["transaction.no_existe"]
    assert checksum_esperado(e, SECRETO) is None


@pytest.mark.parametrize("faltante", ["signature", "timestamp", "data"])
def test_evento_incompleto_no_produce_checksum(faltante):
    e = {k: v for k, v in EVENTO_REAL.items() if k != faltante}
    assert checksum_esperado(e, SECRETO) is None
