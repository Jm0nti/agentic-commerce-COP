"""`HasherPBKDF2`: implementa `puertos.autenticacion.HasherDeContrasenas`.

PBKDF2-HMAC-SHA256 via `hashlib` (stdlib) -- ninguna dependencia nueva.
`bcrypt`/`argon2` resisten mejor un ataque de hardware dedicado, pero
agregarian una dependencia externa solo para una PoC de un solo binario por
usuario; `hashlib.pbkdf2_hmac` con una sal aleatoria de 16 bytes y 200.000
iteraciones (el piso que OWASP recomienda para PBKDF2-SHA256, 2023) alcanza
para lo que esta version necesita probar.

FORMATO DEL HASH GUARDADO
----------------------------
`"pbkdf2_sha256${iteraciones}${sal_hex}${derivado_hex}"` -- el numero de
iteraciones viaja DENTRO del hash (no en una constante separada) para que
subirlo en una version futura no invalide los hashes ya guardados: `verifica`
siempre usa las iteraciones que el hash guardado dice, no las que esta
version considera el default.
"""

from __future__ import annotations

import hashlib
import hmac
import os

_ITERACIONES_POR_DEFECTO = 200_000
_LARGO_SAL = 16


class HasherPBKDF2:
    """Implementa `puertos.autenticacion.HasherDeContrasenas`."""

    def __init__(self, iteraciones: int = _ITERACIONES_POR_DEFECTO) -> None:
        self._iteraciones = iteraciones

    def hashear(self, contrasena: str) -> str:
        sal = os.urandom(_LARGO_SAL)
        derivado = self._derivar(contrasena, sal, self._iteraciones)
        return f"pbkdf2_sha256${self._iteraciones}${sal.hex()}${derivado.hex()}"

    def verifica(self, contrasena: str, hash_guardado: str) -> bool:
        try:
            algoritmo, iteraciones_txt, sal_hex, derivado_hex = hash_guardado.split("$")
            if algoritmo != "pbkdf2_sha256":
                return False
            sal = bytes.fromhex(sal_hex)
            esperado = bytes.fromhex(derivado_hex)
        except (ValueError, AttributeError):
            return False
        calculado = self._derivar(contrasena, sal, int(iteraciones_txt))
        return hmac.compare_digest(calculado, esperado)

    @staticmethod
    def _derivar(contrasena: str, sal: bytes, iteraciones: int) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), sal, iteraciones)
