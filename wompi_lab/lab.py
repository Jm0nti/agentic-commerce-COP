"""Banco de pruebas de Wompi sandbox. Autocontenido, sin relacion con AGORA.

El objetivo de este archivo es uno solo: establecer que los cobros funcionan y
que se pueden observar. Nada de mandatos, nada de agentes, nada de fraude
todavia. Cuando estos comandos corran de punta a punta y las transacciones se
vean en el dashboard, ahi si se empieza a construir encima.

    python wompi_lab/lab.py check              1. llaves y conectividad
    python wompi_lab/lab.py card               2. cobro con tarjeta de prueba
    python wompi_lab/lab.py nequi              3. cobro con Nequi
    python wompi_lab/lab.py source             4. crea la fuente de pago
    python wompi_lab/lab.py charge -a 5000     5. cobra sin el titular presente
    python wompi_lab/lab.py status <tx_id>     consulta una transaccion
    python wompi_lab/lab.py ledger             lo que lleva hecho este banco

Cada operacion queda en `wompi_lab/ledger.jsonl`. Ese archivo es la fuente de
verdad local: el dashboard puede tardar en refrescar y la API no expone un
listado documentado, asi que conviene no depender de ninguno de los dos para
saber que se hizo.

Solo opera contra sandbox. El cliente se niega a arrancar si la URL o la llave
publica no son de pruebas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_URL = "https://sandbox.wompi.co/v1"
AQUI = Path(__file__).resolve().parent
LEDGER = AQUI / "ledger.jsonl"
CACHE = AQUI / "source.json"
EMAIL = "lab+poc@example.com"

# Datos de prueba del sandbox. Cualquier otro valor termina en ERROR.
TARJETA_APROBADA = "4242424242424242"
TARJETA_DECLINADA = "4111111111111111"
NEQUI_APROBADO = "3991111111"
NEQUI_DECLINADO = "3992222222"

FINALES = frozenset({"APPROVED", "DECLINED", "VOIDED", "ERROR"})


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def cargar_env() -> None:
    """Lee el .env de la raiz del repo sin depender de python-dotenv."""
    env = AQUI.parent / ".env"
    if not env.exists():
        return
    for linea in env.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        clave = clave.strip()
        valor = valor.split(" #")[0].strip().strip("\"'")
        if clave and clave not in os.environ:
            os.environ[clave] = valor


def anotar(evento: str, datos: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    registro = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evento": evento,
        **datos,
    }
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def huella(valor: str) -> str:
    if not valor:
        return "(ausente)"
    return f"{'_'.join(valor.split('_')[:2])}_...{valor[-4:]}"


def referencia(prefijo: str) -> str:
    """Unica por construccion. Wompi rechaza referencias repetidas con 422."""
    return f"{prefijo}-{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------- #
# Cliente
# --------------------------------------------------------------------------- #


class Lab:
    def __init__(self) -> None:
        self.pub = os.environ.get("WOMPI_PUBLIC_KEY", "")
        self.prv = os.environ.get("WOMPI_PRIVATE_KEY", "")
        self.integrity = os.environ.get("WOMPI_INTEGRITY_SECRET", "")
        self.http = httpx.Client(timeout=25.0)

        faltan = [
            n
            for n, v in (
                ("WOMPI_PUBLIC_KEY", self.pub),
                ("WOMPI_PRIVATE_KEY", self.prv),
                ("WOMPI_INTEGRITY_SECRET", self.integrity),
            )
            if not v
        ]
        if faltan:
            raise SystemExit(
                f"[x] faltan en el .env: {', '.join(faltan)}\n\n"
                "    WOMPI_PUBLIC_KEY=pub_test_...\n"
                "    WOMPI_PRIVATE_KEY=prv_test_...\n"
                "    WOMPI_INTEGRITY_SECRET=test_integrity_...\n\n"
                "Las tres estan en comercios.wompi.co, seccion de desarrolladores,\n"
                "con el modo de pruebas activado."
            )
        if not self.pub.startswith("pub_test_"):
            raise SystemExit(
                "[x] la llave publica no es de pruebas. Este banco solo opera en "
                "sandbox; una llave pub_prod_ moveria dinero real."
            )

    # -- HTTP --------------------------------------------------------------- #

    def _pedir(self, metodo: str, path: str, key: str, body: dict | None = None) -> dict:
        r = self.http.request(
            metodo,
            f"{BASE_URL}{path}",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
        )
        try:
            payload = r.json()
        except ValueError:
            raise SystemExit(f"[x] {metodo} {path} -> {r.status_code} sin JSON")
        if r.status_code >= 400:
            print(f"  [!] {metodo} {path} -> {r.status_code}")
            print(f"      {json.dumps(payload, ensure_ascii=False)[:400]}")
            return {"_error": True, "_status": r.status_code, **payload}
        return payload

    def get(self, path: str, key: str | None = None) -> dict:
        return self._pedir("GET", path, key or self.pub)

    def post(self, path: str, key: str, body: dict) -> dict:
        return self._pedir("POST", path, key, body)

    # -- piezas ------------------------------------------------------------- #

    def firma(self, ref: str, centavos: int, moneda: str = "COP") -> str:
        return hashlib.sha256(
            f"{ref}{centavos}{moneda}{self.integrity}".encode("utf-8")
        ).hexdigest()

    def aceptaciones(self) -> tuple[str, str]:
        d = self.get(f"/merchants/{self.pub}")["data"]
        return (
            d["presigned_acceptance"]["acceptance_token"],
            d["presigned_personal_data_auth"]["acceptance_token"],
        )

    def comercio(self) -> dict:
        return self.get(f"/merchants/{self.pub}")["data"]

    def transaccion(self, tx_id: str) -> dict:
        return self.get(f"/transactions/{tx_id}")["data"]

    def esperar(self, tx_id: str, intentos: int = 40, pausa: float = 1.5) -> dict:
        ultimo: dict = {}
        for i in range(intentos):
            ultimo = self.transaccion(tx_id)
            estado = ultimo.get("status")
            if estado in FINALES:
                return ultimo
            if i == 0:
                print(f"      esperando estado final (actual: {estado})", end="", flush=True)
            else:
                print(".", end="", flush=True)
            time.sleep(pausa)
        print()
        return ultimo

    def cobrar(self, body: dict, etiqueta: str) -> dict:
        """Crea la transaccion, espera el estado final y lo anota."""
        resp = self.post("/transactions", self.prv, body)
        if resp.get("_error"):
            anotar(
                "cobro_fallido",
                {"etiqueta": etiqueta, "reference": body["reference"], "respuesta": resp},
            )
            return resp

        tx_id = resp["data"]["id"]
        print(f"      transaccion {tx_id} creada (PENDING)")
        final = self.esperar(tx_id)
        estado = final.get("status", "?")
        print(f"\n      {tx_id}  ->  {estado}  {final.get('status_message') or ''}")

        anotar(
            "cobro",
            {
                "etiqueta": etiqueta,
                "transaction_id": tx_id,
                "reference": body["reference"],
                "amount_cop": body["amount_in_cents"] // 100,
                "metodo": body.get("payment_method", {}).get("type")
                or f"payment_source:{body.get('payment_source_id')}",
                "status": estado,
                "status_message": final.get("status_message"),
            },
        )
        return final


# --------------------------------------------------------------------------- #
# Comandos
# --------------------------------------------------------------------------- #


def cmd_check(lab: Lab) -> int:
    print("Credenciales cargadas")
    print(f"  base_url          {BASE_URL}")
    print(f"  public_key        {huella(lab.pub)}")
    print(f"  private_key       {huella(lab.prv)}")
    print(f"  integrity_secret  {huella(lab.integrity)}")

    print("\nConectividad")
    d = lab.comercio()
    if not d:
        return 1
    print(f"  comercio          {d.get('name')}")
    print(f"  legal_name        {d.get('legal_name')}")
    acc, per = lab.aceptaciones()
    print(f"  acceptance_token  ok ({len(acc)} chars)")
    print(f"  personal_auth     ok ({len(per)} chars)")

    metodos = d.get("accepted_payment_methods") or d.get("payment_methods")
    if metodos:
        print(f"  metodos activos   {metodos}")

    print("\nFirma de integridad (prueba con valores fijos)")
    print(f"  sha256('ABC' + 100000 + 'COP' + secreto) = {lab.firma('ABC', 100000)[:24]}...")

    print("\n[ok] todo responde. Siguiente: `lab.py card`")
    return 0


def cmd_card(lab: Lab, monto: int, declinar: bool) -> int:
    numero = TARJETA_DECLINADA if declinar else TARJETA_APROBADA
    print(f"Cobro con tarjeta {numero[:4]}...{numero[-4:]} por {monto:,} COP")

    print("  1. tokenizando la tarjeta (llave publica)")
    tok = lab.post(
        "/tokens/cards",
        lab.pub,
        {
            "number": numero,
            "cvc": "123",
            "exp_month": "08",
            "exp_year": "30",
            "card_holder": "Juan Pruebas",
        },
    )
    if tok.get("_error"):
        return 1
    token = tok["data"]["id"]
    print(f"      token {token[:24]}...")

    print("  2. creando la transaccion (llave privada)")
    acc, per = lab.aceptaciones()
    ref = referencia("card")
    centavos = monto * 100
    final = lab.cobrar(
        {
            "amount_in_cents": centavos,
            "currency": "COP",
            "customer_email": EMAIL,
            "reference": ref,
            "signature": lab.firma(ref, centavos),
            "acceptance_token": acc,
            "accept_personal_auth": per,
            "payment_method": {"type": "CARD", "token": token, "installments": 1},
        },
        etiqueta="card_declinada" if declinar else "card_aprobada",
    )
    return 0 if final.get("status") in FINALES else 1


def cmd_nequi(lab: Lab, monto: int, declinar: bool) -> int:
    tel = NEQUI_DECLINADO if declinar else NEQUI_APROBADO
    print(f"Cobro Nequi al {tel} por {monto:,} COP")

    acc, per = lab.aceptaciones()
    ref = referencia("nequi")
    centavos = monto * 100
    final = lab.cobrar(
        {
            "amount_in_cents": centavos,
            "currency": "COP",
            "customer_email": EMAIL,
            "reference": ref,
            "signature": lab.firma(ref, centavos),
            "acceptance_token": acc,
            "accept_personal_auth": per,
            "payment_method": {"type": "NEQUI", "phone_number": tel},
        },
        etiqueta="nequi_declinada" if declinar else "nequi_aprobada",
    )
    return 0 if final.get("status") in FINALES else 1


def cmd_source(lab: Lab, forzar: bool) -> int:
    """Crea la fuente de pago: el titular autoriza UNA vez.

    Este paso es la frontera. Antes de el, cada cobro necesita al titular.
    Despues de el, ninguno lo necesita.
    """
    if CACHE.exists() and not forzar:
        datos = json.loads(CACHE.read_text(encoding="utf-8"))
        print(f"Fuente ya existente: {datos['payment_source_id']}")
        print("Use --force para crear otra.")
        return 0

    print("Creando fuente de pago Nequi")
    print("  1. tokenizando la cuenta")
    tok = lab.post("/tokens/nequi", lab.pub, {"phone_number": NEQUI_APROBADO})
    if tok.get("_error"):
        return 1
    token = tok["data"]["id"]
    print(f"      token {token[:28]}...  estado {tok['data']['status']}")

    print("  2. esperando que el titular acepte la suscripcion")
    estado = "PENDING"
    for _ in range(30):
        estado = lab.get(f"/tokens/nequi/{token}")["data"]["status"]
        if estado != "PENDING":
            break
        print(".", end="", flush=True)
        time.sleep(2)
    print(f"\n      estado {estado}")
    if estado != "APPROVED":
        print("[x] el token no quedo aprobado, no se puede crear la fuente")
        return 1

    print("  3. creando la fuente de pago (llave privada)")
    acc, per = lab.aceptaciones()
    resp = lab.post(
        "/payment_sources",
        lab.prv,
        {
            "type": "NEQUI",
            "token": token,
            "customer_email": EMAIL,
            "acceptance_token": acc,
            "accept_personal_auth": per,
        },
    )
    if resp.get("_error"):
        return 1

    sid = resp["data"]["id"]
    CACHE.write_text(
        json.dumps({"payment_source_id": sid, "token": token, "email": EMAIL}, indent=2),
        encoding="utf-8",
    )
    anotar("fuente_creada", {"payment_source_id": sid, "status": resp["data"]["status"]})

    print(f"      fuente {sid}  estado {resp['data']['status']}")
    print(
        "\n  Desde aqui se puede cobrar sin el titular. No hay tope, ni "
        "vencimiento,\n  ni ligadura a un monto o a un producto. Pruebe: "
        "`lab.py charge -a 5000`"
    )
    return 0


def cmd_charge(lab: Lab, monto: int, repetir_ref: str | None) -> int:
    if not CACHE.exists():
        print("[x] no hay fuente de pago. Corra `lab.py source` primero.")
        return 1
    datos = json.loads(CACHE.read_text(encoding="utf-8"))
    sid = datos["payment_source_id"]

    print(f"Cobro de {monto:,} COP contra la fuente {sid}, sin el titular presente")
    acc, per = lab.aceptaciones()
    ref = repetir_ref or referencia("src")
    if repetir_ref:
        print(f"  reutilizando la referencia {ref} (prueba de duplicado)")
    centavos = monto * 100

    final = lab.cobrar(
        {
            "amount_in_cents": centavos,
            "currency": "COP",
            "customer_email": datos["email"],
            "reference": ref,
            "signature": lab.firma(ref, centavos),
            "acceptance_token": acc,
            "accept_personal_auth": per,
            "payment_source_id": sid,
        },
        etiqueta="cobro_sin_titular",
    )
    return 0 if final.get("status") in FINALES else 1


def cmd_status(lab: Lab, tx_id: str) -> int:
    d = lab.transaccion(tx_id)
    if not d:
        return 1
    for campo in (
        "id",
        "reference",
        "status",
        "status_message",
        "amount_in_cents",
        "currency",
        "payment_method_type",
        "created_at",
        "finalized_at",
    ):
        if campo in d:
            print(f"  {campo:20} {d[campo]}")
    return 0


def cmd_ledger() -> int:
    if not LEDGER.exists():
        print("Sin registros todavia.")
        return 0
    filas = [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l]
    print(f"{len(filas)} registros en {LEDGER.name}\n")
    print(f"{'fecha':20} {'evento':16} {'monto':>12} {'estado':10} id")
    print("-" * 92)
    for f in filas:
        monto = f"{f['amount_cop']:,}" if "amount_cop" in f else ""
        print(
            f"{f['ts'][:19]:20} {f['evento'][:16]:16} {monto:>12} "
            f"{(f.get('status') or ''):10} {f.get('transaction_id') or ''}"
        )
    aprobadas = [f for f in filas if f.get("status") == "APPROVED"]
    if aprobadas:
        total = sum(f.get("amount_cop", 0) for f in aprobadas)
        print(f"\n  {len(aprobadas)} aprobadas, {total:,} COP de juguete movidos")
    return 0


# --------------------------------------------------------------------------- #


def main() -> int:
    cargar_env()
    p = argparse.ArgumentParser(description="Banco de pruebas de Wompi sandbox")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="llaves y conectividad")

    pc = sub.add_parser("card", help="cobro con tarjeta de prueba")
    pc.add_argument("-a", "--amount", type=int, default=15000)
    pc.add_argument("--declinar", action="store_true")

    pn = sub.add_parser("nequi", help="cobro con Nequi")
    pn.add_argument("-a", "--amount", type=int, default=15000)
    pn.add_argument("--declinar", action="store_true")

    ps = sub.add_parser("source", help="crea la fuente de pago")
    ps.add_argument("--force", action="store_true")

    pg = sub.add_parser("charge", help="cobra contra la fuente, sin titular")
    pg.add_argument("-a", "--amount", type=int, default=5000)
    pg.add_argument("--repetir-ref", help="reutiliza una referencia ya usada")

    pt = sub.add_parser("status", help="consulta una transaccion")
    pt.add_argument("tx_id")

    sub.add_parser("ledger", help="registro local de este banco")

    args = p.parse_args()

    if args.cmd == "ledger":
        return cmd_ledger()

    lab = Lab()
    if args.cmd == "check":
        return cmd_check(lab)
    if args.cmd == "card":
        return cmd_card(lab, args.amount, args.declinar)
    if args.cmd == "nequi":
        return cmd_nequi(lab, args.amount, args.declinar)
    if args.cmd == "source":
        return cmd_source(lab, args.force)
    if args.cmd == "charge":
        return cmd_charge(lab, args.amount, args.repetir_ref)
    if args.cmd == "status":
        return cmd_status(lab, args.tx_id)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
