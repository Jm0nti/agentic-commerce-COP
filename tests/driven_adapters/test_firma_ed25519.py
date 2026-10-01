"""`FirmanteEd25519` + `cargar_o_generar_firmante`: la mitad de firma del
`Verificador` que ya se probaba solo. Una firma que sale de `FirmanteEd25519`
tiene que validar contra `VerificadorEd25519`, y la llave en disco tiene que
sobrevivir una recarga -- eso es lo que hace posible "igual que v1: llave en
disco", que el mismo mandato firmado hoy siga verificando manana."""

from __future__ import annotations

from agora.driven_adapters.firma_ed25519.firma_ed25519 import (
    VerificadorEd25519,
    cargar_o_generar_firmante,
)


def test_firma_generada_valida_contra_el_verificador(tmp_path):
    firmante = cargar_o_generar_firmante(tmp_path / "firma.sk", tmp_path / "firma.pk")
    carga = b"hola mundo"

    firma = firmante.firma(carga)

    assert VerificadorEd25519().verifica(firma, carga, firmante.llave_publica())


def test_genera_las_llaves_una_sola_vez_y_las_reusa(tmp_path):
    ruta_sk = tmp_path / "firma.sk"
    ruta_pk = tmp_path / "firma.pk"

    primero = cargar_o_generar_firmante(ruta_sk, ruta_pk)
    assert ruta_sk.exists() and ruta_pk.exists()

    segundo = cargar_o_generar_firmante(ruta_sk, ruta_pk)

    assert primero.llave_publica() == segundo.llave_publica()
    assert ruta_pk.read_bytes() == primero.llave_publica()


def test_una_firma_de_una_llave_no_valida_contra_otra(tmp_path):
    a = cargar_o_generar_firmante(tmp_path / "a.sk", tmp_path / "a.pk")
    b = cargar_o_generar_firmante(tmp_path / "b.sk", tmp_path / "b.pk")
    carga = b"carga"

    firma = a.firma(carga)

    assert not VerificadorEd25519().verifica(firma, carga, b.llave_publica())
