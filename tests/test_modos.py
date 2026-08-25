"""Un mandato de un ambiente no se ejecuta en el otro.

`fuentes.json` ya separaba por modo. `estado.json` no: los mandatos de sandbox
y de produccion viven en el mismo archivo. Como `fuente_pago` es un entero, un
mandato emitido en sandbox ejecutado en produccion manda un id de sandbox a la
Wompi real -- donde ese numero existe y pertenece a otra persona.
"""

from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from boveda.mandato import Intencion, emitir
from boveda.nucleo import Boveda, BovedaError

COMERCIO = {
    "data": {
        "name": "Demo",
        "legal_name": "Demo",
        "accepted_payment_methods": ["NEQUI"],
        "presigned_acceptance": {"acceptance_token": "t", "permalink": "u"},
        "presigned_personal_data_auth": {"acceptance_token": "d", "permalink": "u"},
    }
}


def _transporte():
    def responder(req: httpx.Request) -> httpx.Response:
        if "/merchants/" in req.url.path:
            return httpx.Response(200, json=COMERCIO)
        return httpx.Response(404, json={})

    return httpx.MockTransport(responder)


def _boveda(tmp_path, modo, monkeypatch) -> Boveda:
    pref = "test" if modo == "sandbox" else "prod"
    monkeypatch.setenv("WOMPI_PUBLIC_KEY", f"pub_{pref}_x")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", f"prv_{pref}_x")
    monkeypatch.setenv("WOMPI_INTEGRITY_SECRET", "x")
    sk = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
    b = Boveda(sk, sk.public_key(), tmp_path / "estado.json", modo=modo)
    b.cliente.http = httpx.Client(transport=_transporte(), timeout=5)
    return b


def test_mandato_de_sandbox_no_se_ejecuta_en_produccion(tmp_path, monkeypatch):
    sk = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
    sb = _boveda(tmp_path, "sandbox", monkeypatch)
    m = emitir(
        titular="t", fuente_pago=363784, comercio="tienda_demo",
        monto_max_cop=5000, sk=sk,
    )
    sb.registrar(m)

    prod = _boveda(tmp_path, "produccion", monkeypatch)
    with pytest.raises(BovedaError, match="se emitio en 'sandbox'"):
        prod.ejecutar(
            Intencion(
                mandato_id=m.mandato_id, comercio="tienda_demo",
                sku="s", monto_cop=5000,
            )
        )


def test_en_su_propio_modo_si_lo_encuentra(tmp_path, monkeypatch):
    sk = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
    sb = _boveda(tmp_path, "sandbox", monkeypatch)
    m = emitir(
        titular="t", fuente_pago=363784, comercio="tienda_demo",
        monto_max_cop=5000, sk=sk,
    )
    sb.registrar(m)
    otra = _boveda(tmp_path, "sandbox", monkeypatch)
    mandato, consumo = otra.obtener(m.mandato_id)
    assert mandato.mandato_id == m.mandato_id
    assert consumo.usos == 0


def test_mandato_viejo_sin_modo_registrado_no_rompe(tmp_path, monkeypatch):
    """Los mandatos emitidos antes de esta guarda no traen modo. Se dejan
    pasar: romper el estado existente seria peor que la guarda que falta."""
    sk = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
    b = _boveda(tmp_path, "produccion", monkeypatch)
    m = emitir(
        titular="t", fuente_pago=22620436, comercio="tienda_demo",
        monto_max_cop=2000, sk=sk,
    )
    b.registrar(m)
    del b.estado["modos"][m.mandato_id]  # como si viniera de una version vieja
    b._guardar()

    otra = _boveda(tmp_path, "produccion", monkeypatch)
    mandato, _ = otra.obtener(m.mandato_id)
    assert mandato.fuente_pago == 22620436


def test_un_declined_no_consume_el_mandato(tmp_path, monkeypatch):
    """Solo un APPROVED suma usos. Un rechazo del antifraude deja el mandato
    intacto -- por eso el de ayer sigue con usos 0 aunque ya se ejecuto."""
    sk = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
    b = _boveda(tmp_path, "produccion", monkeypatch)
    m = emitir(
        titular="t", fuente_pago=22620436, comercio="tienda_demo",
        monto_max_cop=2000, sk=sk, usos_max=1,
    )
    b.registrar(m)

    def responder(req: httpx.Request) -> httpx.Response:
        if "/merchants/" in req.url.path:
            return httpx.Response(200, json=COMERCIO)
        if req.url.path.endswith("/transactions") and req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "tx1", "status": "PENDING"}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "tx1",
                    "status": "DECLINED",
                    "status_message": "Por motivos de seguridad...",
                    "payment_method": {"afe_decision": "DECLINE"},
                }
            },
        )

    b.cliente.http = httpx.Client(transport=httpx.MockTransport(responder), timeout=5)
    r = b.ejecutar(
        Intencion(mandato_id=m.mandato_id, comercio="tienda_demo", sku="s", monto_cop=2000)
    )

    assert r.ejecutado is False
    assert r.detenido_por_antifraude is True
    assert r.afe_decision == "DECLINE"
    assert b.estado["consumo"][m.mandato_id]["usos"] == 0
    assert b.estado.get("gastado_dia_cop", 0) == 0
