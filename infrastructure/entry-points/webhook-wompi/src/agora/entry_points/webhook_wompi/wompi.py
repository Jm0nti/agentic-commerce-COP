"""Receptor HTTP vivo del webhook de la pasarela (etapa 4).

MULTI-COMERCIO (1 de septiembre de 2026)
-----------------------------------------
Cada comercio real tiene su propio `WOMPI_EVENTS_SECRET`, y lo configura en
SU PROPIO dashboard de Wompi (Desarrolladores > Eventos), apuntando a una
URL propia. Wompi no manda ningun header confiable de "que comercio soy"
antes de validar el checksum -- la unica forma de saber que secreto usar es
por CUAL URL golpearon. Por eso la ruta ahora lleva el `comercio_id` en el
path: `/pagos/wompi/transacciones/{comercio_id}`. Cada uno de los comercios
reales apunta su webhook a su propio segmento, bajo la MISMA URL publica
(un solo tunel, un solo puerto -- `docs/viabilidad-multi-comercio-wompi.md`,
"Puerto 8001 y el webhook con varios comercios": la alternativa de un
puerto por comercio se descarto por triplicar la superficie expuesta sin
necesidad, y por apartarse de ADR-1 de `docs/arquitectura-v2.md` ("un
proceso, no un servicio aparte") sin necesidad real).

Pese al nombre del modulo -- "wompi" porque asi se llamaba la ruta ya
configurada en el dashboard de Wompi antes de multi-comercio -- `crear_app`
sigue sin saber que pasarela hay del otro lado de cada comercio. Recibe un
`ConciliarEventoUseCase` ya armado (que a su vez ya trae el `SelectorDePasarela`
que resuelve wompi o simulada segun el `comercio_id` de la URL) y solo
traduce HTTP hacia adentro y hacia afuera. Nada de `os.environ`, nada de
construir el `Contenedor`: eso es trabajo del composition root de este
punto de entrada, `scripts/servir_webhook_wompi.py`. Separar las dos cosas
es lo que permite probar esta app con `TestClient` sin ninguna variable de
entorno (ver `tests/test_webhook_wompi.py`).

WOMPI ESPERA UN 200, SIEMPRE
-----------------------------
Mismo argumento que `boveda/eventos.py` y que el docstring de
`ConciliarEventoUseCase`: un checksum invalido, un evento que no es un cobro de
esta app, un `comercio_id` en la URL que no tiene credenciales configuradas,
o una reserva que ya no existe no son fallos del receptor -- son desenlaces
normales de un webhook. Reintentar no arregla ninguno, y devolver algo
distinto de 200 solo le da a un atacante una forma barata de hacer que
Wompi reintente sin limite. `ConciliarEventoUseCase.__call__` ya nunca levanta, asi
que esta ruta no necesita ni un `try/except`: siempre llega a un `Response`
200.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ...usecase.conciliar_evento.conciliar_evento_use_case import ConciliarEventoUseCase


def crear_app(conciliar_evento: ConciliarEventoUseCase) -> FastAPI:
    """Factoria pura: sin efectos de importacion, sin leer variables de
    entorno. `conciliar_evento` ya viene armado por quien llame (el
    `Contenedor`, o un doble de pruebas)."""

    app = FastAPI(title="Receptor de eventos (agora)")

    @app.get("/salud")
    def salud() -> dict[str, Any]:
        return {"ok": True}

    @app.post("/pagos/wompi/transacciones/{comercio_id}")
    async def recibir(comercio_id: str, request: Request) -> JSONResponse:
        cuerpo = await request.body()
        cabeceras = dict(request.headers)
        resultado = conciliar_evento(cuerpo, cabeceras, comercio_id)

        # Visibilidad minima en consola, igual que boveda/eventos.py -- este
        # proceso normalmente corre desatendido detras de ngrok/cloudflared.
        marca = "ok " if resultado.procesado else "NO "
        print(f"[{marca}] comercio={comercio_id} {resultado.motivo} intencion={resultado.intencion_id}")

        # El cuerpo de la respuesta es solo para quien mire los logs o pruebe
        # con curl a mano -- Wompi unicamente le presta atencion al 200.
        return JSONResponse(
            status_code=200,
            content={"procesado": resultado.procesado, "motivo": resultado.motivo},
        )

    return app
