"""Usuario: la identidad de quien inicia sesion y firma mandatos.

MULTI-USUARIO (4 de septiembre de 2026)
------------------------------------------
Antes de esta version no existia ningun concepto de identidad persistida:
`titular_id` era un `str` que llegaba de un campo de texto libre en
`chat.html`, sin verificacion de ningun tipo, y todos los mandatos se
firmaban con la MISMA llave de proceso (`composicion/contenedor.py:
cargar_o_generar_firmante`). `Usuario` es lo que reemplaza eso: una
identidad real, con su propia contrasena y su propia llave de firma
(`RepositorioLlaves`, no en este archivo -- ver mas abajo).

`Usuario` es liviano A PROPOSITO: solo lleva su identidad (`titular_id`),
el nombre con el que inicia sesion, y el hash de su contrasena. La llave de
firma ed25519 NO viaja aca -- vive en `RepositorioLlaves`
(`puertos/repositorios.py`), un repositorio aparte, porque el ciclo de vida
de una llave de firma (rotarla, revocarla) no tiene por que acoplarse al
ciclo de vida de un usuario, y porque `EmitirMandatoUseCase` solo necesita
resolver un `Firmante` por `titular_id` (`puertos/firma.py:
SelectorDeFirmante`), nunca un `Usuario` completo.

`contrasena_hash` SI viaja aca, igual que `Mandato.firma` (`dominio/
mandato/modelo.py`) viaja como `str` opaco dentro de ese dataclass: en los
dos casos el dominio guarda el ARTEFACTO criptografico ya calculado, nunca
la logica para producirlo o verificarlo -- eso vive en un puerto
(`puertos/autenticacion.py:HasherDeContrasenas`) y su adaptador
(`adaptadores/sistema/hasher_pbkdf2.py`). Este modulo no debe importar
`hashlib` ni ninguna libreria de criptografia.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..commons.identidad import TitularId


@dataclass(frozen=True)
class Usuario:
    titular_id: TitularId
    nombre_usuario: str
    contrasena_hash: str
    creado_en: datetime
