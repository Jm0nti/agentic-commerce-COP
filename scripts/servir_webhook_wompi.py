#!/usr/bin/env python3
"""Arranca el receptor HTTP vivo del webhook (etapa 4).

Composition root de este punto de entrada especifico: lee `os.environ`, arma
el `Contenedor` con `agora.composicion.contenedor.construir` y le pasa su
`conciliar_evento` a `agora.entradas.webhooks.wompi.crear_app`. Vive fuera de
`agora/` -- `entradas/webhooks/wompi.py` se queda como una factoria pura
precisamente para que este sea el unico lugar que lee variables de entorno y
llama a `uvicorn.run`.

    python scripts/servir_webhook_wompi.py

MULTI-COMERCIO (1 de septiembre de 2026)
-----------------------------------------
La ruta ahora lleva el comercio en el path:
`/pagos/wompi/transacciones/{comercio_id}`. Con AGORA_PASARELA=wompi
(`composicion/configuracion.py`), cada comercio de `AGORA_WOMPI_COMERCIOS`
(default `agora_datos/secretos/comercios_wompi.json`) valida el checksum
contra SU PROPIO `events_secret` -- exponer este proceso con ngrok/
cloudflared UNA sola vez y, en el dashboard de Wompi de CADA comercio real
(seccion Eventos), pegar esa misma URL base seguida de `/pagos/wompi/
transacciones/<ese comercio_id>` reemplaza a `boveda/eventos.py`. Un solo
tunel, un solo puerto, una ruta por comercio -- ver `docs/viabilidad-multi-
comercio-wompi.md`.

Con AGORA_PASARELA=simulada (el default) el receptor igual queda arriba y
sirve para una demo: `AdaptadorSimulado.validar_evento` no verifica nada (a
proposito, ver su docstring), asi que cualquier cuerpo con la forma correcta
se acepta en cualquier `comercio_id` -- util para mostrar el flujo completo
posteando a mano el resultado de `evento_de(...)`, pero nunca para
produccion.

Variables propias de este script (ademas de las de `composicion/
configuracion.py`):

    AGORA_WEBHOOK_HOST   default 0.0.0.0
    AGORA_WEBHOOK_PORT   default 8001 -- distinto del 8000 de
                         `boveda/eventos.py` por si ambos conviven durante
                         la migracion. El MISMO puerto sirve a todos los
                         comercios configurados -- no hay un puerto por
                         comercio.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent
if str(RAIZ_REPO) not in sys.path:
    # Para poder correr `python scripts/servir_webhook_wompi.py` directo,
    # sin depender de que el paquete este instalado o de que se invoque con
    # `python -m`.
    sys.path.insert(0, str(RAIZ_REPO))

import uvicorn  # noqa: E402

from agora.composicion.configuracion import leer_configuracion  # noqa: E402
from agora.composicion.contenedor import construir  # noqa: E402
from agora.entradas.webhooks.wompi import crear_app  # noqa: E402
from utilidades.env import cargar_env_desde_archivo  # noqa: E402


def main() -> int:
    cargar_env_desde_archivo(RAIZ_REPO / ".env")
    config = leer_configuracion(os.environ)
    contenedor = construir(config)
    app = crear_app(contenedor.conciliar_evento)

    if config.pasarela != "wompi":
        print(
            f"AVISO: AGORA_PASARELA='{config.pasarela}' -- el checksum NO se "
            "verifica contra un secreto real (ver docstring de este script). "
            "Sirve para demo, no para produccion."
        )
    else:
        print(f"Comercios con credenciales de Wompi configuradas: {', '.join(sorted(config.wompi))}")
        print(
            "Registre en el dashboard de Wompi de CADA comercio (seccion "
            "Eventos) su propia URL: <su URL publica>/pagos/wompi/"
            "transacciones/<comercio_id>"
        )

    host = os.environ.get("AGORA_WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("AGORA_WEBHOOK_PORT", "8001"))
    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
