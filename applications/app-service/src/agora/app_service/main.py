"""El unico arranque de agora: `python -m agora <perfil> [argumentos]`.

Es el `MainApplication` del scaffold de Bancolombia. Cada perfil arma lo que
necesita desde `config/` y le pasa sus dependencias ya resueltas al entry
point que corresponde:

    python -m agora api                 chat web + firma (entry-points/api-rest)
    python -m agora webhook             receptor de eventos de Wompi (entry-points/webhook-wompi)
    python -m agora cli <comando>       la linea de comandos (entry-points/cli)
    python -m agora crear-usuario ...   crea un usuario con su llave de firma
    python -m agora generar-catalogo .. genera el catalogo simulado con DeepSeek

`api` y `webhook` siguen siendo procesos separados (cada uno en su puerto,
el webhook detras de ngrok): lo que se unifica es el codigo de arranque.
"""

from __future__ import annotations

import sys


def _cli(argv: list[str]) -> int:
    from agora.entry_points.cli.cli import main as cli

    from .config.agente import construir_agente
    from .config.configuracion import ConfiguracionInvalida, desde_el_entorno
    from .config.contenedor import construir

    try:
        contenedor = construir(desde_el_entorno())
    except ConfiguracionInvalida as exc:
        print(f"[x] configuracion invalida: {exc}")
        return 1
    return cli(argv, contenedor, lambda: construir_agente(contenedor))


def _modulo(nombre: str):
    """Cada perfil se importa recien cuando se pide: la CLI no tiene por que
    cargar uvicorn, ni `api` el cliente de DeepSeek del generador."""
    def correr(argv: list[str]) -> int:
        from importlib import import_module

        return import_module(f"agora.app_service.{nombre}").main(argv)
    return correr


PERFILES = {
    "api": _modulo("servir_api"),
    "webhook": _modulo("servir_webhook_wompi"),
    "cli": _cli,
    "crear-usuario": _modulo("crear_usuario"),
    "generar-catalogo": _modulo("generar_catalogo_semilla"),
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in PERFILES:
        print(__doc__)
        return 2
    return PERFILES[argv[0]](argv[1:])
