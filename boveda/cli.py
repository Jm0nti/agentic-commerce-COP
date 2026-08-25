"""Manejo de la boveda desde la linea de comandos.

FASE A -- el titular autoriza, una sola vez

    python -m boveda.cli --modo produccion preflight
    python -m boveda.cli --modo produccion enrolar --telefono 3001234567
    python -m boveda.cli --modo produccion fuentes
    python -m boveda.cli --modo produccion revocar <payment_source_id>

FASE B -- el agente cobra, sin el titular

    python -m boveda.cli llaves                          genera el par ed25519
    python -m boveda.cli emitir --monto 8000             emite un mandato
    python -m boveda.cli ejecutar <mandato_id> -m 8000   ejecuta una intencion
    python -m boveda.cli listar                          mandatos y consumo
    python -m boveda.cli recibos                         historial

Para probar el control apagado, que es el experimento:

    python -m boveda.cli ejecutar <id> -m 15000 --sin-mandato

El mandato autoriza 8.000 y la intencion pide 15.000. Con el control encendido
la boveda lo detiene; con `--sin-mandato` lo deja pasar y Wompi lo aprueba. La
diferencia entre las dos corridas es el efecto del control.

Ambos casos siguen sujetos a los topes duros de `nucleo.py`.

SOBRE `--modo produccion`
------------------------
Mueve dinero real. El modo tiene que coincidir con el prefijo de la llave, y
toda accion que entregue o gaste dinero pide confirmacion escrita. `--si` la
salta, y existe solo para guiones; escribirlo a mano es admitir que se sabe lo
que se hace.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .enrolamiento import RegistroFuentes, enrolar_nequi, preflight, revocar
from .mandato import Intencion, emitir
from .nucleo import (
    LIMITE_DURO_DIA_COP,
    LIMITE_DURO_TX_COP,
    Boveda,
    BovedaError,
    ClienteWompi,
    perfil_pagador,
)

RAIZ = Path(__file__).resolve().parent.parent
SECRETOS = RAIZ / "boveda" / "secretos"
LLAVE_SK = SECRETOS / "firma.sk"
LLAVE_PK = SECRETOS / "firma.pk"
ESTADO = SECRETOS / "estado.json"
FUENTES = SECRETOS / "fuentes.json"
RECIBOS = RAIZ / "boveda" / "recibos.jsonl"


def cargar_env() -> None:
    env = RAIZ / ".env"
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


def llaves() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    if not LLAVE_SK.exists():
        raise SystemExit("[x] no hay llaves. Corra `python -m boveda.cli llaves`")
    sk = Ed25519PrivateKey.from_private_bytes(LLAVE_SK.read_bytes())
    return sk, sk.public_key()


def anotar(recibo: dict) -> None:
    with RECIBOS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(recibo, ensure_ascii=False) + "\n")


def abrir(modo: str, exigir: bool) -> Boveda:
    sk, pk = llaves()
    return Boveda(sk, pk, ESTADO, modo=modo, exigir_mandato=exigir)


def registro() -> RegistroFuentes:
    return RegistroFuentes(FUENTES)


def confirmar(modo: str, titulo: str, lineas: list[str], saltar: bool) -> bool:
    """Nada de dinero real sin que alguien lo escriba."""
    if modo != "produccion":
        return True
    if saltar:
        print("  [!] confirmacion saltada con --si\n")
        return True
    print()
    print("  " + "=" * 68)
    print(f"  PRODUCCION -- {titulo}")
    print("  " + "=" * 68)
    for l in lineas:
        print(f"  {l}")
    print("  " + "=" * 68)
    try:
        resp = input("  Escriba PRODUCCION para continuar (cualquier otra cosa aborta): ")
    except EOFError:
        print("  [x] sin terminal interactiva. Use --si si sabe lo que hace.")
        return False
    print()
    return resp.strip() == "PRODUCCION"


# --------------------------------------------------------------------------- #
# Fase A
# --------------------------------------------------------------------------- #


def cmd_preflight(a) -> int:
    """Todo lo verificable antes de involucrar a un humano con un telefono."""
    try:
        cliente = ClienteWompi(a.modo)
        info = preflight(cliente)
    except BovedaError as exc:
        print(f"[x] {exc}")
        return 1

    print(f"Comercio ({info['modo']})")
    print(f"  url                {info['url']}")
    print(f"  nombre             {info['nombre']}")
    print(f"  razon social       {info['razon_social']}")
    print(f"  metodos activos    {', '.join(info['metodos']) or '(ninguno reportado)'}")
    print()
    print(f"  Nequi              {'habilitado' if info['nequi_habilitado'] else 'NO habilitado'}")
    print(f"  Tarjeta            {'habilitada' if info['tarjeta_habilitada'] else 'NO habilitada'}")

    print("\nLo que el titular esta aceptando")
    print(f"  terminos           {info['permalink_terminos']}")
    print(f"  datos personales   {info['permalink_datos']}")
    print(
        "\n  Estos dos enlaces son el contrato que la boveda acepta en nombre del\n"
        "  titular en cada llamada. Leerlos una vez, con dinero real de por medio,\n"
        "  deja de ser un detalle: es la diferencia entre un consentimiento y una\n"
        "  casilla marcada por software."
    )

    # El perfil del pagador no es cosmetico: es casi todo lo que el motor
    # antifraude tiene para decidir si un cobro sin titular presente es
    # legitimo. Vacio, el AFE decide a ciegas -- y a ciegas rechaza.
    email, pagador = perfil_pagador()
    print("\nPerfil del pagador (lo que ve el antifraude)")
    print(f"  correo             {email}")
    if pagador:
        for k, v in pagador.items():
            print(f"  {k:18} {v}")
    else:
        print("  customer_data      (vacio)")

    problemas = []
    if email.endswith(("example.com", "example.org", "example.net")):
        problemas.append(
            "el correo esta en un dominio reservado por la RFC 2606: no existe y\n"
            "      nunca va a entregar. Defina PAGADOR_EMAIL en el .env"
        )
    if not pagador:
        problemas.append(
            "sin customer_data el antifraude no tiene con que distinguir este\n"
            "      cobro de uno automatizado por un tercero. Defina PAGADOR_NOMBRE,\n"
            "      PAGADOR_TELEFONO y PAGADOR_DOCUMENTO en el .env"
        )
    for prob in problemas:
        print(f"\n  [!] {prob}")

    fs = registro().listar(a.modo)
    vivas = [f for f in fs if f["estado"] == "AVAILABLE"]
    print(f"\nFuentes registradas en '{a.modo}': {len(fs)} ({len(vivas)} vivas)")

    if not info["nequi_habilitado"]:
        print(
            "\n[!] Nequi no aparece habilitado. El enrolamiento va a fallar en\n"
            "    silencio: el token se queda en PENDING y el push nunca llega.\n"
            "    Actívelo en el plan Avanzado Agregador antes de seguir."
        )
        return 1

    print("\n[ok] listo para enrolar.")
    return 0


def cmd_enrolar(a) -> int:
    """Fase A. El titular recibe un push y autoriza. Aqui no se cobra nada."""
    try:
        cliente = ClienteWompi(a.modo)
    except BovedaError as exc:
        print(f"[x] {exc}")
        return 1

    if not confirmar(
        a.modo,
        "enrolamiento de una cuenta Nequi real",
        [
            f"telefono          {a.telefono}",
            f"correo            {a.email}",
            "",
            "No se cobra nada en este paso. Lo que se entrega es la autorizacion",
            "para cobrar despues sin que usted este presente, sin tope propio y",
            "sin vencimiento. Se revoca con `revocar <id>`.",
        ],
        a.si,
    ):
        print("  Abortado.")
        return 1

    puntos = {"activos": False}

    def narrar(etapa: str, detalle: str) -> None:
        if etapa == "sondeo":
            print(".", end="", flush=True)
            puntos["activos"] = True
            return
        if puntos["activos"]:
            print()
            puntos["activos"] = False
        if etapa == "push":
            print(f"\n  >>> {detalle.upper()}")
            print("      esperando", end="", flush=True)
            return
        print(f"  {etapa:14} {detalle}")

    try:
        fuente = enrolar_nequi(
            cliente,
            telefono=a.telefono,
            email=a.email,
            registro=registro(),
            espera_seg=a.espera,
            al_avanzar=narrar,
        )
    except BovedaError as exc:
        print(f"\n[x] {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n[x] interrumpido. Si ya acepto el push, el token puede haber")
        print("    quedado APPROVED sin fuente creada. Vuelva a correr `enrolar`.")
        return 1

    print(f"\nFuente {fuente.payment_source_id} creada  ({fuente.estado})")
    print(f"  tipo               {fuente.tipo}")
    print(f"  modo               {fuente.modo}")
    print(f"  cuenta             {fuente.referencia_publica}")
    print(f"  registrada en      boveda/secretos/fuentes.json")
    print(
        "\n  Desde aqui se puede cobrar sin el titular. Ese es exactamente el\n"
        "  hueco que la boveda existe para tapar. Siguiente:\n"
        f"\n    python -m boveda.cli --modo {a.modo} emitir --monto 2000"
    )
    return 0


def cmd_fuentes(a) -> int:
    fs = registro().listar(a.modo)
    if not fs:
        print(f"Sin fuentes registradas en modo '{a.modo}'.")
        return 0
    print(f"{len(fs)} fuente(s) en modo '{a.modo}'\n")
    print(f"  {'id':>10}  {'tipo':8} {'estado':11} {'cuenta':12} creada")
    print("  " + "-" * 62)
    for f in fs:
        print(
            f"  {f['payment_source_id']:>10}  {f['tipo']:8} {f['estado']:11} "
            f"{f['referencia_publica']:12} {f['creada_en'][:19]}"
        )
    return 0


def cmd_revocar(a) -> int:
    try:
        cliente = ClienteWompi(a.modo)
    except BovedaError as exc:
        print(f"[x] {exc}")
        return 1

    if not confirmar(
        a.modo,
        "revocacion de una fuente de pago",
        [
            f"fuente            {a.payment_source_id}",
            "",
            "Despues de esto ningun mandato existente podra cobrar contra ella.",
            "Es irreversible: para volver a cobrar hay que enrolar de nuevo.",
        ],
        a.si,
    ):
        print("  Abortado.")
        return 1

    try:
        estado = revocar(cliente, a.payment_source_id, registro())
    except BovedaError as exc:
        print(f"[x] {exc}")
        return 1

    print(f"  fuente {a.payment_source_id} -> {estado}")
    return 0


# --------------------------------------------------------------------------- #
# Fase B
# --------------------------------------------------------------------------- #


def cmd_llaves() -> int:
    if LLAVE_SK.exists():
        print(f"Ya existen en {SECRETOS.name}/. Borrelas a mano si quiere rotarlas.")
        return 0
    SECRETOS.mkdir(parents=True, exist_ok=True)
    sk = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    LLAVE_SK.write_bytes(
        sk.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    LLAVE_PK.write_bytes(
        sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    print(f"Par ed25519 generado en {SECRETOS.name}/")
    print("  firma.sk  la llave del titular. No versionar.")
    print("  firma.pk  con esta se verifican los mandatos.")
    return 0


def _fuente_por_defecto(modo: str) -> int | None:
    """La fuente viva mas reciente del modo actual.

    Nunca cruza modos. Antes esto leia el cache del banco de pruebas, que en
    produccion habria apuntado a un id de sandbox -- o peor, a uno que existe
    en los dos lados y pertenece a otro.
    """
    vivas = [f for f in RegistroFuentes(FUENTES).listar(modo) if f["estado"] == "AVAILABLE"]
    if vivas:
        return int(sorted(vivas, key=lambda f: f["creada_en"])[-1]["payment_source_id"])
    if modo == "sandbox":
        cache = RAIZ / "wompi_lab" / "source.json"
        if cache.exists():
            return int(json.loads(cache.read_text(encoding="utf-8"))["payment_source_id"])
    return None


def cmd_emitir(a) -> int:
    sk, _ = llaves()
    fuente = a.fuente
    if fuente is None:
        fuente = _fuente_por_defecto(a.modo)
        if fuente is None:
            print(
                f"[x] no hay fuente viva en modo '{a.modo}'. Pase --fuente, o "
                f"enrole una:\n\n    python -m boveda.cli --modo {a.modo} enrolar "
                "--telefono 3001234567"
            )
            return 1
        print(f"Usando la fuente {fuente} (modo {a.modo})")
    elif a.modo == "produccion" and not RegistroFuentes(FUENTES).pertenece("produccion", fuente):
        print(
            f"[!] la fuente {fuente} no esta registrada en produccion. Si viene de\n"
            "    sandbox, el mandato apuntara a una cuenta que no es la que cree."
        )

    m = emitir(
        titular=a.titular,
        fuente_pago=fuente,
        comercio=a.comercio,
        monto_max_cop=a.monto,
        sk=sk,
        tope_total_cop=a.tope_total,
        usos_max=a.usos,
        vigencia_min=a.vigencia,
        categorias=a.categoria or [],
    )
    abrir(a.modo, True).registrar(m)

    print(f"\nMandato {m.mandato_id}")
    print(f"  titular      {m.titular}")
    print(f"  comercio     {m.comercio}")
    print(f"  fuente       {m.fuente_pago}  ({a.modo})")
    print(f"  por tx       {m.monto_max_cop:,} COP")
    print(f"  tope total   {m.tope_total_cop:,} COP")
    print(f"  usos max     {m.usos_max}")
    print(f"  expira       {m.expira_en[:19]}")
    print(f"  firma        {m.firma[:32]}...")
    return 0


def cmd_ejecutar(a) -> int:
    if not confirmar(
        a.modo,
        "cobro con dinero real",
        [
            f"mandato           {a.mandato_id}",
            f"monto             {a.monto:,} COP",
            f"comercio          {a.comercio}",
            f"verificacion      {'APAGADA' if a.sin_mandato else 'encendida'}",
            "",
            f"Topes duros vigentes: {LIMITE_DURO_TX_COP:,} COP/tx, "
            f"{LIMITE_DURO_DIA_COP:,} COP/dia.",
        ],
        a.si,
    ):
        print("  Abortado.")
        return 1

    bov = abrir(a.modo, exigir=not a.sin_mandato)
    intencion = Intencion(
        mandato_id=a.mandato_id,
        comercio=a.comercio,
        sku=a.sku,
        monto_cop=a.monto,
        descripcion=a.descripcion,
        categoria=a.categoria,
    )
    if a.sin_mandato:
        print("  [!] verificacion de mandato APAGADA (brazo sin control)\n")

    try:
        r = bov.ejecutar(intencion)
    except BovedaError as exc:
        print(f"[x] {exc}")
        return 1

    anotar(r.to_json())

    if r.violaciones:
        print("Violaciones detectadas:")
        for v in r.violaciones:
            print(f"  - {v['tipo']:26} {v['detalle']}")
        print()

    print(f"  ejecutado    {r.ejecutado}")
    print(f"  motivo       {r.motivo}")
    if r.transaction_id:
        print(f"  transaccion  {r.transaction_id}")
        print(f"  estado       {r.estado_wompi}")
    if r.afe_decision:
        print(f"  antifraude   {r.afe_decision}")
    if r.status_message:
        print(f"  mensaje      {r.status_message}")

    if r.detenido_por_antifraude:
        print(
            "\n  Lo detuvo el motor antifraude de la pasarela (AFE), no el mandato.\n"
            "  El mandato se cumplio: no hubo violaciones y la boveda dejo pasar el\n"
            "  cobro. El unico control que actuo es el que el comercio no puede ver,\n"
            "  ni configurar, ni explicarle al titular.\n"
            "\n  Anotelo como hallazgo, no como bug. Detalle en docs/decline-afe.md"
        )
    if r.aprobado_pese_a_violacion:
        print(
            "\n  La pasarela aprobo un cobro que el mandato firmado no autorizaba.\n"
            "  Ese es el hallazgo, con recibo."
        )
    return 0


def cmd_diagnostico(a) -> int:
    """Lo que Wompi dice de una transaccion, sin recortes.

    Existe porque el recibo resumia demasiado: un DECLINED sin `status_message`
    ni `afe_decision` obliga a abrir el debugger del dashboard para leer algo
    que la API ya habia contestado.
    """
    try:
        cliente = ClienteWompi(a.modo)
        d = cliente.consultar(a.transaction_id)
    except BovedaError as exc:
        print(f"[x] {exc}")
        return 1

    metodo = d.get("payment_method") or {}
    centavos = d.get("amount_in_cents") or 0

    print(f"Transaccion {d.get('id')}  ({a.modo})")
    print(f"  estado             {d.get('status')}")
    print(f"  mensaje            {d.get('status_message')}")
    print(f"  antifraude (AFE)   {metodo.get('afe_decision')}")
    print(f"  monto              {centavos // 100:,} COP")
    print(f"  referencia         {d.get('reference')}")
    print(f"  metodo             {d.get('payment_method_type')}")
    print(f"  fuente de pago     {d.get('payment_source_id')}")
    print(f"  creada             {d.get('created_at')}")
    print(f"  finalizada         {d.get('finalized_at')}")

    print("\nLo que la pasarela recibio del comercio")
    for campo in ("customer_email", "customer_data", "billing_data", "redirect_url"):
        valor = d.get(campo)
        marca = "" if valor else "   <-- vacio"
        print(f"  {campo:18} {valor}{marca}")

    correo = d.get("customer_email") or ""
    if correo.endswith(("example.com", "example.org", "example.net")):
        print(
            "\n[!] El correo esta en un dominio reservado por la RFC 2606: no existe\n"
            "    y nunca va a entregar. Para un motor antifraude es indistinguible\n"
            "    de un correo desechable. Ponga PAGADOR_EMAIL en el .env."
        )
    if not d.get("customer_data"):
        print(
            "\n[!] Sin customer_data el motor antifraude no tiene con que distinguir\n"
            "    este cobro de uno automatizado por un tercero. Llene PAGADOR_NOMBRE,\n"
            "    PAGADOR_TELEFONO y PAGADOR_DOCUMENTO en el .env.\n"
            "    (billing_data lo llena la pasarela, no el comercio: que este vacio\n"
            "     en un cobro contra fuente de pago es normal.)"
        )

    if (metodo.get("afe_decision") or "").upper() == "DECLINE":
        print(
            "\n  Veredicto: lo rechazo el antifraude de Wompi, no Nequi ni el saldo.\n"
            "  Ese motor no es visible ni configurable por el comercio; solo Wompi\n"
            "  puede decir que regla salto. Ver docs/decline-afe.md"
        )

    if a.json:
        print("\n" + json.dumps(d, indent=2, ensure_ascii=False))
    return 0


def cmd_listar(a) -> int:
    """Que mandatos hay y cual sirve todavia.

    Los defaults de `emitir` son estrechos a proposito -- un uso, una hora --
    asi que la respuesta a "cual puedo ejecutar" casi siempre es "ninguno,
    emita otro". Mejor que lo diga la herramienta a que lo diga un DECLINED.
    """
    bov = abrir(a.modo, True)
    mandatos = bov.estado.get("mandatos", {})
    modos = bov.estado.get("modos") or {}
    if not mandatos:
        print("Sin mandatos.")
        return 0

    ahora = datetime.now(timezone.utc)
    usables = 0
    for mid, crudo in mandatos.items():
        c = bov.estado["consumo"].get(mid, {})
        emitido_en = modos.get(mid)
        usos, tope_usos = c.get("usos", 0), crudo["usos_max"]
        acum = c.get("acumulado_cop", 0)

        if emitido_en and emitido_en != a.modo:
            estado = f"otro ambiente ({emitido_en})"
        elif datetime.fromisoformat(crudo["expira_en"]) < ahora:
            estado = "vencido"
        elif usos >= tope_usos:
            estado = "usos agotados"
        elif acum >= crudo["tope_total_cop"]:
            estado = "tope agotado"
        else:
            estado = "usable"
            usables += 1

        marca = "  " if estado == "usable" else "x "
        print(
            f"  {marca}{mid}  {crudo['comercio']:16} "
            f"{crudo['monto_max_cop']:>8,}/tx  "
            f"usos {usos}/{tope_usos}  "
            f"acum {acum:,}/{crudo['tope_total_cop']:,}  {estado}"
        )

    print(f"\n  {usables} usable(s) en modo '{a.modo}'")
    if not usables:
        print(
            f"    Emita uno nuevo:  python -m boveda.cli --modo {a.modo} "
            "emitir --monto 2000"
        )
    print(f"\n  gastado hoy  {bov.estado.get('gastado_dia_cop', 0):,} COP")
    print(f"  topes duros  {LIMITE_DURO_TX_COP:,}/tx  {LIMITE_DURO_DIA_COP:,}/dia")
    print(
        "    (el gasto diario es compartido entre sandbox y produccion: una\n"
        "     corrida de pruebas consume el cupo real. Es conservador a proposito.)"
    )
    return 0


def cmd_recibos() -> int:
    if not RECIBOS.exists():
        print("Sin recibos.")
        return 0
    filas = [json.loads(l) for l in RECIBOS.read_text(encoding="utf-8").splitlines() if l]
    print(f"{len(filas)} recibos\n")
    for f in filas:
        if f["aprobado_pese_a_violacion"]:
            marca = "  <-- aprobado con violacion"
        elif (f.get("afe_decision") or "").upper() == "DECLINE":
            marca = "  <-- lo detuvo el antifraude, no el mandato"
        else:
            marca = ""
        modo = f.get("modo", "?")[:4]
        print(
            f"  [{modo}] {f['intencion']['monto_cop']:>9,} COP  {f['motivo']:20} "
            f"{f.get('transaction_id') or '':28}{marca}"
        )

    afe = sum(1 for f in filas if (f.get("afe_decision") or "").upper() == "DECLINE")
    if afe:
        print(
            f"\n  {afe} de {len(filas)} detenidos por el antifraude de la pasarela.\n"
            "  Ese control no lo puso la boveda y no se puede medir su umbral."
        )
    return 0


# --------------------------------------------------------------------------- #


def main() -> int:
    cargar_env()
    p = argparse.ArgumentParser(description="Boveda de mandatos")
    p.add_argument("--modo", default="sandbox", choices=["sandbox", "produccion"])
    p.add_argument(
        "--si",
        action="store_true",
        help="salta la confirmacion de produccion. Solo para guiones.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight", help="verifica el comercio antes de enrolar")

    pn = sub.add_parser("enrolar", help="Fase A: el titular autoriza por push")
    pn.add_argument("--telefono", required=True, help="celular Nequi, 10 digitos")
    pn.add_argument("--email", default="titular+poc@example.com")
    pn.add_argument("--espera", type=int, default=300, help="segundos de espera al push")

    sub.add_parser("fuentes", help="fuentes registradas en este modo")

    pr = sub.add_parser("revocar", help="apaga una fuente de pago")
    pr.add_argument("payment_source_id", type=int)

    sub.add_parser("llaves")

    pe = sub.add_parser("emitir")
    pe.add_argument("--titular", default="titular_0001")
    pe.add_argument("--comercio", default="tienda_demo")
    pe.add_argument("--monto", type=int, required=True, help="maximo por transaccion")
    pe.add_argument("--tope-total", type=int)
    pe.add_argument("--usos", type=int, default=1)
    pe.add_argument("--vigencia", type=int, default=60, help="minutos")
    pe.add_argument("--fuente", type=int)
    pe.add_argument("--categoria", action="append")

    px = sub.add_parser("ejecutar")
    px.add_argument("mandato_id")
    px.add_argument("-m", "--monto", type=int, required=True)
    px.add_argument("--comercio", default="tienda_demo")
    px.add_argument("--sku", default="sku-demo")
    px.add_argument("--descripcion", default="")
    px.add_argument("--categoria", default="")
    px.add_argument("--sin-mandato", action="store_true")

    pd = sub.add_parser("diagnostico", help="lo que Wompi dice de una transaccion")
    pd.add_argument("transaction_id")
    pd.add_argument("--json", action="store_true", help="ademas, el objeto crudo")

    sub.add_parser("listar")
    sub.add_parser("recibos")

    a = p.parse_args()

    if a.modo == "produccion" and a.cmd in ("enrolar", "ejecutar", "revocar"):
        print("\n  *** MODO PRODUCCION -- esto opera sobre cuentas reales ***")

    if a.cmd == "preflight":
        return cmd_preflight(a)
    if a.cmd == "enrolar":
        return cmd_enrolar(a)
    if a.cmd == "fuentes":
        return cmd_fuentes(a)
    if a.cmd == "revocar":
        return cmd_revocar(a)
    if a.cmd == "llaves":
        return cmd_llaves()
    if a.cmd == "emitir":
        return cmd_emitir(a)
    if a.cmd == "ejecutar":
        return cmd_ejecutar(a)
    if a.cmd == "diagnostico":
        return cmd_diagnostico(a)
    if a.cmd == "listar":
        return cmd_listar(a)
    if a.cmd == "recibos":
        return cmd_recibos()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
