"""Verificacion de firmas ed25519 contra un mandato.

Implementa el `Verificador` que `dominio/mandato/modelo.py` define como
`Protocol` (y que `dominio/mandato/compat.py` reusa para la v1): recibe la
firma, la carga canonica y la llave publica, todas en bytes, y devuelve un
booleano. El dominio no importa `cryptography` -- eso vive aqui, en el unico
lugar donde la capa de adaptadores toca criptografia.

Antes de este archivo, la misma clase vivia duplicada como test double dentro
de `tests/test_dominio.py`. Promoverla a adaptador real evita que la unica
implementacion de `Verificador` que existe en el repo sea una de pruebas.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class VerificadorEd25519:
    """Implementa el `Verificador` de `dominio.mandato.modelo`."""

    def verifica(self, firma: bytes, carga: bytes, llave_publica: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(llave_publica).verify(firma, carga)
            return True
        except (InvalidSignature, ValueError):
            return False
