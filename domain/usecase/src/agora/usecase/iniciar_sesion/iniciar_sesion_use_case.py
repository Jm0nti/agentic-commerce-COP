"""Verificar usuario y contrasena. Ver `registrar_usuario` para el contexto
de la autenticacion multi-usuario (y por que cerrar sesion no es un caso de uso)."""

from __future__ import annotations

from ...model.commons.errores import CredencialesInvalidas
from ...model.usuario.modelo import Usuario
from ...model.usuario.gateways.autenticacion import HasherDeContrasenas
from ...model.usuario.gateways.repositorios import RepositorioUsuarios


class IniciarSesionUseCase:
    """Verifica nombre de usuario + contrasena. `CredencialesInvalidas` es
    a proposito EL MISMO error tanto si el nombre de usuario no existe como
    si la contrasena no coincide -- distinguirlos permitiria enumerar
    nombres de usuario validos probando contra este caso de uso."""

    def __init__(self, usuarios: RepositorioUsuarios, hasher: HasherDeContrasenas) -> None:
        self._usuarios = usuarios
        self._hasher = hasher

    def __call__(self, nombre_usuario: str, contrasena: str) -> Usuario:
        usuario = self._usuarios.buscar_por_nombre_usuario(nombre_usuario)
        if usuario is None or not self._hasher.verifica(contrasena, usuario.contrasena_hash):
            raise CredencialesInvalidas("nombre de usuario o contrasena incorrectos")
        return usuario
