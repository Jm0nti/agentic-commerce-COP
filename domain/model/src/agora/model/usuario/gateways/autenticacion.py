"""El puerto de contrasenas. Una sola operacion de cada lado: hashear al
registrar, verificar al iniciar sesion.

Separado de `model/mandato/gateways/firma.py` a proposito: una contrasena autentica a la
PERSONA frente a `entry_points/api_rest/` (web), una llave de firma autoriza un
MANDATO frente a `EmitirMandatoUseCase` -- son dos secretos con ciclos de vida
independientes (cambiar la contrasena no tiene por que rotar la llave de
firma, y al reves), y mezclarlos en una sola interfaz obligaria a todo el
que solo necesita una de las dos operaciones a depender de la otra tambien.

QUIEN CONSTRUYE UN `HasherDeContrasenas` DE VERDAD
-----------------------------------------------------
`driven_adapters/hasher_pbkdf2/hasher_pbkdf2.py:HasherPBKDF2`, armado por
`app_service/config/contenedor.py`. Sin dependencias nuevas: PBKDF2-HMAC-SHA256
via `hashlib` (stdlib), con una sal aleatoria por contrasena -- alcanza
para una PoC sin agregar `bcrypt`/`argon2` como dependencia externa.
"""

from __future__ import annotations

from typing import Protocol


class HasherDeContrasenas(Protocol):
    def hashear(self, contrasena: str) -> str: ...

    def verifica(self, contrasena: str, hash_guardado: str) -> bool: ...
