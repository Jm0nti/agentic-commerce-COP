"""El puente entre la v1 que corre hoy y la v2 que la va a reemplazar.

Esta es la prueba que hace segura la etapa 2. No comprueba que el codigo nuevo
funcione -- eso lo hace `test_dominio.py` -- sino que **el codigo nuevo dice
exactamente lo mismo que el viejo sobre los mismos datos**.

Sin ella, migrar seria un acto de fe: los mandatos reales de
`boveda/secretos/estado.json` estan firmados con el formato v1, y si el lector
nuevo se equivoca en un byte de la carga canonica, la firma no valida y la
evidencia del experimento se vuelve irreverificable.

Los mandatos v1 se generan aqui con el codigo v1 de verdad (`boveda/mandato.py`),
no con una reimplementacion. Comparar una copia contra si misma no probaria nada.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# el codigo v1 que corre hoy y mueve dinero
from boveda.mandato import Consumo as ConsumoV1
from boveda.mandato import Intencion as IntencionV1
from boveda.mandato import emitir as emitir_v1
from boveda.mandato import evaluar as evaluar_v1

# el codigo v2
from agora.dominio.comun.dinero import Dinero
from agora.dominio.mandato.compat import es_v1, leer_estado_v1, leer_v1
from agora.dominio.mandato.modelo import Consumo, Intencion


class VerificadorEd25519:
    def verifica(self, firma: bytes, carga: bytes, llave_publica: bytes) -> bool:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        try:
            Ed25519PublicKey.from_public_bytes(llave_publica).verify(firma, carga)
            return True
        except (InvalidSignature, ValueError):
            return False


@pytest.fixture
def llaves():
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return sk, sk.public_key(), pub


def _v1(sk, **kw):
    base = dict(
        titular="titular_0001",
        fuente_pago=22620436,
        comercio="tienda_demo",
        monto_max_cop=8000,
        sk=sk,
        usos_max=1,
        vigencia_min=60,
    )
    base.update(kw)
    return emitir_v1(**base)


def _par_de_intenciones(monto_cop: int, comercio="tienda_demo", mandato_id="", categoria=""):
    """La misma intencion, expresada en los dos modelos."""
    v1 = IntencionV1(
        mandato_id=mandato_id, comercio=comercio, sku="sku-demo",
        monto_cop=monto_cop, categoria=categoria,
    )
    v2 = Intencion(
        intencion_id="int_1", mandato_id=mandato_id, comercio_id=comercio,
        carrito_id="car_1", monto=Dinero.de_pesos(monto_cop), categoria=categoria,
    )
    return v1, v2


# --------------------------------------------------------------------------- #
# La carga canonica
# --------------------------------------------------------------------------- #


def test_la_carga_canonica_es_identica_byte_a_byte(llaves):
    """Lo mas importante del archivo. Si esto falla, ninguna firma v1 valida."""
    sk, _, _ = llaves
    original = _v1(sk)
    leido = leer_v1(original.to_json())
    assert leido.canonico() == original.carga()


def test_la_firma_v1_valida_con_el_verificador_nuevo(llaves):
    sk, _, pub = llaves
    original = _v1(sk)
    leido = leer_v1(original.to_json())
    assert leido.verifica(VerificadorEd25519(), pub)


def test_una_firma_ajena_no_valida(llaves):
    sk, _, _ = llaves
    otra = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    leido = leer_v1(_v1(sk).to_json())
    assert not leido.verifica(VerificadorEd25519(), otra)


@pytest.mark.parametrize("campo,valor", [
    ("monto_max_cop", 5_000_000),
    ("comercio", "tienda_del_atacante"),
    ("usos_max", 99),
    ("expira_en", "2099-01-01T00:00:00+00:00"),
])
def test_alterar_el_json_rompe_la_firma(llaves, campo, valor):
    sk, _, pub = llaves
    crudo = _v1(sk).to_json()
    crudo[campo] = valor
    assert not leer_v1(crudo).verifica(VerificadorEd25519(), pub)


# --------------------------------------------------------------------------- #
# Equivalencia de veredictos
# --------------------------------------------------------------------------- #


ESCENARIOS = [
    ("camino feliz", 8_000, "tienda_demo", "", 0, 0),
    ("monto sobre el mandato", 15_000, "tienda_demo", "", 0, 0),
    ("comercio no autorizado", 8_000, "tienda_del_atacante", "", 0, 0),
    ("usos agotados", 8_000, "tienda_demo", "", 1, 0),
    ("tope acumulado", 8_000, "tienda_demo", "", 0, 8_000),
    ("todo mal a la vez", 15_000, "otro", "", 1, 8_000),
]


@pytest.mark.parametrize(
    "nombre,monto,comercio,categoria,usos,acumulado", ESCENARIOS,
    ids=[e[0] for e in ESCENARIOS],
)
def test_los_dos_modelos_dan_las_mismas_violaciones(
    llaves, nombre, monto, comercio, categoria, usos, acumulado
):
    """El veredicto no puede cambiar al migrar.

    Si el codigo nuevo bloquea algo que el viejo dejaba pasar (o al reves), los
    resultados anteriores del experimento dejarian de ser comparables con los
    siguientes -- y la PoC vive de esa comparacion.
    """
    sk, pk, pub = llaves
    m = _v1(sk)
    i_v1, i_v2 = _par_de_intenciones(monto, comercio, m.mandato_id, categoria)

    tipos_v1 = {v.tipo for v in evaluar_v1(
        m, i_v1, ConsumoV1(usos=usos, acumulado_cop=acumulado), pk)}

    leido = leer_v1(m.to_json())
    tipos_v2 = {v.tipo for v in leido.violaciones_contra(
        i_v2,
        Consumo(usos=usos, acumulado=Dinero.de_pesos(acumulado)),
        VerificadorEd25519(),
        datetime.now(timezone.utc),
        llave_publica=pub,
    )}

    assert tipos_v1 == tipos_v2, f"{nombre}: v1={tipos_v1} v2={tipos_v2}"


def test_tambien_coinciden_cuando_el_mandato_vencio(llaves):
    sk, pk, pub = llaves
    m = _v1(sk, vigencia_min=-120)
    i_v1, i_v2 = _par_de_intenciones(8_000, mandato_id=m.mandato_id)

    tipos_v1 = {v.tipo for v in evaluar_v1(m, i_v1, ConsumoV1(), pk)}
    tipos_v2 = {v.tipo for v in leer_v1(m.to_json()).violaciones_contra(
        i_v2, Consumo(), VerificadorEd25519(), datetime.now(timezone.utc),
        llave_publica=pub)}

    assert "vencido" in tipos_v1
    assert tipos_v1 == tipos_v2


def test_categorias_coinciden(llaves):
    sk, pk, pub = llaves
    m = _v1(sk, categorias=["mercado"])
    i_v1, i_v2 = _par_de_intenciones(
        8_000, mandato_id=m.mandato_id, categoria="electronica")

    tipos_v1 = {v.tipo for v in evaluar_v1(m, i_v1, ConsumoV1(), pk)}
    tipos_v2 = {v.tipo for v in leer_v1(m.to_json()).violaciones_contra(
        i_v2, Consumo(), VerificadorEd25519(), datetime.now(timezone.utc),
        llave_publica=pub)}

    assert "categoria_no_autorizada" in tipos_v1
    assert tipos_v1 == tipos_v2


# --------------------------------------------------------------------------- #
# Lectura de un estado.json completo
# --------------------------------------------------------------------------- #


def test_se_lee_un_estado_json_entero(llaves):
    sk, _, pub = llaves
    a, b = _v1(sk), _v1(sk, monto_max_cop=2_000)
    estado = {
        "mandatos": {a.mandato_id: a.to_json(), b.mandato_id: b.to_json()},
        "consumo": {a.mandato_id: {"usos": 0, "acumulado_cop": 0}},
        "dia": "2026-08-19",
        "gastado_dia_cop": 2050,
        "modos": {a.mandato_id: "produccion"},
    }
    leidos = leer_estado_v1(estado)
    assert set(leidos) == {a.mandato_id, b.mandato_id}
    assert all(m.verifica(VerificadorEd25519(), pub) for m in leidos.values())


def test_se_distingue_un_v1_de_un_v2():
    assert es_v1({"fuente_pago": 1, "mandato_id": "x"})
    assert not es_v1({"version": 2, "medio": {}, "mandato_id": "x"})


def test_un_campo_desconocido_es_un_error_no_un_silencio():
    """Si el formato cambio, la firma ya no cuadra: mejor fallar fuerte que
    verificar contra una carga incompleta."""
    with pytest.raises(ValueError, match="campos desconocidos"):
        leer_v1({
            "mandato_id": "m", "titular": "t", "fuente_pago": 1,
            "comercio": "c", "monto_max_cop": 1, "tope_total_cop": 1,
            "usos_max": 1, "expira_en": "x", "creado_en": "y",
            "categorias": [], "firma": "", "campo_nuevo": 42,
        })
