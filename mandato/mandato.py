"""Mandatos de pago firmados. La pieza que ningun riel colombiano entrega.

Wompi te da un `payment_source_id` y con eso ya puedes cobrar. Sin tope, sin
vencimiento, sin ligadura a un monto, a un producto ni a un comercio. Ese
identificador es la llave completa de la cuenta del titular y no trae ninguna
restriccion adherida.

Este archivo construye la restriccion que falta. Un mandato es un documento
firmado por el titular con Ed25519 que dice, de forma verificable y oponible:

    "autorizo cobros contra ESTA fuente, por hasta ESTE monto, sumando no mas
     de ESTE total, hacia ESTOS comercios, hasta ESTA fecha."

En Colombia esto no es decorativo: la Ley 527 de 1999 y el Decreto 2364 de 2012
le dan validez probatoria a la firma electronica. Un mandato firmado es la
evidencia con la que se resuelve una disputa sobre si el titular autorizo o no.

El vocabulario sigue a AP2 (Agent Payments Protocol):

    intent  el titular ausente. Autoriza al agente bajo restricciones.
            Es el caso interesante y el peligroso.
    cart    el titular presente. Firma un carrito concreto. Su hash queda
            dentro del mandato, asi que alterar el carrito despues invalida
            la firma.

    python mandato/mandato.py llaves                        genera el par del titular
    python mandato/mandato.py emitir --help                 emite y firma
    python mandato/mandato.py ver <archivo>                 lo muestra legible
    python mandato/mandato.py verificar <archivo> ...       verificacion en seco

La llave privada del titular no deberia vivir en disco en un despliegue real:
va en el dispositivo del usuario, o en un HSM. Aqui esta en un archivo porque
esto es un banco de pruebas y esconderlo daria una falsa sensacion de rigor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

AQUI = Path(__file__).resolve().parent
BOVEDA = AQUI.parent / "boveda"
# `boveda/secretos/` ya esta en el .gitignore del repo. Todo lo que no debe
# versionarse va ahi; los mandatos firmados, que no tienen secretos, no.
SECRETOS = BOVEDA / "secretos"
LLAVE_PRIVADA = SECRETOS / "titular_ed25519.key"
LLAVE_PUBLICA = SECRETOS / "titular_ed25519.pub"

VERSION = "1"
TIPOS = ("intent", "cart")


# --------------------------------------------------------------------------- #
# Llaves
# --------------------------------------------------------------------------- #


def generar_llaves(forzar: bool = False) -> tuple[Path, Path]:
    SECRETOS.mkdir(parents=True, exist_ok=True)
    if LLAVE_PRIVADA.exists() and not forzar:
        raise SystemExit(
            f"[x] ya existe {LLAVE_PRIVADA.name}. Use --force para reemplazarla.\n"
            "    Reemplazarla invalida todos los mandatos ya firmados."
        )

    priv = Ed25519PrivateKey.generate()
    LLAVE_PRIVADA.write_bytes(
        priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    try:
        os.chmod(LLAVE_PRIVADA, 0o600)
    except OSError:
        pass  # Windows

    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    LLAVE_PUBLICA.write_text(pub_bytes.hex(), encoding="utf-8")
    return LLAVE_PRIVADA, LLAVE_PUBLICA


def cargar_privada() -> Ed25519PrivateKey:
    if not LLAVE_PRIVADA.exists():
        raise SystemExit("[x] no hay llave del titular. Corra `mandato.py llaves`.")
    return Ed25519PrivateKey.from_private_bytes(LLAVE_PRIVADA.read_bytes())


def cargar_publica(hex_pub: str | None = None) -> Ed25519PublicKey:
    if hex_pub is None:
        if not LLAVE_PUBLICA.exists():
            raise SystemExit("[x] no hay llave publica. Corra `mandato.py llaves`.")
        hex_pub = LLAVE_PUBLICA.read_text(encoding="utf-8").strip()
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(hex_pub))


# --------------------------------------------------------------------------- #
# Canonicalizacion y firma
# --------------------------------------------------------------------------- #


def canonico(cuerpo: dict) -> bytes:
    """Serializacion estable. Dos procesos distintos deben producir el mismo
    byte string para el mismo mandato, o la firma no vale nada."""
    return json.dumps(
        cuerpo, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def hash_carrito(items: list[dict], monto_cop: int, comercio: str) -> str:
    """Ata el mandato a un carrito concreto.

    Sin esto, un agente manipulado puede firmar un carrito de 10.000 COP y
    presentar otro de 10.000 COP hacia otro destino. Con esto, cualquier
    alteracion posterior a la firma rompe la verificacion.
    """
    base = canonico({"items": items, "monto_cop": monto_cop, "comercio": comercio})
    return "sha256:" + hashlib.sha256(base).hexdigest()


def emitir(
    payment_source_id: int | str,
    monto_maximo_cop: int,
    tope_vida_cop: int,
    comercios: list[str],
    horas_vigencia: int = 24,
    tipo: str = "intent",
    max_transacciones: int = 0,
    carrito: dict | None = None,
    titular_id: str = "titular-poc",
) -> dict:
    """Construye el mandato y lo firma con la llave privada del titular."""
    if tipo not in TIPOS:
        raise SystemExit(f"[x] tipo invalido: {tipo}. Use uno de {TIPOS}.")
    if tipo == "cart" and carrito is None:
        raise SystemExit("[x] un mandato de tipo 'cart' exige un carrito.")
    if monto_maximo_cop <= 0 or tope_vida_cop <= 0:
        raise SystemExit("[x] los topes deben ser positivos.")
    if tope_vida_cop < monto_maximo_cop:
        raise SystemExit("[x] el tope de vida no puede ser menor al tope por cobro.")

    priv = cargar_privada()
    pub_hex = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()

    ahora = datetime.now(timezone.utc)
    cuerpo = {
        "version": VERSION,
        "mandato_id": f"mnd-{uuid.uuid4().hex[:16]}",
        "tipo": tipo,
        "titular": {"id": titular_id, "llave_publica": pub_hex},
        "payment_source_id": str(payment_source_id),
        "limites": {
            "monto_maximo_cop": monto_maximo_cop,
            "tope_vida_cop": tope_vida_cop,
            "comercios_permitidos": sorted(comercios),
            "max_transacciones": max_transacciones,  # 0 = sin limite de conteo
        },
        "vigencia": {
            "desde": ahora.isoformat(timespec="seconds"),
            "hasta": (ahora + timedelta(hours=horas_vigencia)).isoformat(
                timespec="seconds"
            ),
        },
        "humano_presente": tipo == "cart",
        "carrito_hash": (
            hash_carrito(carrito["items"], carrito["monto_cop"], carrito["comercio"])
            if carrito
            else None
        ),
        "nonce": uuid.uuid4().hex,
    }

    firma = priv.sign(canonico(cuerpo))
    return {"cuerpo": cuerpo, "firma": firma.hex(), "algoritmo": "Ed25519"}


# --------------------------------------------------------------------------- #
# Verificacion
# --------------------------------------------------------------------------- #


class Resultado:
    """El desenlace de verificar un mandato, con el detalle de cada control.

    Importa que sea explicito: en una PoC de fraude, saber CUAL control atajo
    el intento vale mas que saber que el intento no paso.
    """

    def __init__(self) -> None:
        self.controles: list[tuple[str, bool, str]] = []

    def check(self, nombre: str, ok: bool, detalle: str = "") -> None:
        self.controles.append((nombre, bool(ok), detalle))

    @property
    def autorizado(self) -> bool:
        return all(ok for _, ok, _ in self.controles)

    @property
    def motivos(self) -> list[str]:
        return [
            f"{n}: {d}" if d else n for n, ok, d in self.controles if not ok
        ]

    def imprimir(self) -> None:
        for nombre, ok, detalle in self.controles:
            marca = "ok " if ok else "NO "
            print(f"  [{marca}] {nombre:26} {detalle}")
        print()
        if self.autorizado:
            print("  AUTORIZADO")
        else:
            print("  RECHAZADO")
            for m in self.motivos:
                print(f"    - {m}")


def verificar(
    mandato: dict,
    monto_cop: int,
    comercio: str,
    acumulado_cop: int = 0,
    transacciones_previas: int = 0,
    nonces_usados: set[str] | None = None,
    carrito: dict | None = None,
    ahora: datetime | None = None,
) -> Resultado:
    """Los siete controles. Ninguno es opcional.

    Wompi no valida nada de esto: para Wompi, cualquier POST con un
    payment_source_id valido y una firma de integridad correcta es un cobro
    legitimo. La superficie de fraude de la PoC es exactamente del tamano de
    lo que este metodo decida no revisar.
    """
    r = Resultado()
    nonces_usados = nonces_usados or set()
    ahora = ahora or datetime.now(timezone.utc)

    cuerpo = mandato.get("cuerpo") or {}
    firma_hex = mandato.get("firma") or ""

    # 1. Firma
    try:
        pub = cargar_publica(cuerpo["titular"]["llave_publica"])
        pub.verify(bytes.fromhex(firma_hex), canonico(cuerpo))
        r.check("firma", True, "Ed25519 valida")
    except (InvalidSignature, KeyError, ValueError, TypeError) as e:
        r.check("firma", False, f"invalida ({type(e).__name__})")
        return r  # sin firma valida el resto del documento no significa nada

    # 2. Vigencia
    desde = datetime.fromisoformat(cuerpo["vigencia"]["desde"])
    hasta = datetime.fromisoformat(cuerpo["vigencia"]["hasta"])
    vigente = desde <= ahora <= hasta
    r.check(
        "vigencia",
        vigente,
        "vigente" if vigente else f"fuera de ventana (vence {hasta.isoformat()})",
    )

    lim = cuerpo["limites"]

    # 3. Tope por cobro
    dentro = monto_cop <= lim["monto_maximo_cop"]
    r.check(
        "tope_por_cobro",
        dentro,
        f"{monto_cop:,} <= {lim['monto_maximo_cop']:,}"
        if dentro
        else f"{monto_cop:,} excede {lim['monto_maximo_cop']:,}",
    )

    # 4. Tope acumulado. Ataja la escalada por goteo: muchos cobros
    #    individualmente legitimos que suman una cifra que nadie autorizo.
    total = acumulado_cop + monto_cop
    dentro_vida = total <= lim["tope_vida_cop"]
    r.check(
        "tope_acumulado",
        dentro_vida,
        f"{total:,} <= {lim['tope_vida_cop']:,}"
        if dentro_vida
        else f"{total:,} excede {lim['tope_vida_cop']:,}",
    )

    # 5. Lista blanca de comercios. El control contra inyeccion de prompt:
    #    el agente puede ser convencido de comprar en otro lado, el mandato no.
    permitido = comercio in lim["comercios_permitidos"]
    r.check(
        "comercio_permitido",
        permitido,
        comercio if permitido else f"'{comercio}' no esta en la lista blanca",
    )

    # 6. Conteo de transacciones
    if lim.get("max_transacciones"):
        bajo_conteo = transacciones_previas < lim["max_transacciones"]
        r.check(
            "max_transacciones",
            bajo_conteo,
            f"{transacciones_previas}/{lim['max_transacciones']}",
        )

    # 7. Nonce. Sin esto, un mandato capturado se puede reproducir para
    #    siempre dentro de su ventana de vigencia.
    fresco = cuerpo["nonce"] not in nonces_usados
    r.check("nonce", fresco, "sin consumir" if fresco else "ya consumido (replay)")

    # 8. Carrito, solo para mandatos de tipo cart
    if cuerpo.get("carrito_hash"):
        if carrito is None:
            r.check("carrito", False, "el mandato exige carrito y no se presento")
        else:
            esperado = hash_carrito(
                carrito["items"], carrito["monto_cop"], carrito["comercio"]
            )
            coincide = esperado == cuerpo["carrito_hash"]
            r.check(
                "carrito",
                coincide,
                "hash coincide" if coincide else "el carrito fue alterado tras la firma",
            )

    return r


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _guardar(mandato: dict, destino: Path | None) -> Path:
    BOVEDA.mkdir(parents=True, exist_ok=True)
    destino = destino or BOVEDA / f"{mandato['cuerpo']['mandato_id']}.json"
    destino.write_text(
        json.dumps(mandato, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return destino


def _cargar(ruta: str) -> dict:
    p = Path(ruta)
    if not p.exists():
        p = BOVEDA / ruta
    if not p.exists():
        raise SystemExit(f"[x] no encuentro el mandato: {ruta}")
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description="Mandatos de pago firmados")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("llaves", help="genera el par Ed25519 del titular")
    pl.add_argument("--force", action="store_true")

    pe = sub.add_parser("emitir", help="emite y firma un mandato")
    pe.add_argument("--payment-source-id", required=True)
    pe.add_argument("--monto-max", type=int, required=True, help="tope por cobro, COP")
    pe.add_argument("--tope-vida", type=int, required=True, help="tope acumulado, COP")
    pe.add_argument(
        "--comercio", action="append", required=True, help="repetible; lista blanca"
    )
    pe.add_argument("--horas", type=int, default=24)
    pe.add_argument("--tipo", choices=TIPOS, default="intent")
    pe.add_argument("--max-transacciones", type=int, default=0)
    pe.add_argument("--salida")

    pv = sub.add_parser("ver", help="muestra un mandato")
    pv.add_argument("archivo")

    pc = sub.add_parser("verificar", help="verificacion en seco, sin cobrar")
    pc.add_argument("archivo")
    pc.add_argument("--monto", type=int, required=True)
    pc.add_argument("--comercio", required=True)
    pc.add_argument("--acumulado", type=int, default=0)

    a = p.parse_args()

    if a.cmd == "llaves":
        priv, pub = generar_llaves(a.force)
        print(f"  privada  {priv}")
        print(f"  publica  {pub}")
        print(f"  hex      {pub.read_text(encoding='utf-8').strip()}")
        print(
            "\n  En produccion esta llave privada vive en el dispositivo del\n"
            "  titular, no aqui. Que este en disco es una decision de banco de\n"
            "  pruebas, no un descuido."
        )
        return 0

    if a.cmd == "emitir":
        m = emitir(
            payment_source_id=a.payment_source_id,
            monto_maximo_cop=a.monto_max,
            tope_vida_cop=a.tope_vida,
            comercios=a.comercio,
            horas_vigencia=a.horas,
            tipo=a.tipo,
            max_transacciones=a.max_transacciones,
        )
        destino = _guardar(m, Path(a.salida) if a.salida else None)
        c = m["cuerpo"]
        print(f"Mandato {c['mandato_id']} emitido")
        print(f"  tipo              {c['tipo']} (humano_presente={c['humano_presente']})")
        print(f"  fuente            {c['payment_source_id']}")
        print(f"  tope por cobro    {c['limites']['monto_maximo_cop']:,} COP")
        print(f"  tope acumulado    {c['limites']['tope_vida_cop']:,} COP")
        print(f"  comercios         {', '.join(c['limites']['comercios_permitidos'])}")
        print(f"  vence             {c['vigencia']['hasta']}")
        print(f"  archivo           {destino}")
        return 0

    if a.cmd == "ver":
        print(json.dumps(_cargar(a.archivo), indent=2, ensure_ascii=False))
        return 0

    if a.cmd == "verificar":
        r = verificar(
            _cargar(a.archivo),
            monto_cop=a.monto,
            comercio=a.comercio,
            acumulado_cop=a.acumulado,
        )
        print(f"Verificando cobro de {a.monto:,} COP hacia '{a.comercio}'\n")
        r.imprimir()
        return 0 if r.autorizado else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
