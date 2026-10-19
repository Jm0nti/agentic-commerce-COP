#!/usr/bin/env python3
"""Arranca la API HTTP + frontend de una sola pagina (etapa 7): el chat con
el agente y la firma/confirmacion humana en la misma pestana, en vez de dos
terminales (`chat` + `firmar`/`retomar` de `entry_points/cli/`).

Composition root de este punto de entrada especifico: lee `os.environ`, arma
el `Contenedor` con `agora.composicion.contenedor.construir`, arma el
`Agente` con `agora.composicion.agente.construir_agente`, y le pasa los dos
a `agora.entradas.api.app.crear_app`. Vive fuera de `agora/`, igual que
`python -m agora webhook` -- `entry_points/api_rest/app.py` se queda como
una factoria pura precisamente para que este sea el unico lugar que lee
variables de entorno y llama a `uvicorn.run`.

    python -m agora api

Necesita `DEEPSEEK_API_KEY` (`docs/variables-de-entorno.md`) para que
`POST /sesiones` funcione -- sin ella el servidor igual levanta (`/salud`
responde, la pagina se sirve), pero `POST /sesiones` devuelve 503, mismo
criterio que `entry_points/cli/cli.py:cmd_chat`.

Con `AGORA_PERSISTENCIA=sqlite` (recomendado: sin esto, firmar la propuesta
desde el popup y despues reiniciar el proceso pierde la propuesta) el mandato y el estado de cada
intencion sobreviven un reinicio del servidor; la `Conversacion` de cada
sesion de chat NO sobrevive (es en memoria a proposito, ver
`entry_points/api_rest/sesiones.py`), asi que reiniciar el proceso mid-charla obliga
a recargar la pagina para pedir una sesion nueva.

Variables propias de este script (ademas de las de `app_service/config/
configuracion.py`):

    AGORA_API_HOST   default 0.0.0.0
    AGORA_API_PORT   default 8002 -- distinto del 8001 de
                     `python -m agora webhook` por si ambos
                     conviven durante una demo.
"""

from __future__ import annotations

import os

import uvicorn

from agora.app_service.config.agente import construir_agente
from agora.app_service.config.configuracion import desde_el_entorno
from agora.app_service.config.contenedor import construir
from agora.entry_points.api_rest.app import crear_app
from agora.entry_points.api_rest.sondeo_pagos import SondeoDePagosPendientes


def main(argv: list[str] | None = None) -> int:
    config = desde_el_entorno()
    contenedor = construir(config)
    agente = construir_agente(contenedor)

    if agente is None:
        print(
            "AVISO: no hay DEEPSEEK_API_KEY configurada -- el servidor "
            "levanta igual, pero POST /sesiones va a devolver 503 (mismo "
            "criterio que 'chat' en entradas/cli/). Ver "
            "docs/variables-de-entorno.md."
        )
    if config.persistencia != "sqlite":
        print(
            "AVISO: AGORA_PERSISTENCIA no es 'sqlite' -- una propuesta que "
            "el agente arme sigue firmandose desde el popup, pero no "
            "sobrevive un reinicio de este proceso (ver el docstring de "
            "este script)."
        )

    app = crear_app(agente, contenedor)

    if app.state.sesiones is not None:
        # Etapa 9: sin esto, un pago real que Wompi liquida despues de que
        # el agente ya contesto "quedo pendiente" nunca se lo cuenta a la
        # persona -- alguien tendria que volver a escribirle. Ver el
        # docstring de `entry_points/api_rest/sondeo_pagos.py`.
        sondeo = SondeoDePagosPendientes(app.state.sesiones, contenedor.consultar_estado)
        sondeo.iniciar()

    host = os.environ.get("AGORA_API_HOST", "0.0.0.0")
    port = int(os.environ.get("AGORA_API_PORT", "8002"))
    uvicorn.run(app, host=host, port=port)
    return 0

