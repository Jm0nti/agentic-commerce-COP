"""`AdaptadorWompi`, contra una Wompi simulada con `httpx.MockTransport`.

Misma tecnica que `tests/test_modos.py` y `tests/test_eventos.py` en la v1: no
hay red real en las pruebas, pero el `ClienteWompi` que corre es el de
verdad, solo con el transporte HTTP sustituido.
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from agora.adaptadores.pasarelas.wompi import AdaptadorWompi, ConfiguracionWompi
from agora.adaptadores.pasarelas.wompi.cliente import ClienteWompi
from agora.adaptadores.pasarelas.wompi.config import ConfiguracionInvalida
from agora.dominio.comun.dinero import Dinero
from agora.dominio.comun.errores import ErrorDePasarela, PasarelaNoDisponible
from agora.dominio.pago.modelo import Ambiente, EstadoCobro, MedioDePagoRef, OrdenDeCobro, Proveedor
from agora.puertos.pasarela import SolicitudEnrolamiento

ACEPTACIONES = {
    "data": {
        "presigned_acceptance": {"acceptance_token": "acc"},
        "presigned_personal_data_auth": {"acceptance_token": "per"},
    }
}


def _config(ambiente=Ambiente.SANDBOX) -> ConfiguracionWompi:
    pref = "test" if ambiente is Ambiente.SANDBOX else "prod"
    return ConfiguracionWompi(
        ambiente=ambiente,
        llave_publica=f"pub_{pref}_x",
        llave_privada=f"prv_{pref}_x",
        secreto_integridad="secreto_int",
        secreto_eventos="secreto_evt",
    )


def _adaptador(responder) -> AdaptadorWompi:
    cliente = ClienteWompi(_config(), httpx.Client(transport=httpx.MockTransport(responder), timeout=5))
    return AdaptadorWompi(_config(), cliente)


def _orden(monto_pesos: int = 15_000, correo: str = "juan@correo-real.com") -> OrdenDeCobro:
    return OrdenDeCobro(
        intencion_id="int_1",
        medio=MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22620436"),
        monto=Dinero.de_pesos(monto_pesos),
        glosa="compra",
        correo_pagador=correo,
    )


# --------------------------------------------------------------------------- #
# Configuracion
# --------------------------------------------------------------------------- #


def test_configuracion_exige_las_tres_credenciales():
    with pytest.raises(ConfiguracionInvalida, match="faltan"):
        ConfiguracionWompi(
            ambiente=Ambiente.SANDBOX, llave_publica="pub_test_x",
            llave_privada="", secreto_integridad="s",
        )


def test_configuracion_exige_que_el_prefijo_coincida_con_el_ambiente():
    """El bug que esto evita: una llave de produccion con ambiente sandbox no
    falla sola, cobra de verdad contra un endpoint que el codigo cree de
    mentiras (`nucleo.py:131-139`)."""
    with pytest.raises(ConfiguracionInvalida, match="pub_test_"):
        ConfiguracionWompi(
            ambiente=Ambiente.SANDBOX, llave_publica="pub_prod_x",
            llave_privada="prv_test_x", secreto_integridad="s",
        )


# --------------------------------------------------------------------------- #
# Cobro
# --------------------------------------------------------------------------- #


def test_cobrar_aprobado():
    def responder(req: httpx.Request) -> httpx.Response:
        if "/merchants/" in req.url.path:
            return httpx.Response(200, json=ACEPTACIONES)
        if req.url.path.endswith("/transactions") and req.method == "POST":
            return httpx.Response(
                201, json={"data": {"id": "tx1", "status": "APPROVED",
                                     "status_message": "Aprobada",
                                     "payment_method": {"afe_decision": "ACCEPT"}}},
            )
        return httpx.Response(404, json={})

    r = _adaptador(responder).cobrar(_orden())
    assert r.estado is EstadoCobro.APROBADO
    assert r.id_externo == "tx1"
    assert r.afe_decision == "ACCEPT"


def test_cobrar_declinado_por_antifraude():
    """Reproduce la forma exacta de la corrida real (`docs/decline-afe.md`):
    `status: DECLINED` con `payment_method.afe_decision: DECLINE`."""

    def responder(req: httpx.Request) -> httpx.Response:
        if "/merchants/" in req.url.path:
            return httpx.Response(200, json=ACEPTACIONES)
        if req.url.path.endswith("/transactions") and req.method == "POST":
            return httpx.Response(
                201,
                json={"data": {
                    "id": "tx2", "status": "DECLINED",
                    "status_message": "Por motivos de seguridad no pudimos procesar tu pago",
                    "payment_method": {"afe_decision": "DECLINE"},
                }},
            )
        return httpx.Response(404, json={})

    r = _adaptador(responder).cobrar(_orden(monto_pesos=2_000))
    assert r.estado is EstadoCobro.RECHAZADO
    assert r.detenido_por_antifraude


def test_referencia_se_deriva_de_la_intencion():
    """ADR-6: reintentar no puede duplicar un cobro porque la referencia no
    cambia entre intentos."""
    vista: dict = {}

    def responder(req: httpx.Request) -> httpx.Response:
        if "/merchants/" in req.url.path:
            return httpx.Response(200, json=ACEPTACIONES)
        if req.url.path.endswith("/transactions") and req.method == "POST":
            vista["cuerpo"] = json.loads(req.content)
            return httpx.Response(201, json={"data": {"id": "tx1", "status": "PENDING"}})
        return httpx.Response(404, json={})

    _adaptador(responder).cobrar(_orden())
    assert vista["cuerpo"]["reference"] == "agora-int_1"


def test_firma_de_integridad_usa_el_secreto_de_la_config():
    vista: dict = {}

    def responder(req: httpx.Request) -> httpx.Response:
        if "/merchants/" in req.url.path:
            return httpx.Response(200, json=ACEPTACIONES)
        if req.url.path.endswith("/transactions") and req.method == "POST":
            vista["cuerpo"] = json.loads(req.content)
            return httpx.Response(201, json={"data": {"id": "tx1", "status": "PENDING"}})
        return httpx.Response(404, json={})

    _adaptador(responder).cobrar(_orden(monto_pesos=15_000))
    centavos = 15_000 * 100
    esperada = hashlib.sha256(
        f"agora-int_1{centavos}COPsecreto_int".encode("utf-8")
    ).hexdigest()
    assert vista["cuerpo"]["signature"] == esperada


def test_no_cobra_un_medio_de_otro_proveedor():
    orden = OrdenDeCobro(
        intencion_id="int_1",
        medio=MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "1"),
        monto=Dinero.de_pesos(1_000), glosa="x", correo_pagador="a@b.com",
    )
    with pytest.raises(ErrorDePasarela):
        _adaptador(lambda req: httpx.Response(404, json={})).cobrar(orden)


def test_error_4xx_de_wompi_se_traduce_a_error_de_pasarela():
    def responder(req: httpx.Request) -> httpx.Response:
        if "/merchants/" in req.url.path:
            return httpx.Response(200, json=ACEPTACIONES)
        return httpx.Response(422, json={"error": {"messages": {"reference": ["ya existe"]}}})

    with pytest.raises(ErrorDePasarela) as exc:
        _adaptador(responder).cobrar(_orden())
    assert not exc.value.reintentable


def test_error_5xx_de_wompi_es_reintentable():
    def responder(req: httpx.Request) -> httpx.Response:
        if "/merchants/" in req.url.path:
            return httpx.Response(200, json=ACEPTACIONES)
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(PasarelaNoDisponible) as exc:
        _adaptador(responder).cobrar(_orden())
    assert exc.value.reintentable


def test_fallo_de_red_es_reintentable():
    def responder(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no hay red", request=req)

    with pytest.raises(PasarelaNoDisponible):
        _adaptador(responder).cobrar(_orden())


def test_consultar_cobro():
    def responder(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path.endswith("/tx1"):
            return httpx.Response(
                200, json={"data": {"id": "tx1", "status": "APPROVED",
                                     "reference": "agora-int_1"}},
            )
        return httpx.Response(404, json={})

    r = _adaptador(responder).consultar_cobro("tx1")
    assert r.estado is EstadoCobro.APROBADO
    assert r.referencia == "agora-int_1"


# --------------------------------------------------------------------------- #
# Enrolamiento
# --------------------------------------------------------------------------- #


def test_preparar_medio_no_bloquea_esperando_el_push():
    """A diferencia de `boveda/enrolamiento.py:enrolar_nequi`, que sondea
    hasta 300s dentro de la misma llamada, aqui solo se crea el token."""

    def responder(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/tokens/nequi") and req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "tok_1", "status": "PENDING"}})
        return httpx.Response(404, json={})

    en_proceso = _adaptador(responder).preparar_medio(
        SolicitudEnrolamiento("3001234567", "juan@correo-real.com", Ambiente.SANDBOX)
    )
    assert en_proceso.token == "tok_1"
    assert en_proceso.estado == "PENDING"


def test_confirmar_medio_crea_la_fuente_de_pago():
    def responder(req: httpx.Request) -> httpx.Response:
        if "/merchants/" in req.url.path:
            return httpx.Response(200, json=ACEPTACIONES)
        if req.url.path.endswith("/payment_sources") and req.method == "POST":
            return httpx.Response(201, json={"data": {"id": 99, "status": "AVAILABLE"}})
        return httpx.Response(404, json={})

    estado = _adaptador(responder).confirmar_medio("tok_1", "juan@correo-real.com")
    assert estado.disponible
    assert estado.ref == MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "99")


def test_revocar_medio():
    def responder(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/void") and req.method == "PUT":
            return httpx.Response(200, json={"data": {"id": 99, "status": "VOIDED"}})
        return httpx.Response(404, json={})

    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "99")
    estado = _adaptador(responder).revocar_medio(ref)
    assert estado.estado == "VOIDED"


# --------------------------------------------------------------------------- #
# Eventos
# --------------------------------------------------------------------------- #


def _evento_valido(secreto: str) -> tuple[bytes, str]:
    data = {"transaction": {"id": "tx1", "status": "APPROVED"}}
    ts = 1_700_000_000
    props = ["transaction.id", "transaction.status"]
    checksum = hashlib.sha256(
        ("tx1" + "APPROVED" + str(ts) + secreto).encode("utf-8")
    ).hexdigest()
    evento = {
        "event": "transaction.updated",
        "data": data,
        "timestamp": ts,
        "signature": {"properties": props, "checksum": checksum},
    }
    return json.dumps(evento).encode("utf-8"), checksum


def test_validar_evento_con_checksum_correcto():
    cuerpo, _ = _evento_valido("secreto_evt")
    adaptador = _adaptador(lambda req: httpx.Response(404, json={}))
    evento = adaptador.validar_evento(cuerpo, {})
    assert evento["data"]["transaction"]["id"] == "tx1"


def test_validar_evento_con_checksum_incorrecto_levanta():
    cuerpo, _ = _evento_valido("otro_secreto")
    adaptador = _adaptador(lambda req: httpx.Response(404, json={}))
    with pytest.raises(ErrorDePasarela, match="checksum"):
        adaptador.validar_evento(cuerpo, {})


def test_validar_evento_sin_checksum_levanta():
    cuerpo = json.dumps({"event": "x", "data": {}}).encode("utf-8")
    adaptador = _adaptador(lambda req: httpx.Response(404, json={}))
    with pytest.raises(ErrorDePasarela):
        adaptador.validar_evento(cuerpo, {})
