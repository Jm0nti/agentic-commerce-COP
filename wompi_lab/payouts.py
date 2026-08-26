"""Banco de pruebas de envio de dinero (Wompi Pagos a Terceros, sandbox).

Esto NO es el mismo producto que `lab.py`. Cambia todo:

                    lab.py (cobros)              payouts.py (envios)
    base_url        sandbox.wompi.co/v1          api.sandbox.payouts.wompi.co/v1
    auth            Bearer pub_test_/prv_test_   headers x-api-key + user-principal-id
    dashboard       Desarrolladores              Desarrolladores > Payouts
    direccion       el cliente paga al comercio  el comercio paga a un tercero

La direccion del dinero es lo que hace a este archivo interesante para la PoC.
En `lab.py` un cobro mal hecho se disputa: hay tarjeta, hay emisor, hay
contracargo. Aqui no. Una dispersion sale de la cuenta y llega a la cuenta del
beneficiario; si el beneficiario era el equivocado, no hay a quien reclamarle.

    python wompi_lab/payouts.py check                     1. credenciales y cuentas
    python wompi_lab/payouts.py fund -a 5000000           2. recarga saldo de prueba
    python wompi_lab/payouts.py banks                     3. catalogo de bancos
    python wompi_lab/payouts.py send -a 20000 ...         4. envio a cuenta bancaria
    python wompi_lab/payouts.py resolve <llave>           5. resuelve una llave Bre-B
    python wompi_lab/payouts.py breb <llave> -a 20000     6. dispersion por llave
    python wompi_lab/payouts.py status <payout_id>
    python wompi_lab/payouts.py ledger

DOS COSAS QUE HAY QUE COMPROBAR ANTES DE ESPERAR QUE ESTO CORRA
---------------------------------------------------------------
1. El producto "Pagos a Terceros" tiene que estar habilitado en la cuenta. Se
   verifica en el dashboard: Desarrollo > Desarrolladores > boton "Payouts"
   arriba a la derecha. Si ese boton no aparece, hay que pedirlo al comercial;
   no es autoservicio como el sandbox de cobros.

2. El endpoint de resolucion de llave Bre-B esta declarado en la guia de
   integracion de Wompi, pero esa pagina se renderiza en cliente y no pude
   leerla. La ruta en `RESOLVE_PATH` es una conjetura razonable y esta aislada
   a proposito para que corregirla sea cambiar una constante. Todo lo demas de
   este archivo sale de documentacion que si pude verificar.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_URL = "https://api.sandbox.payouts.wompi.co/v1"
AQUI = Path(__file__).resolve().parent
RAIZ_REPO = AQUI.parent
if str(RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO))

from utilidades.env import cargar_env_desde_archivo

LEDGER = AQUI / "ledger_payouts.jsonl"

# Ver nota 2 en el encabezado. Ajustar cuando se lea la guia oficial.
RESOLVE_PATH = "/breb/keys/resolve"

ESTADOS_LOTE = {
    "PENDING_APPROVAL": "por aprobar",
    "PENDING": "en proceso",
    "NOT_APPROVED": "no aprobado",
    "REJECTED": "rechazado",
    "PARTIAL_PAYMENT": "pago parcial",
    "TOTAL_PAYMENT": "procesado",
}
ESTADOS_TX = {
    "PENDING": "en proceso",
    "APPROVED": "pagada",
    "CANCELLED": "cancelada",
    "FAILED": "rechazada",
}


def cargar_env() -> None:
    cargar_env_desde_archivo(RAIZ_REPO / ".env")


def anotar(evento: str, datos: dict) -> None:
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


def huella(v: str) -> str:
    return f"...{v[-6:]}" if v else "(ausente)"


def cop(centavos: int) -> str:
    return f"{centavos // 100:,} COP"


# --------------------------------------------------------------------------- #


class Payouts:
    def __init__(self) -> None:
        self.api_key = os.environ.get("WOMPI_PAYOUTS_API_KEY", "")
        self.user_id = os.environ.get("WOMPI_PAYOUTS_USER_ID", "")
        if not self.api_key or not self.user_id:
            raise SystemExit(
                "[x] faltan en el .env:\n\n"
                "    WOMPI_PAYOUTS_API_KEY=...\n"
                "    WOMPI_PAYOUTS_USER_ID=...\n\n"
                "Salen del dashboard en modo sandbox:\n"
                "  Desarrollo > Desarrolladores > boton 'Payouts' (arriba a la derecha)\n"
                "  > modulo 'Modo Sandbox' > 'Ver modo Sandbox'\n\n"
                "Con sandbox activo aparece una barra roja arriba. Si no ves el boton\n"
                "'Payouts', el producto Pagos a Terceros no esta habilitado en la cuenta."
            )
        self.http = httpx.Client(timeout=30.0)

    def _headers(self, idempotente: bool = False) -> dict:
        h = {
            "x-api-key": self.api_key,
            "user-principal-id": self.user_id,
            "Content-Type": "application/json",
        }
        if idempotente:
            # Entre 1 y 64 caracteres, alfanumericos y guion. Expira en 24h.
            h["idempotency-key"] = f"lab-{uuid.uuid4().hex}"
        return h

    def pedir(self, metodo: str, path: str, body: dict | None = None) -> dict:
        r = self.http.request(
            metodo,
            f"{BASE_URL}{path}",
            headers=self._headers(idempotente=metodo == "POST"),
            json=body,
        )
        try:
            payload = r.json()
        except ValueError:
            print(f"  [!] {metodo} {path} -> {r.status_code} sin JSON")
            print(f"      {r.text[:300]}")
            return {"_error": True, "_status": r.status_code}
        if r.status_code >= 400:
            print(f"  [!] {metodo} {path} -> {r.status_code}")
            print(f"      {json.dumps(payload, ensure_ascii=False)[:500]}")
            return {"_error": True, "_status": r.status_code, **payload}
        return payload

    # -- endpoints ---------------------------------------------------------- #

    def cuentas(self) -> dict:
        return self.pedir("GET", "/accounts")

    def bancos(self) -> dict:
        return self.pedir("GET", "/banks")

    def recargar(self, account_id: str, centavos: int) -> dict:
        """Endpoint exclusivo de sandbox. Minimo $1.000, maximo $50.000.000."""
        return self.pedir(
            "POST",
            "/accounts/balance-recharge",
            {"accountId": account_id, "amountInCents": centavos},
        )

    def crear_lote(self, cuerpo: dict) -> dict:
        return self.pedir("POST", "/payouts", cuerpo)

    def lote(self, payout_id: str) -> dict:
        return self.pedir("GET", f"/payouts/{payout_id}")

    def resolver_llave(self, llave: str) -> dict:
        """Devuelve el titular detras de una llave Bre-B, ANTES de dispersar.

        Este es el unico punto del flujo donde se puede comparar a quien se
        cree que se le esta pagando contra a quien se le va a pagar de verdad.
        Despues de la dispersion no hay reversa.
        """
        return self.pedir("POST", RESOLVE_PATH, {"key": llave})


# --------------------------------------------------------------------------- #
# Comandos
# --------------------------------------------------------------------------- #


def _primera_cuenta(p: Payouts) -> dict | None:
    resp = p.cuentas()
    if resp.get("_error"):
        return None
    filas = resp.get("data") or resp.get("accounts") or resp
    if isinstance(filas, dict):
        filas = filas.get("content") or filas.get("items") or []
    return filas[0] if filas else None


def cmd_check(p: Payouts) -> int:
    print("Credenciales")
    print(f"  base_url          {BASE_URL}")
    print(f"  x-api-key         {huella(p.api_key)}")
    print(f"  user-principal-id {huella(p.user_id)}")

    print("\nCuentas de origen")
    resp = p.cuentas()
    if resp.get("_error"):
        print(
            "\n[x] no respondio. Lo mas probable: el producto Pagos a Terceros\n"
            "    no esta habilitado, o las llaves son de produccion."
        )
        return 1
    print(json.dumps(resp, indent=2, ensure_ascii=False)[:1500])
    print("\n[ok] la API responde. Siguiente: `payouts.py fund -a 5000000`")
    return 0


def cmd_fund(p: Payouts, monto_cop: int, account_id: str | None) -> int:
    if not account_id:
        cuenta = _primera_cuenta(p)
        if not cuenta:
            print("[x] no encontre cuentas. Corra `payouts.py check` y pase --account-id")
            return 1
        account_id = cuenta.get("id") or cuenta.get("accountId")
        print(f"Usando la primera cuenta: {account_id}")

    centavos = monto_cop * 100
    if not (100_000 <= centavos <= 5_000_000_000):
        print("[x] el monto debe estar entre 1.000 y 50.000.000 COP")
        return 1

    print(f"Recargando {monto_cop:,} COP de juguete")
    resp = p.recargar(account_id, centavos)
    if resp.get("_error"):
        return 1
    print(json.dumps(resp, indent=2, ensure_ascii=False)[:800])
    anotar("recarga", {"account_id": account_id, "amount_cop": monto_cop})
    return 0


def cmd_banks(p: Payouts, filtro: str | None) -> int:
    resp = p.bancos()
    if resp.get("_error"):
        return 1
    filas = resp.get("data") or resp
    if isinstance(filas, dict):
        filas = filas.get("content") or filas.get("items") or []
    for b in filas:
        nombre = b.get("name", "")
        if filtro and filtro.lower() not in nombre.lower():
            continue
        print(f"  {b.get('id', ''):40} {b.get('code', ''):>6}  {nombre}")
    return 0


def cmd_send(
    p: Payouts,
    monto_cop: int,
    account_id: str,
    bank_id: str,
    account_number: str,
    legal_id: str,
    nombre: str,
    fallar: bool,
) -> int:
    """Envio a una cuenta bancaria por los datos tradicionales."""
    ref = f"lote-{uuid.uuid4().hex[:10]}"
    cuerpo = {
        "reference": ref,
        "accountId": account_id,
        "paymentType": "OTHER",
        # Exclusivo de sandbox: fuerza el desenlace. Sin este campo, APPROVED.
        "transactionStatus": "FAILED" if fallar else "APPROVED",
        "transactions": [
            {
                "legalIdType": "CC",
                "legalId": legal_id,
                "bankId": bank_id,
                "accountType": "AHORROS",
                "accountNumber": account_number,
                "name": nombre,
                "email": "beneficiario@example.com",
                "amount": monto_cop * 100,
                "reference": f"tx-{uuid.uuid4().hex[:8]}",
            }
        ],
    }
    print(f"Enviando {monto_cop:,} COP a {nombre} ({account_number})")
    resp = p.crear_lote(cuerpo)
    if resp.get("_error"):
        return 1
    print(json.dumps(resp, indent=2, ensure_ascii=False)[:1000])
    anotar(
        "envio_cuenta",
        {
            "reference": ref,
            "amount_cop": monto_cop,
            "beneficiario": nombre,
            "cuenta": account_number,
            "respuesta": resp.get("data") or resp,
        },
    )
    return 0


def cmd_resolve(p: Payouts, llave: str) -> int:
    print(f"Resolviendo la llave {llave}")
    resp = p.resolver_llave(llave)
    if resp.get("_error"):
        print(
            "\n  Si el error es 404, la ruta de resolucion no es la que supuse.\n"
            f"  Ajuste RESOLVE_PATH (hoy: {RESOLVE_PATH}) con la de la guia oficial."
        )
        return 1
    print(json.dumps(resp, indent=2, ensure_ascii=False)[:1000])
    anotar("resolucion_llave", {"llave": llave, "respuesta": resp.get("data") or resp})
    print(
        "\n  Compare el titular devuelto contra el comercio al que CREE estar\n"
        "  pagando. Ese contraste es el unico control antes de un envio que\n"
        "  no tiene reversa."
    )
    return 0


def cmd_breb(
    p: Payouts, llave: str, monto_cop: int, account_id: str, fallar: bool, saltar: bool
) -> int:
    if not saltar:
        print("Paso 1 - resolviendo la llave antes de dispersar")
        r = p.resolver_llave(llave)
        if r.get("_error"):
            print(
                "\n[x] no se pudo resolver la llave. Use --saltar-resolucion para\n"
                "    dispersar de todos modos: eso reproduce exactamente el\n"
                "    escenario de riesgo que la PoC quiere estudiar."
            )
            return 1
        print(json.dumps(r, indent=2, ensure_ascii=False)[:600])
        print()

    ref = f"breb-{uuid.uuid4().hex[:10]}"
    cuerpo = {
        "reference": ref,
        "accountId": account_id,
        "paymentType": "OTHER",
        "transactionStatus": "FAILED" if fallar else "APPROVED",
        "transactions": [
            {
                "key": llave,  # la llave reemplaza banco + tipo + numero de cuenta
                "amount": monto_cop * 100,
                "reference": f"tx-{uuid.uuid4().hex[:8]}",
            }
        ],
    }
    print(f"Paso 2 - dispersando {monto_cop:,} COP a la llave {llave}")
    resp = p.crear_lote(cuerpo)
    if resp.get("_error"):
        return 1
    print(json.dumps(resp, indent=2, ensure_ascii=False)[:1000])
    anotar(
        "dispersion_breb",
        {
            "reference": ref,
            "llave": llave,
            "amount_cop": monto_cop,
            "resolucion_omitida": saltar,
            "respuesta": resp.get("data") or resp,
        },
    )
    return 0


def cmd_status(p: Payouts, payout_id: str) -> int:
    resp = p.lote(payout_id)
    if resp.get("_error"):
        return 1
    d = resp.get("data") or resp
    estado = d.get("status", "")
    print(f"  lote      {payout_id}")
    print(f"  estado    {estado}  ({ESTADOS_LOTE.get(estado, '?')})")
    for tx in d.get("transactions", []) or []:
        e = tx.get("status", "")
        print(
            f"    - {cop(tx.get('amount', 0)):>16}  {e:10} ({ESTADOS_TX.get(e, '?')})"
            f"  {tx.get('reference', '')}"
        )
    return 0


def cmd_ledger() -> int:
    if not LEDGER.exists():
        print("Sin registros todavia.")
        return 0
    filas = [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l]
    print(f"{len(filas)} registros\n")
    for f in filas:
        monto = f"{f['amount_cop']:,} COP" if "amount_cop" in f else ""
        print(f"  {f['ts'][:19]}  {f['evento']:20} {monto:>16}  {f.get('llave', '')}")
    return 0


# --------------------------------------------------------------------------- #


def main() -> int:
    cargar_env()
    p_ = argparse.ArgumentParser(description="Envios de dinero en Wompi sandbox")
    sub = p_.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check")

    pf = sub.add_parser("fund")
    pf.add_argument("-a", "--amount", type=int, default=5_000_000)
    pf.add_argument("--account-id")

    pb = sub.add_parser("banks")
    pb.add_argument("--filtro")

    ps = sub.add_parser("send")
    ps.add_argument("-a", "--amount", type=int, required=True)
    ps.add_argument("--account-id", required=True)
    ps.add_argument("--bank-id", required=True)
    ps.add_argument("--account-number", required=True)
    ps.add_argument("--legal-id", default="1000000000")
    ps.add_argument("--name", default="Beneficiario Pruebas")
    ps.add_argument("--fallar", action="store_true")

    pr = sub.add_parser("resolve")
    pr.add_argument("llave")

    pk = sub.add_parser("breb")
    pk.add_argument("llave")
    pk.add_argument("-a", "--amount", type=int, required=True)
    pk.add_argument("--account-id", required=True)
    pk.add_argument("--fallar", action="store_true")
    pk.add_argument("--saltar-resolucion", action="store_true")

    pt = sub.add_parser("status")
    pt.add_argument("payout_id")

    sub.add_parser("ledger")

    a = p_.parse_args()
    if a.cmd == "ledger":
        return cmd_ledger()

    api = Payouts()
    if a.cmd == "check":
        return cmd_check(api)
    if a.cmd == "fund":
        return cmd_fund(api, a.amount, a.account_id)
    if a.cmd == "banks":
        return cmd_banks(api, a.filtro)
    if a.cmd == "send":
        return cmd_send(
            api, a.amount, a.account_id, a.bank_id, a.account_number,
            a.legal_id, a.name, a.fallar,
        )
    if a.cmd == "resolve":
        return cmd_resolve(api, a.llave)
    if a.cmd == "breb":
        return cmd_breb(api, a.llave, a.amount, a.account_id, a.fallar, a.saltar_resolucion)
    if a.cmd == "status":
        return cmd_status(api, a.payout_id)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
