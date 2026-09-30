#!/usr/bin/env python3
"""Arranca la API HTTP + frontend de una sola pagina (etapa 7): el chat con
el agente y la firma/confirmacion humana en la misma pestana, en vez de dos
terminales (`chat` + `firmar`/`retomar` de `entradas/cli/`).

Composition root de este punto de entrada especifico: lee `os.environ`, arma
el `Contenedor` con `agora.composicion.contenedor.construir`, arma el
`Agente` con `agora.composicion.agente.construir_agente`, y le pasa los dos
a `agora.entradas.api.app.crear_app`. Vive fuera de `agora/`, igual que
`scripts/servir_webhook_wompi.py` -- `entradas/api/app.py` se queda como
una factoria pura precisamente para que este sea el unico lugar que lee
variables de entorno y llama a `uvicorn.run`.

    python scripts/servir_api.py

Necesita `DEEPSEEK_API_KEY` (`docs/variables-de-entorno.md`) para que
`POST /sesiones` funcione -- sin ella el servidor igual levanta (`/salud`
responde, la pagina se sirve), pero `POST /sesiones` devuelve 503, mismo
criterio que `entradas/cli/__main__.py:cmd_chat`.

Con `AGORA_PERSISTENCIA=sqlite` (recomendado: sin esto, firmar la propuesta
desde el popup y despues reiniciar el proceso pierde la propuesta -- ver
`docs/etapa-6-conectar-chat-y-firma.md`) el mandato y el estado de cada
intencion sobreviven un reinicio del servidor; la `Conversacion` de cada
sesion de chat NO sobrevive (es en memoria a proposito, ver
`entradas/api/sesiones.py`), asi que reiniciar el proceso mid-charla obliga
a recargar la pagina para pedir una sesion nueva.

Variables propias de este script (ademas de las de `composicion/
configuracion.py`):

    AGORA_API_HOST   default 0.0.0.0
    AGORA_API_PORT   default 8002 -- distinto del 8001 de
                     `scripts/servir_webhook_wompi.py` por si ambos
                     conviven durante una demo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]  # solo para sys.path
if str(_REPO) not in sys.path:
    # Para poder correr `python scripts/servir_api.py` directo, sin
    # depender de que el paquete este instalado o de que se invoque con
    # `python -m` (mismo patron que `scripts/servir_webhook_wompi.py`).
    sys.path.insert(0, str(_REPO))

import uvicorn  # noqa: E402

from agora.composicion.agente import construir_agente  # noqa: E402
from agora.composicion.configuracion import RAIZ_REPO, leer_configuracion  # noqa: E402
from agora.composicion.contenedor import construir  # noqa: E402
from agora.entradas.api.app import crear_app  # noqa: E402
from agora.entradas.api.sondeo_pagos import SondeoDePagosPendientes  # noqa: E402
from utilidades.env import cargar_env_desde_archivo  # noqa: E402


def main() -> int:
    cargar_env_desde_archivo(RAIZ_REPO / ".env")
    config = leer_configuracion(os.environ)
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
        # docstring de `agora/entradas/api/sondeo_pagos.py`.
        sondeo = SondeoDePagosPendientes(app.state.sesiones, contenedor.consultar_estado)
        sondeo.iniciar()

    host = os.environ.get("AGORA_API_HOST", "0.0.0.0")
    port = int(os.environ.get("AGORA_API_PORT", "8002"))
    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
