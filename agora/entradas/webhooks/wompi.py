"""Receptor HTTP vivo del webhook de la pasarela (etapa 4).

Pese al nombre del modulo -- "wompi" porque es la ruta que ya esta
configurada en el dashboard de Wompi, `/pagos/wompi/transacciones`, la misma
que usaba `boveda/eventos.py` -- `crear_app` no sabe que pasarela hay del
otro lado. Recibe un `ConciliarEvento` ya armado (que a su vez ya trae la
pasarela que corresponda, wompi o simulada) y solo traduce HTTP hacia
adentro y hacia afuera. Nada de `os.environ`, nada de construir el
`Contenedor`: eso es trabajo del composition root de este punto de entrada,
`scripts/servir_webhook_wompi.py`. Separar las dos cosas es lo que permite
probar esta app con `TestClient` sin ninguna variable de entorno (ver
`tests/test_webhook_wompi.py`).

WOMPI ESPERA UN 200, SIEMPRE
-----------------------------
Mismo argumento que `boveda/eventos.py` y que el docstring de
`ConciliarEvento`: un checksum invalido, un evento que no es un cobro de
esta app, o una reserva que ya no existe no son fallos del receptor -- son
desenlaces normales de un webhook. Reintentar no arregla ninguno, y devolver
algo distinto de 200 solo le da a un atacante una forma barata de hacer que
Wompi reintente sin limite. `ConciliarEvento.__call__` ya nunca levanta, asi
que esta ruta no necesita ni un `try/except`: siempre llega a un `Response`
200.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ...aplicacion.conciliar_evento import ConciliarEvento


def crear_app(conciliar_evento: ConciliarEvento) -> FastAPI:
    """Factoria pura: sin efectos de importacion, sin leer variables de
    entorno. `conciliar_evento` ya viene armado por quien llame (el
    `Contenedor`, o un doble de pruebas)."""

    app = FastAPI(title="Receptor de eventos (agora)")

    @app.get("/salud")
    def salud() -> dict[str, Any]:
        return {"ok": True}

    @app.post("/pagos/wompi/transacciones")
    async def recibir(request: Request) -> JSONResponse:
        cuerpo = await request.body()
        cabeceras = dict(request.headers)
        resultado = conciliar_evento(cuerpo, cabeceras)

        # Visibilidad minima en consola, igual que boveda/eventos.py -- este
        # proceso normalmente corre desatendido detras de ngrok/cloudflared.
        marca = "ok " if resultado.procesado else "NO "
        print(f"[{marca}] {resultado.motivo} intencion={resultado.intencion_id}")

        # El cuerpo de la respuesta es solo para quien mire los logs o pruebe
        # con curl a mano -- Wompi unicamente le presta atencion al 200.
        return JSONResponse(
            status_code=200,
            content={"procesado": resultado.procesado, "motivo": resultado.motivo},
        )

    return app
