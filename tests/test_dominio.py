"""El dominio, sin red, sin disco y sin variables de entorno.

Todo lo que se prueba aqui corre en memoria. Si alguna de estas pruebas
necesitara un monkeypatch de `os.environ` o un archivo temporal, la capa estaria
mal cortada.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agora.dominio.catalogo.modelo import Carrito, ItemCarrito
from agora.dominio.comun.dinero import CERO, Dinero
from agora.dominio.mandato.modelo import Consumo, Intencion, Mandato
from agora.dominio.mandato.politica import Decision, evaluar
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor
from agora.dominio.pago.topes import TopesDuros

AHORA = datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc)


class VerificadorEd25519:
    def verifica(self, firma: bytes, carga: bytes, llave_publica: bytes) -> bool:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        try:
            Ed25519PublicKey.from_public_bytes(llave_publica).verify(firma, carga)
            return True
        except (InvalidSignature, ValueError):
            return False


# --------------------------------------------------------------------------- #
# Dinero
# --------------------------------------------------------------------------- #


def test_pesos_y_centavos_no_se_confunden():
    """El bug que este tipo existe para evitar: hoy conviven `monto_cop` y
    `amount_in_cents` con un `* 100` suelto en la frontera."""
    assert Dinero.de_pesos(2050).centavos == 205_000
    assert Dinero.de_centavos(205_000).pesos == 2050
    assert Dinero.de_pesos(2050) == Dinero.de_centavos(205_000)


def test_no_se_mezclan_monedas():
    with pytest.raises(ValueError, match="no se pueden mezclar"):
        Dinero.de_pesos(1000, "COP") + Dinero.de_pesos(1000, "USD")


def test_no_hay_dinero_negativo():
    with pytest.raises(ValueError):
        Dinero(-1)
    with pytest.raises(ValueError):
        Dinero.de_pesos(1000) - Dinero.de_pesos(2000)


def test_suma_y_comparacion():
    assert Dinero.de_pesos(8000) + Dinero.de_pesos(7000) == Dinero.de_pesos(15_000)
    assert Dinero.de_pesos(15_000).excede(Dinero.de_pesos(8_000))
    assert not Dinero.de_pesos(2050).excede(Dinero.de_pesos(20_000))
    assert (CERO + Dinero.de_pesos(1)).centavos == 100


# --------------------------------------------------------------------------- #
# Topes duros
# --------------------------------------------------------------------------- #


def test_los_topes_duros_son_los_de_siempre():
    """20.000 por transaccion. Si esto cambia sin una decision explicita, la
    proteccion que permite estudiar el mandato dejo de ser la que se documento."""
    t = TopesDuros()
    assert t.por_transaccion == Dinero.de_pesos(20_000)
    assert t.por_dia == Dinero.de_pesos(100_000)
    assert t.excede(Dinero.de_pesos(25_000)) is not None
    assert t.excede(Dinero.de_pesos(2_050)) is None


# --------------------------------------------------------------------------- #
# Carrito
# --------------------------------------------------------------------------- #


def _items():
    return (
        ItemCarrito("prd_a", "Audifonos", 2, Dinero.de_pesos(18_000)),
        ItemCarrito("prd_b", "Cable", 1, Dinero.de_pesos(9_000)),
    )


def test_total_del_carrito():
    c = Carrito("car_1", "com_x", _items())
    assert c.total == Dinero.de_pesos(45_000)


def test_el_hash_no_depende_del_orden():
    a = Carrito("car_1", "com_x", _items())
    b = Carrito("car_2", "com_x", tuple(reversed(_items())))
    assert a.hash_canonico == b.hash_canonico


def test_cambiar_un_item_cambia_el_hash_aunque_el_total_no():
    """El ataque real contra un Cart Mandate: mismo monto, mismo comercio,
    otra cosa dentro."""
    original = Carrito("car_1", "com_x", (
        ItemCarrito("prd_a", "Audifonos", 1, Dinero.de_pesos(45_000)),
    ))
    alterado = Carrito("car_1", "com_x", (
        ItemCarrito("prd_z", "Consola", 1, Dinero.de_pesos(45_000)),
    ))
    assert original.total == alterado.total
    assert original.hash_canonico != alterado.hash_canonico


def test_carrito_vacio_no_existe():
    with pytest.raises(ValueError, match="carrito vacio"):
        Carrito("car_1", "com_x", ())


# --------------------------------------------------------------------------- #
# Mandato v2
# --------------------------------------------------------------------------- #


def _mandato(sk: Ed25519PrivateKey, **kw) -> Mandato:
    from cryptography.hazmat.primitives import serialization

    pub = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    base = dict(
        mandato_id="mnd_prueba01",
        titular_id="tit_1",
        medio=MedioDePagoRef(Proveedor.WOMPI, Ambiente.PRODUCCION, "22620436"),
        comercio_id="com_x",
        monto_max=Dinero.de_pesos(8_000),
        tope_total=Dinero.de_pesos(8_000),
        usos_max=1,
        expira_en=AHORA + timedelta(hours=1),
        creado_en=AHORA,
        llave_publica=pub,
    )
    base.update(kw)
    m = Mandato(**base)
    return Mandato(**{**base, "firma": sk.sign(m.canonico())})


def _intencion(monto_pesos: int, comercio="com_x", **kw) -> Intencion:
    return Intencion(
        intencion_id="int_1",
        mandato_id=kw.pop("mandato_id", "mnd_prueba01"),
        comercio_id=comercio,
        carrito_id="car_1",
        monto=Dinero.de_pesos(monto_pesos),
        **kw,
    )


def test_mandato_bien_firmado_no_tiene_violaciones():
    sk = Ed25519PrivateKey.generate()
    m = _mandato(sk)
    v = m.violaciones_contra(_intencion(8_000), Consumo(), VerificadorEd25519(), AHORA)
    assert v == []


def test_la_version_va_dentro_de_la_firma():
    """Sin esto, alguien podria presentar un v1 como v2 sin romper la firma."""
    sk = Ed25519PrivateKey.generate()
    m = _mandato(sk)
    assert b'"version":2' in m.canonico()


def test_monto_sobre_el_mandato():
    """El caso del experimento: el mandato autoriza 8.000, la intencion pide
    15.000. Esa corrida existe en recibos.jsonl."""
    sk = Ed25519PrivateKey.generate()
    m = _mandato(sk)
    tipos = {x.tipo for x in m.violaciones_contra(
        _intencion(15_000), Consumo(), VerificadorEd25519(), AHORA)}
    assert "monto_sobre_mandato" in tipos
    assert "tope_total_agotado" in tipos


def test_alterar_el_cuerpo_invalida_la_firma():
    sk = Ed25519PrivateKey.generate()
    m = _mandato(sk)
    from dataclasses import replace

    inflado = replace(m, monto_max=Dinero.de_pesos(5_000_000))
    tipos = {x.tipo for x in inflado.violaciones_contra(
        _intencion(100_000), Consumo(), VerificadorEd25519(), AHORA)}
    assert "firma_invalida" in tipos


def test_carrito_alterado_tras_la_firma():
    sk = Ed25519PrivateKey.generate()
    carrito = Carrito("car_1", "com_x", _items())
    m = _mandato(sk, carrito_hash=carrito.hash_canonico,
                 monto_max=Dinero.de_pesos(45_000),
                 tope_total=Dinero.de_pesos(45_000))

    otro = Carrito("car_1", "com_x", (
        ItemCarrito("prd_z", "Consola", 1, Dinero.de_pesos(45_000)),))
    tipos = {x.tipo for x in m.violaciones_contra(
        _intencion(45_000), Consumo(), VerificadorEd25519(), AHORA,
        carrito_hash=otro.hash_canonico)}
    assert "carrito_alterado" in tipos

    sin_tipos = m.violaciones_contra(
        _intencion(45_000), Consumo(), VerificadorEd25519(), AHORA,
        carrito_hash=carrito.hash_canonico)
    assert sin_tipos == []


def test_el_tiempo_es_un_parametro():
    """Antes probar un vencimiento obligaba a emitir con vigencia negativa."""
    sk = Ed25519PrivateKey.generate()
    m = _mandato(sk)
    despues = AHORA + timedelta(hours=2)
    tipos = {x.tipo for x in m.violaciones_contra(
        _intencion(8_000), Consumo(), VerificadorEd25519(), despues)}
    assert tipos == {"vencido"}


# --------------------------------------------------------------------------- #
# Politica
# --------------------------------------------------------------------------- #


def test_dictamen_permitir():
    sk = Ed25519PrivateKey.generate()
    m = _mandato(sk, monto_max=Dinero.de_pesos(20_000),
                 tope_total=Dinero.de_pesos(100_000), usos_max=5)
    d = evaluar(m, _intencion(2_050), Consumo(), VerificadorEd25519(), ahora=AHORA)
    assert d.decision is Decision.PERMITIR
    assert d.deja_pasar


def test_dictamen_bloquear():
    sk = Ed25519PrivateKey.generate()
    m = _mandato(sk)
    d = evaluar(m, _intencion(15_000), Consumo(), VerificadorEd25519(), ahora=AHORA)
    assert d.decision is Decision.BLOQUEAR
    assert d.violaciones


def test_dictamen_confirmar_cuando_agota_el_mandato():
    """Cabe en el mandato, pero se lo gasta todo de una. No es una violacion:
    es una pregunta para el humano."""
    sk = Ed25519PrivateKey.generate()
    m = _mandato(sk, monto_max=Dinero.de_pesos(8_000),
                 tope_total=Dinero.de_pesos(8_000), usos_max=1)
    d = evaluar(m, _intencion(8_000), Consumo(), VerificadorEd25519(), ahora=AHORA)
    assert d.decision is Decision.CONFIRMAR
    assert d.violaciones == []
    assert d.senales


def test_sin_mandato_deja_pasar_pero_deja_escrito():
    """El brazo sin control. Sigue registrando las violaciones -- que la
    pasarela apruebe un cobro que el mandato no autorizaba es la metrica."""
    sk = Ed25519PrivateKey.generate()
    m = _mandato(sk)
    d = evaluar(m, _intencion(15_000), Consumo(), VerificadorEd25519(),
                exigir_mandato=False, ahora=AHORA)
    assert d.decision is Decision.PERMITIR
    assert {v.tipo for v in d.violaciones} >= {"monto_sobre_mandato"}
