#!/usr/bin/env python3
"""Arranca el receptor HTTP vivo del webhook (etapa 4).

Composition root de este punto de entrada especifico: lee `os.environ`, arma
el `Contenedor` con `agora.composicion.contenedor.construir` y le pasa su
`conciliar_evento` a `agora.entradas.webhooks.wompi.crear_app`. Vive fuera de
`agora/`, igual que `scripts/migrar_fuentes_a_sqlite.py` -- `entradas/
webhooks/wompi.py` se queda como una factoria pura precisamente para que
este sea el unico lugar que lee variables de entorno y llama a `uvicorn.run`.

    python scripts/servir_webhook_wompi.py

Con AGORA_PASARELA=wompi (`composicion/configuracion.py`) el checksum se
verifica de verdad contra WOMPI_EVENTS_SECRET -- exponer esto con
ngrok/cloudflared y pegar esa URL en el dashboard de Wompi, seccion Eventos,
reemplaza a `boveda/eventos.py`. Con AGORA_PASARELA=simulada (el default) el
receptor igual queda arriba y sirve para una demo: `AdaptadorSimulado.
validar_evento` no verifica nada (a proposito, ver su docstring), asi que
cualquier cuerpo con la forma correcta se acepta -- util para mostrar el
flujo completo posteando a mano el resultado de `evento_de(...)`, pero nunca
para produccion.

Variables propias de este script (ademas de las de `composicion/
configuracion.py`):

    AGORA_WEBHOOK_HOST   default 0.0.0.0
    AGORA_WEBHOOK_PORT   default 8001 -- distinto del 8000 de
                         `boveda/eventos.py` por si ambos conviven durante
                         la migracion.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent
if str(RAIZ_REPO) not in sys.path:
    # Para poder correr `python scripts/servir_webhook_wompi.py` directo,
    # sin depender de que el paquete este instalado o de que se invoque con
    # `python -m` (mismo patron que `scripts/migrar_fuentes_a_sqlite.py`).
    sys.path.insert(0, str(RAIZ_REPO))

import uvicorn  # noqa: E402

from agora.composicion.configuracion import leer_configuracion  # noqa: E402
from agora.composicion.contenedor import construir  # noqa: E402
from agora.entradas.webhooks.wompi import crear_app  # noqa: E402


def main() -> int:
    config = leer_configuracion(os.environ)
    contenedor = construir(config)
    app = crear_app(contenedor.conciliar_evento)

    if config.pasarela != "wompi":
        print(
            f"AVISO: AGORA_PASARELA='{config.pasarela}' -- el checksum NO se "
            "verifica contra un secreto real (ver docstring de este script). "
            "Sirve para demo, no para produccion."
        )

    host = os.environ.get("AGORA_WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("AGORA_WEBHOOK_PORT", "8001"))
    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
