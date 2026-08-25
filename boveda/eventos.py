"""Receptor de eventos de Wompi, con validacion de checksum.

La URL de eventos configurada en el dashboard apunta a un dominio que no
responde. Wompi lo reporta como "Error" y reintenta hasta 3 veces en 24 horas;
despues se rinde. Eso no rompe ningun cobro -- el evento es una notificacion,
no parte del flujo -- pero deja a la PoC sin el unico canal fuera de banda que
tiene para saber lo que paso.

Y hay algo mas: en Fase B **no llega ningun push a Nequi**. La suscripcion se
autorizo una vez y desde entonces el titular no se entera de nada. El webhook
es literalmente la unica senal de que hubo un cobro. Que este roto no es un
detalle de infraestructura.

VALIDAR EL CHECKSUM NO ES OPCIONAL
----------------------------------
Sin validarlo, cualquiera que sepa la URL puede POSTear un `transaction.updated`
con status APPROVED. La boveda creeria que un cobro paso cuando no paso, o al
reves. Es la superficie de ataque mas barata de todo el sistema: no hay que
robar credenciales, basta con adivinar un endpoint.

El calculo, segun la documentacion de Wompi:

    SHA256( v1 + v2 + ... + vn + timestamp + secreto_de_eventos )

donde v1..vn son los valores de las propiedades listadas en
`signature.properties`, EN ESE ORDEN, leidas del objeto `data`. Wompi advierte
que esa lista puede cambiar con el tiempo y entre eventos, asi que se lee del
evento y no se quema en el codigo.

    uvicorn boveda.eventos:app --port 8000

Y se expone con lo que sea (ngrok, cloudflared) para poner esa URL publica en
el dashboard, seccion Eventos.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response

RAIZ = Path(__file__).resolve().parent.parent
BITACORA = RAIZ / "boveda" / "eventos.jsonl"

app = FastAPI(title="Receptor de eventos Wompi")


def _leer(data: dict[str, Any], ruta: str) -> Any:
    """`transaction.amount_in_cents` -> data['transaction']['amount_in_cents']"""
    actual: Any = data
    for parte in ruta.split("."):
        if not isinstance(actual, dict):
            return None
        actual = actual.get(parte)
    return actual


def checksum_esperado(evento: dict[str, Any], secreto: str) -> str | None:
    """None si al evento le falta algo para poder calcularlo."""
    firma = evento.get("signature") or {}
    props = firma.get("properties")
    data = evento.get("data")
    ts = evento.get("timestamp")
    if not props or not isinstance(data, dict) or ts is None:
        return None

    partes = []
    for ruta in props:
        valor = _leer(data, ruta)
        if valor is None:
            return None
        partes.append(str(valor))
    partes.append(str(ts))
    partes.append(secreto)
    return hashlib.sha256("".join(partes).encode("utf-8")).hexdigest()


def validar(evento: dict[str, Any], secreto: str) -> tuple[bool, str]:
    recibido = (evento.get("signature") or {}).get("checksum")
    if not recibido:
        return False, "el evento no trae checksum"
    esperado = checksum_esperado(evento, secreto)
    if esperado is None:
        return False, "no se pudo calcular el checksum con lo que trae el evento"
    # Comparacion en tiempo constante. Es barato y evita regalar informacion.
    if not hmac.compare_digest(esperado, str(recibido)):
        return False, "checksum no coincide"
    return True, "ok"


def anotar(registro: dict[str, Any]) -> None:
    BITACORA.parent.mkdir(parents=True, exist_ok=True)
    with BITACORA.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


@app.get("/salud")
def salud() -> dict[str, Any]:
    return {"ok": True, "secreto_configurado": bool(os.environ.get("WOMPI_EVENTS_SECRET"))}


@app.post("/pagos/wompi/transacciones")
async def recibir(request: Request) -> Response:
    """Wompi espera un 200. Cualquier otra cosa la hace reintentar.

    Se responde 200 incluso cuando el checksum no valida: reintentar no
    arreglaria una firma mala, y dejar la puerta abierta a que un atacante
    provoque reintentos infinitos es peor. El evento se anota como invalido y
    ahi queda la evidencia.
    """
    crudo = await request.body()
    try:
        evento = json.loads(crudo)
    except ValueError:
        anotar(
            {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "valido": False,
                "motivo": "cuerpo no es JSON",
                "crudo": crudo[:500].decode("utf-8", "replace"),
            }
        )
        return Response(status_code=200)

    secreto = os.environ.get("WOMPI_EVENTS_SECRET", "")
    if not secreto:
        ok, motivo = False, "falta WOMPI_EVENTS_SECRET en el .env"
    else:
        ok, motivo = validar(evento, secreto)

    tx = ((evento.get("data") or {}).get("transaction")) or {}
    metodo = tx.get("payment_method") or {}
    registro = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "valido": ok,
        "motivo": motivo,
        "evento": evento.get("event"),
        "environment": evento.get("environment"),
        "transaction_id": tx.get("id"),
        "reference": tx.get("reference"),
        "status": tx.get("status"),
        "status_message": tx.get("status_message"),
        "afe_decision": metodo.get("afe_decision"),
        "amount_cop": (tx.get("amount_in_cents") or 0) // 100,
        "payment_source_id": tx.get("payment_source_id"),
        "header_checksum": request.headers.get("X-Event-Checksum"),
    }
    anotar(registro)

    marca = "ok " if ok else "NO "
    print(
        f"[{marca}] {registro['evento']} {registro['transaction_id']} "
        f"{registro['status']} {registro['amount_cop']:,} COP"
        + ("" if ok else f"  ({motivo})")
    )
    return Response(status_code=200)
