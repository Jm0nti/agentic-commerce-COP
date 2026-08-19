"""Ejecutor de cobros contra mandato. El unico camino permitido hacia Wompi.

La regla es una y no admite excepcion:

    NINGUN cobro sale de aqui sin un mandato que lo autorice.

Wompi no va a ayudar con esto. Para Wompi, cualquier POST /v1/transactions con
un payment_source_id valido y una firma de integridad correcta es un cobro
legitimo. No hay campo donde declarar la intencion, no hay tope que registrar,
no hay forma de decirle "este cobro solo vale si el titular lo pidio". Todo
ese juicio vive aqui.

    python mandato/ejecutor.py autorizar --mandato <id> -a 5000 --comercio tienda
    python mandato/ejecutor.py escenarios          la bateria de fraude, en seco
    python mandato/ejecutor.py estado              acumulados y nonces
    python mandato/ejecutor.py ledger

Estado del ejecutor en `boveda/secretos/estado_ejecutor.json`, bitacora en
`boveda/ledger_mandatos.jsonl`. El estado de `boveda/cli` usa otro esquema y no
se comparte con este ejecutor.
El ledger anota TAMBIEN los intentos rechazados: un rechazo que no queda
escrito es un ataque que no se puede contar despues.

Guardarrail: por defecto solo opera contra sandbox. Cobrar de verdad exige
--produccion y llaves prv_prod_. Es deliberado que sea incomodo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from mandato import (
    BOVEDA,
    SECRETOS,
    Resultado,
    _cargar,
    emitir,
    hash_carrito,
    verificar,
)

SANDBOX_URL = "https://sandbox.wompi.co/v1"
PROD_URL = "https://production.wompi.co/v1"

AQUI = Path(__file__).resolve().parent
# El estado guarda nonces consumidos y acumulados: borrarlo desactiva tres de
# los ocho controles. Por eso vive en `boveda/secretos/`, que no se versiona.
# Este ejecutor y `boveda.nucleo` tienen modelos de mandato distintos. No deben
# compartir el archivo de estado ni sus contadores.
ESTADO = SECRETOS / "estado_ejecutor.json"
LEDGER = BOVEDA / "ledger_mandatos.jsonl"

FINALES = frozenset({"APPROVED", "DECLINED", "VOIDED", "ERROR"})


# --------------------------------------------------------------------------- #
# Entorno y estado
# --------------------------------------------------------------------------- #


def cargar_env() -> None:
    env = AQUI.parent / ".env"
    if not env.exists():
        return
    for linea in env.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, _, v = linea.partition("=")
        k, v = k.strip(), v.split(" #")[0].strip().strip("\"'")
        if k and k not in os.environ:
            os.environ[k] = v


def leer_estado() -> dict:
    if not ESTADO.exists():
        return {"nonces_usados": [], "mandatos": {}}
    estado = json.loads(ESTADO.read_text(encoding="utf-8"))
    estado.setdefault("nonces_usados", [])
    estado.setdefault("mandatos", {})
    return estado


def escribir_estado(e: dict) -> None:
    SECRETOS.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(e, indent=2, ensure_ascii=False), encoding="utf-8")


def anotar(evento: str, datos: dict) -> None:
    BOVEDA.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "evento": evento,
                    **datos,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


# --------------------------------------------------------------------------- #
# Wompi
# --------------------------------------------------------------------------- #


class Wompi:
    def __init__(self, produccion: bool = False) -> None:
        self.pub = os.environ.get("WOMPI_PUBLIC_KEY", "")
        self.prv = os.environ.get("WOMPI_PRIVATE_KEY", "")
        self.integrity = os.environ.get("WOMPI_INTEGRITY_SECRET", "")
        self.base = os.environ.get(
            "WOMPI_BASE_URL", PROD_URL if produccion else SANDBOX_URL
        )
        self.produccion = produccion

        if not all((self.pub, self.prv, self.integrity)):
            raise SystemExit(
                "[x] faltan WOMPI_PUBLIC_KEY / WOMPI_PRIVATE_KEY / "
                "WOMPI_INTEGRITY_SECRET en el .env"
            )
        if produccion and not self.pub.startswith("pub_prod_"):
            raise SystemExit(
                "[x] pidio --produccion pero la llave publica no es pub_prod_."
            )
        if not produccion and not self.pub.startswith("pub_test_"):
            raise SystemExit(
                "[x] la llave publica no es de pruebas y no paso --produccion.\n"
                "    Si de verdad quiere mover dinero real, digalo explicitamente."
            )
        self.http = httpx.Client(timeout=25.0)

    def firma(self, ref: str, centavos: int, moneda: str = "COP") -> str:
        return hashlib.sha256(
            f"{ref}{centavos}{moneda}{self.integrity}".encode("utf-8")
        ).hexdigest()

    def _pedir(self, metodo: str, path: str, key: str, body: dict | None = None) -> dict:
        r = self.http.request(
            metodo,
            f"{self.base}{path}",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
        )
        try:
            payload = r.json()
        except ValueError:
            return {"_error": True, "_status": r.status_code}
        if r.status_code >= 400:
            return {"_error": True, "_status": r.status_code, **payload}
        return payload

    def aceptaciones(self) -> tuple[str, str]:
        d = self._pedir("GET", f"/merchants/{self.pub}", self.pub)["data"]
        return (
            d["presigned_acceptance"]["acceptance_token"],
            d["presigned_personal_data_auth"]["acceptance_token"],
        )

    def cobrar(self, payment_source_id: str, monto_cop: int, email: str) -> dict:
        acc, per = self.aceptaciones()
        ref = f"mnd-{uuid.uuid4().hex[:12]}"
        centavos = monto_cop * 100
        resp = self._pedir(
            "POST",
            "/transactions",
            self.prv,
            {
                "amount_in_cents": centavos,
                "currency": "COP",
                "customer_email": email,
                "reference": ref,
                "signature": self.firma(ref, centavos),
                "acceptance_token": acc,
                "accept_personal_auth": per,
                "payment_source_id": int(payment_source_id),
            },
        )
        if resp.get("_error"):
            return resp

        tx_id = resp["data"]["id"]
        for _ in range(40):
            d = self._pedir("GET", f"/transactions/{tx_id}", self.pub)["data"]
            if d.get("status") in FINALES:
                return d
            time.sleep(1.5)
        return d


# --------------------------------------------------------------------------- #
# El unico camino hacia el cobro
# --------------------------------------------------------------------------- #


def autorizar(
    mandato: dict,
    monto_cop: int,
    comercio: str,
    carrito: dict | None = None,
    simular: bool = True,
    produccion: bool = False,
    email: str = "lab+poc@example.com",
    etiqueta: str = "",
) -> tuple[Resultado, dict | None]:
    """Verifica, y solo si todo pasa, cobra. Anota pase lo que pase."""
    estado = leer_estado()
    mid = mandato["cuerpo"]["mandato_id"]
    acumulados = estado["mandatos"].get(mid, {"acumulado_cop": 0, "transacciones": 0})

    r = verificar(
        mandato,
        monto_cop=monto_cop,
        comercio=comercio,
        acumulado_cop=acumulados["acumulado_cop"],
        transacciones_previas=acumulados["transacciones"],
        nonces_usados=set(estado["nonces_usados"]),
        carrito=carrito,
    )

    base = {
        "mandato_id": mid,
        "etiqueta": etiqueta,
        "monto_cop": monto_cop,
        "comercio": comercio,
        "acumulado_previo": acumulados["acumulado_cop"],
        "controles": [
            {"control": n, "ok": ok, "detalle": d} for n, ok, d in r.controles
        ],
    }

    if not r.autorizado:
        anotar("rechazado", {**base, "motivos": r.motivos})
        return r, None

    if simular:
        anotar("autorizado_simulado", base)
        return r, {"status": "SIMULADO"}

    w = Wompi(produccion=produccion)
    final = w.cobrar(mandato["cuerpo"]["payment_source_id"], monto_cop, email)

    # El nonce se consume aunque el cobro sea rechazado por el banco. Si no,
    # un rechazo se vuelve una via para reintentar un mandato indefinidamente.
    estado["nonces_usados"].append(mandato["cuerpo"]["nonce"])
    if final.get("status") == "APPROVED":
        acumulados["acumulado_cop"] += monto_cop
        acumulados["transacciones"] += 1
    estado["mandatos"][mid] = acumulados
    escribir_estado(estado)

    anotar(
        "cobrado",
        {
            **base,
            "produccion": produccion,
            "transaction_id": final.get("id"),
            "status": final.get("status"),
            "status_message": final.get("status_message"),
        },
    )
    return r, final


# --------------------------------------------------------------------------- #
# Bateria de fraude
# --------------------------------------------------------------------------- #


def escenarios() -> int:
    """Los ataques que la iteracion 1 tiene que atajar. Todo en seco.

    Cada uno debe FALLAR de forma observable. Un escenario que pasa en silencio
    es un hueco; un escenario que ni siquiera se ejecuta es peor.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    fuente = "363784"
    comercio_ok = "tienda-demo"

    m = emitir(
        payment_source_id=fuente,
        monto_maximo_cop=20_000,
        tope_vida_cop=50_000,
        comercios=[comercio_ok],
        horas_vigencia=24,
        tipo="intent",
        max_transacciones=3,
    )

    casos = []

    # 1. Camino feliz
    casos.append(("camino feliz", m, 15_000, comercio_ok, 0, set(), None))

    # 2. Sobre el tope por cobro
    casos.append(("monto sobre el tope", m, 25_000, comercio_ok, 0, set(), None))

    # 3. Comercio fuera de la lista blanca (inyeccion de prompt)
    casos.append(
        ("comercio no autorizado", m, 15_000, "tienda-del-atacante", 0, set(), None)
    )

    # 4. Replay de un nonce ya consumido
    casos.append(
        ("replay de nonce", m, 10_000, comercio_ok, 0, {m["cuerpo"]["nonce"]}, None)
    )

    # 5. Escalada por acumulacion: cada cobro es legitimo, la suma no
    casos.append(("escalada acumulada", m, 15_000, comercio_ok, 45_000, set(), None))

    # 6. Mandato expirado, pero legitimamente firmado. Debe caer por vigencia,
    #    no por firma: son dos controles distintos y hay que verlos separados.
    vencido = emitir(
        payment_source_id=fuente,
        monto_maximo_cop=20_000,
        tope_vida_cop=50_000,
        comercios=[comercio_ok],
        horas_vigencia=-48,
    )
    casos.append(("mandato expirado", vencido, 10_000, comercio_ok, 0, set(), None))

    # 7. Cuerpo alterado despues de firmar (aqui SI debe caer por firma)
    alterado = json.loads(json.dumps(m))
    alterado["cuerpo"]["limites"]["monto_maximo_cop"] = 5_000_000
    casos.append(("tope inflado tras firmar", alterado, 100_000, comercio_ok, 0, set(), None))

    # 8. Firmado por otra llave
    otra = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    suplantado = json.loads(json.dumps(m))
    suplantado["firma"] = otra.sign(
        json.dumps(
            suplantado["cuerpo"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hex()
    casos.append(("firma de otra llave", suplantado, 10_000, comercio_ok, 0, set(), None))

    # 9. Carrito alterado despues de la firma (mandato tipo cart)
    carrito_original = {
        "items": [{"sku": "cafe-500g", "cantidad": 1}],
        "monto_cop": 18_000,
        "comercio": comercio_ok,
    }
    mc = emitir(
        payment_source_id=fuente,
        monto_maximo_cop=20_000,
        tope_vida_cop=20_000,
        comercios=[comercio_ok],
        tipo="cart",
        carrito=carrito_original,
    )
    carrito_alterado = {
        "items": [{"sku": "consola", "cantidad": 1}],
        "monto_cop": 18_000,
        "comercio": comercio_ok,
    }
    casos.append(
        ("carrito alterado", mc, 18_000, comercio_ok, 0, set(), carrito_alterado)
    )
    casos.append(("carrito integro", mc, 18_000, comercio_ok, 0, set(), carrito_original))

    print("Bateria de escenarios de fraude (en seco, sin tocar Wompi)")
    print("=" * 74)
    fallos_esperados = 0
    for nombre, man, monto, com, acum, nonces, carr in casos:
        r = verificar(
            man,
            monto_cop=monto,
            comercio=com,
            acumulado_cop=acum,
            nonces_usados=nonces,
            carrito=carr,
        )
        veredicto = "AUTORIZADO" if r.autorizado else "RECHAZADO"
        print(f"\n{nombre:32} {monto:>10,} COP  ->  {veredicto}")
        if not r.autorizado:
            fallos_esperados += 1
            for mot in r.motivos:
                print(f"    {mot}")

    print("\n" + "=" * 74)
    print(f"{fallos_esperados} de {len(casos)} escenarios rechazados.")
    print(
        "\nSe esperan 2 autorizados: 'camino feliz' y 'carrito integro'.\n"
        "Cualquier otro autorizado es un hueco en el ejecutor, no un exito."
    )
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main() -> int:
    cargar_env()
    p = argparse.ArgumentParser(description="Ejecutor de cobros contra mandato")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("autorizar", help="verifica y, si pasa, cobra")
    pa.add_argument("--mandato", required=True, help="archivo o id en la boveda")
    pa.add_argument("-a", "--amount", type=int, required=True)
    pa.add_argument("--comercio", required=True)
    pa.add_argument("--cobrar", action="store_true", help="ejecuta de verdad")
    pa.add_argument("--produccion", action="store_true", help="DINERO REAL")
    pa.add_argument("--etiqueta", default="")

    sub.add_parser("escenarios", help="bateria de fraude en seco")
    sub.add_parser("estado", help="acumulados y nonces consumidos")
    sub.add_parser("ledger", help="bitacora de decisiones")

    a = p.parse_args()

    if a.cmd == "escenarios":
        return escenarios()

    if a.cmd == "estado":
        e = leer_estado()
        print(f"Nonces consumidos: {len(e['nonces_usados'])}")
        for mid, d in e["mandatos"].items():
            print(
                f"  {mid}  acumulado {d['acumulado_cop']:>12,} COP"
                f"  transacciones {d['transacciones']}"
            )
        return 0

    if a.cmd == "ledger":
        if not LEDGER.exists():
            print("Sin registros todavia.")
            return 0
        filas = [
            json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l
        ]
        print(f"{len(filas)} decisiones\n")
        print(f"{'fecha':20} {'evento':22} {'monto':>12}  comercio")
        print("-" * 78)
        for f in filas:
            print(
                f"{f['ts'][:19]:20} {f['evento'][:22]:22} "
                f"{f.get('monto_cop', 0):>12,}  {f.get('comercio', '')}"
            )
        rech = [f for f in filas if f["evento"] == "rechazado"]
        if rech:
            print(f"\n  {len(rech)} intentos rechazados por el ejecutor")
        return 0

    if a.cmd == "autorizar":
        man = _cargar(
            a.mandato if a.mandato.endswith(".json") else f"{a.mandato}.json"
        )
        if a.produccion and not a.cobrar:
            print("[x] --produccion sin --cobrar no tiene sentido.")
            return 1
        if a.produccion:
            print(
                "\n  *** PRODUCCION. Esto mueve dinero real de una cuenta real. ***\n"
            )
        r, final = autorizar(
            man,
            monto_cop=a.amount,
            comercio=a.comercio,
            simular=not a.cobrar,
            produccion=a.produccion,
            etiqueta=a.etiqueta,
        )
        print(f"Cobro de {a.amount:,} COP hacia '{a.comercio}'\n")
        r.imprimir()
        if final:
            print(f"\n  wompi -> {final.get('status')} {final.get('id', '')}")
        return 0 if r.autorizado else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
