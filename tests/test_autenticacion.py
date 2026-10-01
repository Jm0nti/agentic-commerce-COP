"""Multi-usuario (4 de septiembre de 2026): el hasher de contrasenas, los
casos de uso de `aplicacion/autenticacion.py`, `RegistroDeFirmantes`
(`SelectorDeFirmante`), los repositorios de usuarios/llaves (memoria y
sqlite) y las sesiones de login de `entradas/api/`.

`tests/test_composicion.py`, `test_composicion_agente.py`, `test_cli.py` y
`test_api_app.py` ya ejercitan buena parte de esto de punta a punta (via
`Contenedor.registrar_usuario`/`iniciar_sesion`) -- este archivo agrega la
cobertura unitaria de cada pieza sola, con dobles de prueba en vez de un
`Contenedor` completo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from agora.adaptadores.persistencia.memoria import (
    RepositorioLlavesEnMemoria,
    RepositorioUsuariosEnMemoria,
)
from agora.adaptadores.persistencia.sqlite import (
    RepositorioLlavesSQLite,
    RepositorioUsuariosSQLite,
)
from agora.adaptadores.sistema import GeneradorIdsUuid, HasherPBKDF2, RegistroDeFirmantes
from agora.adaptadores.sistema.firma_ed25519 import generar_par_ed25519
from agora.usecase.iniciar_sesion.iniciar_sesion_use_case import IniciarSesionUseCase
from agora.usecase.registrar_usuario.registrar_usuario_use_case import RegistrarUsuarioUseCase
from agora.model.commons.errores import (
    CredencialesInvalidas,
    NombreDeUsuarioYaExiste,
    SinLlaveDeFirma,
)
from agora.model.usuario.modelo import Usuario
from agora.entradas.api.autenticacion import AlmacenDeSesionesWeb
from agora.model.commons.errores import SesionInvalida

AHORA = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


@dataclass
class _RelojFijo:
    cuando: datetime

    def ahora(self) -> datetime:
        return self.cuando


class _GeneradorDeLlavesFalso:
    """Devuelve siempre el MISMO par -- alcanza para probar que
    `RegistrarUsuarioUseCase` lo guarda donde corresponde, sin generar criptografia
    de verdad en cada prueba."""

    def __init__(self) -> None:
        self.llamadas = 0

    def generar(self) -> tuple[bytes, bytes]:
        self.llamadas += 1
        return b"llave-privada-falsa-32-bytes--x", b"llave-publica-falsa-32-bytes--x"


# -- HasherPBKDF2 ------------------------------------------------------------ #


def test_hashear_y_verificar_la_misma_contrasena():
    hasher = HasherPBKDF2(iteraciones=1_000)
    hashed = hasher.hashear("clave-correcta")
    assert hasher.verifica("clave-correcta", hashed)


def test_verificar_una_contrasena_distinta_falla():
    hasher = HasherPBKDF2(iteraciones=1_000)
    hashed = hasher.hashear("clave-correcta")
    assert not hasher.verifica("otra-clave", hashed)


def test_dos_hashes_de_la_misma_contrasena_son_distintos():
    """La sal es aleatoria por contrasena -- dos usuarios con la misma
    clave no deberian tener el mismo hash guardado."""
    hasher = HasherPBKDF2(iteraciones=1_000)
    assert hasher.hashear("clave-correcta") != hasher.hashear("clave-correcta")


def test_verificar_contra_un_hash_con_formato_invalido_no_revienta():
    hasher = HasherPBKDF2(iteraciones=1_000)
    assert not hasher.verifica("cualquier-cosa", "esto-no-es-un-hash-valido")


# -- RegistrarUsuarioUseCase / IniciarSesionUseCase ----------------------------------------- #


def _armar_autenticacion():
    usuarios = RepositorioUsuariosEnMemoria()
    llaves = RepositorioLlavesEnMemoria()
    hasher = HasherPBKDF2(iteraciones=1_000)
    generador_llaves = _GeneradorDeLlavesFalso()
    ids = GeneradorIdsUuid()
    reloj = _RelojFijo(AHORA)
    registrar = RegistrarUsuarioUseCase(
        usuarios=usuarios, llaves=llaves, hasher=hasher,
        generador_llaves=generador_llaves, ids=ids, reloj=reloj,
    )
    iniciar = IniciarSesionUseCase(usuarios=usuarios, hasher=hasher)
    return registrar, iniciar, usuarios, llaves, generador_llaves


def test_registrar_usuario_guarda_el_usuario_y_su_llave():
    registrar, _, usuarios, llaves, _ = _armar_autenticacion()

    usuario = registrar("juan", "clave-secreta", titular_id="tit_juan")

    assert usuario.titular_id == "tit_juan"
    assert usuario.nombre_usuario == "juan"
    assert usuario.creado_en == AHORA
    assert usuarios.buscar_por_nombre_usuario("juan") == usuario
    assert usuarios.buscar_por_titular("tit_juan") == usuario
    assert llaves.llave_privada_de("tit_juan") == b"llave-privada-falsa-32-bytes--x"


def test_registrar_usuario_sin_titular_genera_uno_con_prefijo_tit():
    registrar, _, _, _, _ = _armar_autenticacion()

    usuario = registrar("juan", "clave-secreta")

    assert usuario.titular_id.startswith("tit_")


def test_registrar_usuario_con_nombre_repetido_levanta():
    registrar, _, _, _, generador_llaves = _armar_autenticacion()
    registrar("juan", "clave-secreta", titular_id="tit_1")

    with pytest.raises(NombreDeUsuarioYaExiste):
        registrar("juan", "otra-clave", titular_id="tit_2")

    # Nunca se llego a generar una segunda llave -- se verifica el nombre
    # ANTES de tocar cualquier cosa de criptografia (ver el docstring de
    # `RegistrarUsuarioUseCase`).
    assert generador_llaves.llamadas == 1


def test_iniciar_sesion_con_credenciales_correctas():
    registrar, iniciar, _, _, _ = _armar_autenticacion()
    registrar("juan", "clave-secreta", titular_id="tit_juan")

    usuario = iniciar("juan", "clave-secreta")

    assert usuario.titular_id == "tit_juan"


def test_iniciar_sesion_con_contrasena_incorrecta_levanta():
    registrar, iniciar, _, _, _ = _armar_autenticacion()
    registrar("juan", "clave-secreta", titular_id="tit_juan")

    with pytest.raises(CredencialesInvalidas):
        iniciar("juan", "clave-equivocada")


def test_iniciar_sesion_con_usuario_inexistente_levanta_el_mismo_error():
    """Mismo error que una contrasena incorrecta -- ver el docstring de
    `CredencialesInvalidas`: no hay que poder distinguir "no existe" de
    "contrasena mala" enumerando nombres de usuario."""
    _, iniciar, _, _, _ = _armar_autenticacion()

    with pytest.raises(CredencialesInvalidas):
        iniciar("nadie", "cualquier-cosa")


# -- RegistroDeFirmantes ------------------------------------------------------ #


def test_registro_de_firmantes_resuelve_la_llave_de_un_titular_con_llave():
    llaves = RepositorioLlavesEnMemoria()
    privada, publica = generar_par_ed25519()
    llaves.guardar("tit_1", privada, publica)
    selector = RegistroDeFirmantes(llaves)

    firmante = selector.para("tit_1")

    assert firmante.llave_publica() == publica


def test_registro_de_firmantes_sin_llave_levanta_sin_generar_una():
    llaves = RepositorioLlavesEnMemoria()
    selector = RegistroDeFirmantes(llaves)

    with pytest.raises(SinLlaveDeFirma):
        selector.para("tit_sin_usuario")

    # Nunca genera una de respaldo -- confirma que no quedo nada guardado.
    assert llaves.llave_privada_de("tit_sin_usuario") is None


# -- RepositorioUsuarios / RepositorioLlaves: memoria y sqlite, mismo contrato -- #


@pytest.fixture(params=["memoria", "sqlite"])
def _repos(request, tmp_path):
    if request.param == "memoria":
        return RepositorioUsuariosEnMemoria(), RepositorioLlavesEnMemoria()
    ruta = tmp_path / "agora.db"
    return RepositorioUsuariosSQLite(ruta), RepositorioLlavesSQLite(ruta)


def test_repositorio_usuarios_guarda_y_busca_por_nombre_y_por_titular(_repos):
    usuarios, _ = _repos
    usuario = Usuario(
        titular_id="tit_1", nombre_usuario="juan",
        contrasena_hash="pbkdf2_sha256$1$aa$bb", creado_en=AHORA,
    )

    usuarios.guardar(usuario)

    assert usuarios.buscar_por_nombre_usuario("juan") == usuario
    assert usuarios.buscar_por_titular("tit_1") == usuario


def test_repositorio_usuarios_nombre_o_titular_desconocido_devuelve_none(_repos):
    usuarios, _ = _repos
    assert usuarios.buscar_por_nombre_usuario("nadie") is None
    assert usuarios.buscar_por_titular("tit_nadie") is None


def test_repositorio_llaves_guarda_y_devuelve_la_privada(_repos):
    _, llaves = _repos
    llaves.guardar("tit_1", b"privada-de-prueba", b"publica-de-prueba")

    assert llaves.llave_privada_de("tit_1") == b"privada-de-prueba"


def test_repositorio_llaves_titular_desconocido_devuelve_none(_repos):
    _, llaves = _repos
    assert llaves.llave_privada_de("tit_nadie") is None


# -- AlmacenDeSesionesWeb (entradas/api/autenticacion.py) --------------------- #


def _usuario_de_prueba() -> Usuario:
    return Usuario(
        titular_id="tit_1", nombre_usuario="juan",
        contrasena_hash="pbkdf2_sha256$1$aa$bb", creado_en=AHORA,
    )


def test_almacen_de_sesiones_web_crea_y_resuelve_un_token():
    almacen = AlmacenDeSesionesWeb(_RelojFijo(AHORA))
    token = almacen.crear(_usuario_de_prueba())

    titular_id, nombre_usuario = almacen.titular_de(token)

    assert titular_id == "tit_1"
    assert nombre_usuario == "juan"


def test_almacen_de_sesiones_web_token_desconocido_levanta_sesion_invalida():
    almacen = AlmacenDeSesionesWeb(_RelojFijo(AHORA))
    with pytest.raises(SesionInvalida):
        almacen.titular_de("token-que-no-existe")


def test_almacen_de_sesiones_web_token_expirado_levanta_sesion_invalida():
    reloj = _RelojFijo(AHORA)
    almacen = AlmacenDeSesionesWeb(reloj, duracion=timedelta(hours=1))
    token = almacen.crear(_usuario_de_prueba())

    reloj.cuando = AHORA + timedelta(hours=2)

    with pytest.raises(SesionInvalida):
        almacen.titular_de(token)


def test_almacen_de_sesiones_web_cerrar_invalida_el_token():
    almacen = AlmacenDeSesionesWeb(_RelojFijo(AHORA))
    token = almacen.crear(_usuario_de_prueba())

    almacen.cerrar(token)

    with pytest.raises(SesionInvalida):
        almacen.titular_de(token)
