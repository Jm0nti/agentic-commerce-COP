"""Autenticacion: registrar un usuario nuevo (con su propia llave de
firma) e iniciar sesion. Cerrar sesion NO esta aca -- ver mas abajo.

POR QUE REGISTRAR UN USUARIO TAMBIEN LE CREA SU LLAVE DE FIRMA
--------------------------------------------------------------------
Antes de esta version (multi-usuario, 4 de septiembre de 2026),
`composicion/contenedor.py` armaba UNA sola llave de firma para todo el
proceso (`cargar_o_generar_firmante`), sin importar que titular firmara --
un mandato de cualquiera se firmaba con la MISMA llave que un mandato de
cualquier otro, indistinguible desde la criptografia sola. `RegistrarUsuarioUseCase`
es donde eso se corrige: cada usuario nuevo nace con su propio par ed25519
(`GeneradorDeLlaves`), guardado junto con el (`RepositorioLlaves`) para que
`SelectorDeFirmante.para(titular_id)` (`adaptadores/sistema/
registro_firmantes.py:RegistroDeFirmantes`) pueda resolver el `Firmante`
correcto al momento de emitir un mandato -- ver `aplicacion/
emitir_mandato.py`.

`scripts/crear_usuario.py` es el UNICO lugar que llama a `RegistrarUsuarioUseCase`
en produccion: no hay ruta HTTP de auto-registro -- el usuario fue
explicito en que los usuarios se crean por script, asi que un usuario
nuevo siempre pasa por alguien con acceso a la terminal del servidor,
nunca por un formulario publico.

POR QUE `CerrarSesion` NO ES UN CASO DE USO
------------------------------------------------
`IniciarSesionUseCase` tiene logica real: verificar una contrasena contra un hash
guardado es una regla que vale la pena probar sola, sin FastAPI de por
medio. Cerrar sesion es borrar un token de una cookie de un almacen en
memoria -- cero logica de dominio, un detalle de COMO llega la sesion por
HTTP. Envolverlo en una clase de `aplicacion/` solo para simetria seria
ceremonia: vive directo en `entradas/api/autenticacion.py`, igual que
`entradas/api/sesiones.py:AlmacenDeSesiones` nunca tuvo un caso de uso
`CerrarSesionDeChat` para borrar una `Conversacion`.
"""

from __future__ import annotations

from ...model.commons.errores import NombreDeUsuarioYaExiste
from ...model.usuario.modelo import Usuario
from ...model.usuario.gateways.autenticacion import HasherDeContrasenas
from ...model.mandato.gateways.firma import GeneradorDeLlaves
from ...model.usuario.gateways.repositorios import RepositorioLlaves, RepositorioUsuarios
from ...model.commons.gateways.sistema import GeneradorIds, Reloj


class RegistrarUsuarioUseCase:
    def __init__(
        self,
        usuarios: RepositorioUsuarios,
        llaves: RepositorioLlaves,
        hasher: HasherDeContrasenas,
        generador_llaves: GeneradorDeLlaves,
        ids: GeneradorIds,
        reloj: Reloj,
    ) -> None:
        self._usuarios = usuarios
        self._llaves = llaves
        self._hasher = hasher
        self._generador_llaves = generador_llaves
        self._ids = ids
        self._reloj = reloj

    def __call__(self, nombre_usuario: str, contrasena: str, titular_id: str | None = None) -> Usuario:
        if self._usuarios.buscar_por_nombre_usuario(nombre_usuario) is not None:
            raise NombreDeUsuarioYaExiste(
                f"ya existe un usuario con el nombre de usuario '{nombre_usuario}'"
            )
        titular = titular_id or self._ids.nuevo("tit")
        usuario = Usuario(
            titular_id=titular,
            nombre_usuario=nombre_usuario,
            contrasena_hash=self._hasher.hashear(contrasena),
            creado_en=self._reloj.ahora(),
        )
        self._usuarios.guardar(usuario)
        # La llave se genera DESPUES de guardar el usuario: si algo fallara
        # generando o guardando la llave, es preferible un usuario sin
        # llave (visible, `SinLlaveDeFirma` lo dice claro en el primer
        # intento de firmar) a una llave huerfana sin usuario dueño.
        llave_privada, llave_publica = self._generador_llaves.generar()
        self._llaves.guardar(titular, llave_privada, llave_publica)
        return usuario
