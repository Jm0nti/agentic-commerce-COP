"""Persistencia de usuarios y de sus llaves de firma. Salio de
`puertos/repositorios.py` (Fase 2 del refactor a la Clean Architecture de
Bancolombia).
"""

from __future__ import annotations

from typing import Protocol

from ..modelo import Usuario


class RepositorioUsuarios(Protocol):
    """Multi-usuario (4 de septiembre de 2026). `guardar` es upsert por
    `titular_id` (mismo criterio que el resto de los repositorios de este
    archivo). `nombre_usuario` es UNICO -- `RegistrarUsuario` (`aplicacion/
    autenticacion.py`) verifica `buscar_por_nombre_usuario` antes de crear
    uno nuevo, para no dejar dos usuarios respondiendo al mismo login."""

    def guardar(self, usuario: Usuario) -> None: ...

    def buscar_por_nombre_usuario(self, nombre_usuario: str) -> Usuario | None: ...

    def buscar_por_titular(self, titular_id: str) -> Usuario | None: ...


class RepositorioLlaves(Protocol):
    """La llave de firma ed25519 de cada titular -- separada de `Usuario`
    a proposito (ver el docstring de `dominio/usuario/modelo.py`). Solo
    guarda bytes crudos, nunca objetos de `cryptography`: igual que
    `Mandato.firma`, la forma de USAR esos bytes (firmar, derivar la
    publica) vive en el adaptador (`adaptadores/sistema/firma_ed25519.py`),
    no en el puerto.

    `SelectorDeFirmante` (`puertos/firma.py`) es quien de verdad consume
    `llave_privada_de` para armar un `Firmante` -- este repositorio solo
    guarda y devuelve bytes, nunca decide que hacer si un titular no tiene
    llave (eso es `RegistroDeFirmantes`, que levanta `SinLlaveDeFirma`)."""

    def guardar(self, titular_id: str, llave_privada: bytes, llave_publica: bytes) -> None: ...

    def llave_privada_de(self, titular_id: str) -> bytes | None:
        """Los 32 bytes crudos de la llave privada ed25519 de este
        titular, o `None` si nunca se creo una -- nunca genera una al
        vuelo, eso lo decide `RegistroDeFirmantes`."""
        ...
