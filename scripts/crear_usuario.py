#!/usr/bin/env python3
"""Crea un usuario nuevo -- multi-usuario (4 de septiembre de 2026): el
UNICO camino de produccion para dar de alta a alguien. No hay ruta HTTP de
auto-registro (`entradas/api/app.py` solo expone `/auth/iniciar-sesion` y
`/auth/cerrar-sesion` sobre usuarios que ya existen): crear un usuario
siempre pasa por alguien con acceso a la terminal del servidor.

Este script solo lee el `.env`, arma el `Contenedor` (`composicion/
contenedor.py:construir`) y le delega TODO el trabajo a `contenedor.
registrar_usuario` (`aplicacion/autenticacion.py:RegistrarUsuarioUseCase`): hashea
la contrasena, genera un par de llaves ed25519 nuevo, y guarda las dos
cosas (tabla `usuario`, tabla `llave_firma`) segun `AGORA_PERSISTENCIA` --
mismo patron de composition root que `scripts/servir_api.py`.

    python scripts/crear_usuario.py --nombre-usuario juan --contrasena ****
    python scripts/crear_usuario.py --nombre-usuario juan --contrasena **** --titular tit_juan

Sin `--titular`, se genera uno nuevo (prefijo `tit_`, igual que cualquier
otro `TitularId` -- `dominio/comun/identidad.py`). Con `--titular`, se usa
ese id exacto -- util para dar de alta un usuario sobre un `titular_id` que
ya tiene medios de pago o mandatos de antes de que existiera el login
(migrando una demo vieja, por ejemplo).

IMPORTANTE: correrlo con `AGORA_PERSISTENCIA=sqlite` (o con la variable ya
puesta en el `.env`) -- con `memoria` (el default sin `.env`) el usuario y
su llave desaparecen en cuanto el proceso de este script termina, y
`scripts/servir_api.py`/`entradas/cli/` nunca los verian.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO = Path(__file__).resolve().parents[1]  # solo para sys.path
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agora.composicion.configuracion import (  # noqa: E402
    RAIZ_REPO,
    ConfiguracionInvalida,
    leer_configuracion,
)
from agora.composicion.contenedor import construir  # noqa: E402
from agora.model.commons.errores import NombreDeUsuarioYaExiste


def _parsear_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="crear_usuario", description="Crea un usuario nuevo con su propia llave de firma",
    )
    p.add_argument("--nombre-usuario", required=True, help="con que nombre inicia sesion")
    p.add_argument(
        "--contrasena", default=None,
        help="si se omite, se pide de forma interactiva (no queda en el historial de la terminal)",
    )
    p.add_argument(
        "--titular", default=None,
        help="titular_id a usar (default: se genera uno nuevo, prefijo 'tit_')",
    )
    return p.parse_args()


def main() -> int:
    args = _parsear_args()
    load_dotenv(RAIZ_REPO / ".env")
    try:
        config = leer_configuracion(os.environ)
    except ConfiguracionInvalida as exc:
        print(f"[x] configuracion invalida: {exc}")
        return 1

    contrasena = args.contrasena or getpass.getpass("Contrasena: ")
    if not contrasena:
        print("[x] la contrasena no puede estar vacia")
        return 1

    contenedor = construir(config)
    try:
        usuario = contenedor.registrar_usuario(args.nombre_usuario, contrasena, args.titular)
    except NombreDeUsuarioYaExiste as exc:
        print(f"[x] {exc.mensaje}")
        return 1

    print(f"Usuario '{usuario.nombre_usuario}' creado.")
    print(f"  titular_id   {usuario.titular_id}")
    print(
        "\n  Ya puede iniciar sesion en la web, y usar la CLI pasando este "
        f"titular_id:\n\n    python -m agora.entradas.cli fuentes {usuario.titular_id}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
