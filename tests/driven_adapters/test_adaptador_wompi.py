"""`AdaptadorWompi`, contra una Wompi simulada con `httpx.MockTransport`.

No hay red real en las pruebas, pero el `ClienteWompi` que corre es el de
verdad, solo con el transporte HTTP sustituido.
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from agora.driven_adapters.pasarela_wompi import AdaptadorWompi, ConfiguracionWompi
from agora.driven_adapters.pasarela_wompi.cliente import ClienteWompi
from agora.driven_adapters.pasarela_wompi.config import ConfiguracionInvalida
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import ErrorDePasarela, PasarelaNoDisponible
from agora.model.pago.modelo import Ambiente, EstadoCobro, MedioDePagoRef, OrdenDeCobro, Proveedor
from agora.model.pago.gateways.pasarela import SolicitudEnrolamiento

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
    mentiras."""
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
    """Reproduce la forma exacta de la corrida real (`docs/utils/decline-afe.md`):
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
    """Solo se crea el token: sondear hasta 300s esperando el push no es
    trabajo del adaptador."""

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


def test_revocar_medio_nequi_no_levanta_se_desactiva_local_con_aviso():
    """Hallazgo del 7 sept 2026 (produccion real, Juan): Wompi documenta
    `/void` solo para DaviPlata y Bancolombia -- una fuente Nequi (la unica
    que usa esta app) responde 422 con este motivo puntual. No es un error
    transitorio: `revocar_medio` lo traduce a un desenlace "desactivado solo
    en esta app", no a una excepcion."""
    def responder(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/void") and req.method == "PUT":
            return httpx.Response(
                422,
                json={
                    "error": {
                        "type": "UNPROCESSABLE",
                        "reason": (
                            "Únicamente se pueden anular fuentes de pago con "
                            "el tipo de operación financiera 'PREAUTHORIZATION'"
                        ),
                    }
                },
            )
        return httpx.Response(404, json={})

    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22906782")
    estado = _adaptador(responder).revocar_medio(ref)

    assert estado.estado == "VOIDED_LOCAL"
    assert estado.ref == ref
    assert "Nequi" in estado.detalle["aviso"] or "app Nequi" in estado.detalle["aviso"]
    assert "PREAUTHORIZATION" in estado.detalle["motivo_wompi"]


def test_revocar_medio_otro_error_de_wompi_si_levanta():
    """El fallback de arriba es especifico del motivo "PREAUTHORIZATION" --
    cualquier otro 4xx (credenciales, fuente inexistente, lo que sea) tiene
    que seguir siendo un error real, no algo que se trague en silencio."""
    def responder(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/void") and req.method == "PUT":
            return httpx.Response(404, json={"error": {"type": "NOT_FOUND", "reason": "no existe"}})
        return httpx.Response(404, json={})

    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22906782")
    with pytest.raises(ErrorDePasarela):
        _adaptador(responder).revocar_medio(ref)


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


# --------------------------------------------------------------------------- #
# resultado_desde_evento (etapa 4)
# --------------------------------------------------------------------------- #


def _evento_transaccion(reference: str, status: str = "APPROVED", tipo: str = "transaction.updated") -> dict:
    return {
        "event": tipo,
        "data": {
            "transaction": {
                "id": "tx1",
                "reference": reference,
                "status": status,
                "status_message": "ok",
                "payment_method": {"afe_decision": "ACCEPT"},
            }
        },
    }


def test_resultado_desde_evento_traduce_una_referencia_propia():
    adaptador = _adaptador(lambda req: httpx.Response(404, json={}))
    evento = _evento_transaccion("agora-int_1")

    traduccion = adaptador.resultado_desde_evento(evento)

    assert traduccion is not None
    intencion_id, resultado = traduccion
    assert intencion_id == "int_1"
    assert resultado.estado is EstadoCobro.APROBADO
    assert resultado.id_externo == "tx1"


def test_resultado_desde_evento_ignora_una_referencia_ajena():
    """Una referencia sin el prefijo `agora-` no es de esta app -- por
    ejemplo, trafico de otro sistema que comparta el mismo webhook de Wompi."""
    adaptador = _adaptador(lambda req: httpx.Response(404, json={}))
    evento = _evento_transaccion("referencia-de-otro-sistema")

    assert adaptador.resultado_desde_evento(evento) is None


def test_resultado_desde_evento_ignora_otro_tipo_de_evento():
    adaptador = _adaptador(lambda req: httpx.Response(404, json={}))
    evento = _evento_transaccion("agora-int_1", tipo="transaction.created")

    assert adaptador.resultado_desde_evento(evento) is None
