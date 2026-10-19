"""Firma y verificacion ed25519 de un mandato.

`VerificadorEd25519` implementa el `Verificador` que `model/mandato/
modelo.py` define como `Protocol`: recibe la firma, la carga canonica y la
llave publica, todas en bytes, y devuelve un booleano. El dominio no importa
`cryptography` -- eso vive aqui, en el unico lugar donde la capa de
adaptadores toca criptografia.

Antes de este archivo, la misma clase vivia duplicada como test double dentro
de `tests/model/test_dominio.py`. Promoverla a adaptador real evita que la unica
implementacion de `Verificador` que existe en el repo sea una de pruebas.

`FirmanteEd25519` + `cargar_o_generar_firmante` son la etapa 5: implementan
el `Firmante` de `model/mandato/gateways/firma.py`, del lado de quien SI tiene la llave
privada -- el titular, simulado aqui como un par ed25519 en disco. Solo `app_service/config/contenedor.py` llama
a `cargar_o_generar_firmante`: `usecase/agente/` no importa este modulo (lo verifica
`test_fronteras.py`), y `usecase/emitir_mandato/emitir_mandato_use_case.py` recibe un `Firmante`
ya armado por constructor, sin saber que hay un archivo en disco detras.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class VerificadorEd25519:
    """Implementa el `Verificador` de `dominio.mandato.modelo`."""

    def verifica(self, firma: bytes, carga: bytes, llave_publica: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(llave_publica).verify(firma, carga)
            return True
        except (InvalidSignature, ValueError):
            return False


class FirmanteEd25519:
    """Implementa el `Firmante` de `puertos.firma`."""

    def __init__(self, llave_privada: Ed25519PrivateKey) -> None:
        self._sk = llave_privada

    def firma(self, carga: bytes) -> bytes:
        return self._sk.sign(carga)

    def llave_publica(self) -> bytes:
        return self._sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )


def cargar_o_generar_firmante(ruta_sk: Path, ruta_pk: Path) -> FirmanteEd25519:
    """Lee el par de llaves, o lo genera si no existe.

    Leer y generar van en una sola funcion porque `entry_points/cli/` no tiene
    un flujo de "primero genere sus llaves" -- el titular simulado de una
    demo no deberia tener que saber que existe un paso de bootstrap de
    criptografia antes de poder firmar su primer mandato. Si `ruta_sk` no
    existe, se genera el par y se escribe sin cifrar (alcance de PoC); si existe, se lee tal cual.

    No cifrar la llave privada en disco es una decision de alcance, no un
    descuido: `docs/variables-de-entorno.md` ya documenta que este proceso
    guarda otros secretos (credenciales de Wompi) del mismo modo, y
    `usecase/agente/` nunca llega a este archivo -- `test_fronteras.py` lo verifica.
    """
    if ruta_sk.exists():
        sk = Ed25519PrivateKey.from_private_bytes(ruta_sk.read_bytes())
    else:
        sk = Ed25519PrivateKey.generate()
        ruta_sk.parent.mkdir(parents=True, exist_ok=True)
        ruta_sk.write_bytes(
            sk.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        ruta_pk.parent.mkdir(parents=True, exist_ok=True)
        ruta_pk.write_bytes(
            sk.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
    return FirmanteEd25519(sk)


def generar_par_ed25519() -> tuple[bytes, bytes]:
    """Un par ed25519 nuevo, crudo -- implementa `puertos.firma.
    GeneradorDeLlaves` (via `GeneradorDeLlavesEd25519`, mas abajo). Misma
    codificacion que `cargar_o_generar_firmante`: `Raw`/`Raw`, sin cifrar,
    32 bytes cada una."""
    sk = Ed25519PrivateKey.generate()
    llave_privada = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    llave_publica = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return llave_privada, llave_publica


def firmante_desde_bytes(llave_privada: bytes) -> FirmanteEd25519:
    """Arma un `FirmanteEd25519` a partir de una llave privada cruda ya
    guardada (multi-usuario: `RepositorioLlaves.llave_privada_de`), sin
    pasar por disco -- a diferencia de `cargar_o_generar_firmante`, que lee
    o escribe un archivo. Lo usa `driven_adapters/sistema/
    registro_firmantes.py:RegistroDeFirmantes` para resolver el `Firmante`
    de cada titular en el momento de firmar."""
    return FirmanteEd25519(Ed25519PrivateKey.from_private_bytes(llave_privada))


class GeneradorDeLlavesEd25519:
    """Implementa `puertos.firma.GeneradorDeLlaves`."""

    def generar(self) -> tuple[bytes, bytes]:
        return generar_par_ed25519()
