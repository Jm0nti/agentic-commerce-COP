"""`python -m agora.entradas.cli <comando>`.

Fase A -- el titular autoriza, una sola vez

    python -m agora.entradas.cli enrolar --telefono 3001234567 --titular tit_1
    python -m agora.entradas.cli fuentes tit_1
    python -m agora.entradas.cli revocar --id-externo simsrc_... --titular tit_1

Navegar el catalogo simulado

    python -m agora.entradas.cli comercios
    python -m agora.entradas.cli productos com_placeholder_tecnox
    python -m agora.entradas.cli producto prd_...

Fase B -- armar, firmar y cobrar

Dos caminos para llegar al mismo lugar (un `Mandato` firmado), segun quien
arma la propuesta:

  1. El humano opera la CLI de punta a punta -- `emitir` arma el carrito Y
     firma en un solo comando, porque no hace falta separar "propongo" de
     "autorizo" cuando los dos pasos los hace la misma persona:

         python -m agora.entradas.cli emitir com_placeholder_tecnox tit_1 \\
             --item prd_audifonos:1 --item prd_mouse:2

  2. El agente arma la propuesta en una charla de `chat` (otro proceso) y
     el titular la autoriza el mismo, en su propia terminal, con `firmar`
     -- el `propuesta_id` que hace falta ya se lo mostro el agente
     (`composicion/agente.py:armar_carrito`, etapa 6):

         python -m agora.entradas.cli firmar <propuesta_id> tit_1

En los dos casos, lo que sigue es igual:

    python -m agora.entradas.cli pagar <mandato_id> <carrito_id>
    python -m agora.entradas.cli retomar <intencion_id> <mandato_id> <carrito_id>
    python -m agora.entradas.cli estado <intencion_id>
    python -m agora.entradas.cli mandatos

`retomar` hace falta seguido: `EmitirMandato` corta el mandato exacto al
carrito (un solo uso, `monto_max` igual al total), y eso dispara casi
siempre las senales blandas de `dominio/mandato/politica.py` -- `pagar`
devuelve `esperando_confirmacion_humana` en vez de aprobar directo.

Chat con el agente (necesita DEEPSEEK_API_KEY)

    python -m agora.entradas.cli chat

El chat solo puede PROPONER (`armar_carrito`) y, ya con un mandato_id en
mano, PAGAR (`pagar`) -- nunca firmar (`agente/herramientas.py`, la
frontera). Autorizar la propuesta es el comando `firmar` de arriba, corrido
por la persona en otra terminal.

Variables de entorno: se leen de `.env` en la raiz del repo si existe
(`python-dotenv`), y despues de `os.environ` -- mismo orden que
`boveda/cli.py:cargar_env`. Ver `docs/variables-de-entorno.md`.

`estado <intencion_id>` solo encuentra algo entre procesos con
`AGORA_PERSISTENCIA=sqlite` (etapa 6, segunda parte): `RegistroDeEstados`
tiene un adaptador SQLite igual que mandatos/medios/carritos/propuestas --
sin eso, `retomar` corrido en otra terminal (siempre otra terminal: nunca es
herramienta del agente) dejaria al `chat` sin forma de enterarse de que la
intencion ya se resolvio. Con `AGORA_PERSISTENCIA=memoria` (el default sin
`.env`), `estado`/`consultar_estado` solo ven lo que paso en el MISMO
proceso.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv

from ...aplicacion.navegar_catalogo import ItemPedido
from ...dominio.comun.errores import ErrorDeDominio
from ...dominio.mandato.modelo import Intencion
from ...dominio.pago.modelo import MedioDePagoRef, Proveedor
from ...composicion.agente import construir_agente
from ...composicion.configuracion import RAIZ_REPO, ConfiguracionInvalida, leer_configuracion
from ...composicion.contenedor import Contenedor, construir


def _armar_contenedor() -> Contenedor:
    load_dotenv(RAIZ_REPO / ".env")
    try:
        config = leer_configuracion(os.environ)
    except ConfiguracionInvalida as exc:
        print(f"[x] configuracion invalida: {exc}")
        raise SystemExit(1) from None
    return construir(config)


def _parsear_item(bruto: str) -> ItemPedido:
    """`producto_id:cantidad`, con `:cantidad` opcional (default 1) --
    formato compacto pensado para escribirse a mano en una terminal."""
    if ":" in bruto:
        producto_id, _, cantidad = bruto.partition(":")
        return ItemPedido(producto_id=producto_id, cantidad=int(cantidad))
    return ItemPedido(producto_id=bruto)


# --------------------------------------------------------------------------- #
# Fase A
# --------------------------------------------------------------------------- #


def cmd_enrolar(a, contenedor: Contenedor) -> int:
    puntos = {"activos": False}

    def narrar(etapa: str, detalle: str) -> None:
        if etapa == "sondeo":
            print(".", end="", flush=True)
            puntos["activos"] = True
            return
        if puntos["activos"]:
            print()
            puntos["activos"] = False
        print(f"  {etapa:10} {detalle}")

    try:
        ref = contenedor.enrolar_medio(a.telefono, a.correo, a.titular, a.comercio, al_avanzar=narrar)
    except ErrorDeDominio as exc:
        print(f"\n[x] {exc.mensaje}")
        return 1

    print(f"\nMedio de pago enrolado para '{a.titular}'")
    print(f"  proveedor    {ref.proveedor.value}")
    print(f"  ambiente     {ref.ambiente.value}")
    print(f"  id_externo   {ref.id_externo}")
    print(
        "\n  Desde aca se puede firmar un mandato contra este medio sin que "
        f"'{a.titular}' este presente:\n"
        f"\n    python -m agora.entradas.cli emitir <comercio_id> {a.titular} "
        "--item <producto_id>"
    )
    return 0


def cmd_fuentes(a, contenedor: Contenedor) -> int:
    vivos = contenedor.medios.vivos(a.titular, contenedor.config.ambiente)
    if not vivos:
        print(f"Sin medios de pago vivos para '{a.titular}' en '{contenedor.config.ambiente.value}'.")
        return 0
    print(f"{len(vivos)} medio(s) vivo(s) para '{a.titular}' ({contenedor.config.ambiente.value})\n")
    for ref in vivos:
        print(f"  {ref.proveedor.value:10} {ref.id_externo}")
    return 0


def cmd_revocar(a, contenedor: Contenedor) -> int:
    ref = MedioDePagoRef(
        proveedor=Proveedor(a.proveedor), ambiente=contenedor.config.ambiente, id_externo=a.id_externo,
    )
    try:
        estado = contenedor.revocar_medio(ref, a.titular)
    except ErrorDeDominio as exc:
        print(f"[x] {exc.mensaje}")
        return 1
    print(f"  medio {ref.id_externo} -> {estado.estado}")
    # "VOIDED_LOCAL" (Wompi no anula Nequi por API, ver AdaptadorWompi.
    # revocar_medio) trae un aviso que el titular necesita ver.
    aviso = (estado.detalle or {}).get("aviso")
    if aviso:
        print(f"  [!] {aviso}")
    return 0


# --------------------------------------------------------------------------- #
# Catalogo
# --------------------------------------------------------------------------- #


def cmd_comercios(a, contenedor: Contenedor) -> int:
    comercios = contenedor.navegar_catalogo.buscar_comercios(a.buscar or "")
    if not comercios:
        print("Sin comercios.")
        return 0
    for c in comercios:
        print(f"  {c.comercio_id:28} {c.nombre:20} {c.categoria}")
    return 0


def cmd_productos(a, contenedor: Contenedor) -> int:
    try:
        productos = contenedor.navegar_catalogo.buscar_productos(a.comercio_id, a.buscar or "")
    except ErrorDeDominio as exc:
        print(f"[x] {exc.mensaje}")
        return 1
    if not productos:
        print("Sin productos.")
        return 0
    for p in productos:
        print(f"  {p.producto_id:28} {p.nombre:24} {p.precio!s:>14}  {p.disponibilidad.value}")
    return 0


def cmd_producto(a, contenedor: Contenedor) -> int:
    try:
        p = contenedor.navegar_catalogo.ver_producto(a.producto_id)
    except ErrorDeDominio as exc:
        print(f"[x] {exc.mensaje}")
        return 1
    print(f"{p.nombre}  ({p.producto_id})")
    print(f"  comercio        {p.comercio_id}")
    print(f"  precio          {p.precio}")
    print(f"  disponibilidad  {p.disponibilidad.value}")
    print(f"  descripcion     {p.descripcion}")
    return 0


# --------------------------------------------------------------------------- #
# Fase B
# --------------------------------------------------------------------------- #


def cmd_emitir(a, contenedor: Contenedor) -> int:
    """Arma el carrito y firma el mandato en un solo comando: quien opera la
    CLI YA es el humano, asi que no hace falta separar "el agente propone"
    de "el humano firma" en dos invocaciones -- esa separacion importa
    cuando el que propone es un modelo de lenguaje (`agente/`), no una
    persona escribiendo el comando ella misma."""
    items = [_parsear_item(i) for i in a.item]
    try:
        carrito, propuesta = contenedor.navegar_catalogo.armar_carrito(
            a.comercio_id, items, justificacion=a.justificacion or "",
        )
        mandato = contenedor.emitir_mandato(propuesta.propuesta_id, a.titular)
    except ErrorDeDominio as exc:
        print(f"[x] {exc.mensaje}")
        return 1

    print(f"Carrito {carrito.carrito_id}  ({carrito.total})")
    for i in carrito.items:
        print(f"  {i.cantidad}x {i.nombre:24} {i.subtotal}")

    print(f"\nMandato {mandato.mandato_id}  (firmado)")
    print(f"  titular      {mandato.titular_id}")
    print(f"  comercio     {mandato.comercio_id}")
    print(f"  monto max    {mandato.monto_max}")
    print(f"  expira       {mandato.expira_en.isoformat(timespec='seconds')}")
    print(
        "\n  Con esto se puede pagar:\n"
        f"\n    python -m agora.entradas.cli pagar {mandato.mandato_id} {carrito.carrito_id}"
    )
    return 0


def cmd_firmar(a, contenedor: Contenedor) -> int:
    """Etapa 6: firma una propuesta que ya armo OTRO proceso -- tipicamente
    el agente, en una charla de `chat` (`armar_carrito` le muestra a la
    persona el `propuesta_id` y este mismo comando ya armado, ver
    `composicion/agente.py`). A diferencia de `cmd_emitir`, no arma un
    carrito nuevo: `contenedor.emitir_mandato` busca la propuesta y el
    carrito por id contra `RepositorioPropuestas`/`RepositorioCarritos`, asi
    que el `carrito_id` que resulta es el MISMO que ya tiene quien arranco
    la conversacion -- eso es lo que permite que `pagar()` (la herramienta
    del agente) despues encuentre el mandato correcto sin que la persona
    tenga que pasarle un carrito_id distinto."""
    try:
        mandato = contenedor.emitir_mandato(a.propuesta_id, a.titular)
        carrito = contenedor.carritos.obtener(
            contenedor.propuestas.obtener(a.propuesta_id).carrito_id
        )
    except ErrorDeDominio as exc:
        print(f"[x] {exc.mensaje}")
        return 1

    print(f"Mandato {mandato.mandato_id}  (firmado)")
    print(f"  titular      {mandato.titular_id}")
    print(f"  comercio     {mandato.comercio_id}")
    print(f"  monto max    {mandato.monto_max}")
    print(f"  expira       {mandato.expira_en.isoformat(timespec='seconds')}")
    print(
        "\n  Con esto se puede pagar (por CLI, o pasandole el mandato_id al "
        "agente en el chat):\n"
        f"\n    python -m agora.entradas.cli pagar {mandato.mandato_id} {carrito.carrito_id}"
    )
    return 0


def cmd_pagar(a, contenedor: Contenedor) -> int:
    try:
        carrito = contenedor.carritos.obtener(a.carrito_id)
    except ErrorDeDominio as exc:
        print(f"[x] {exc.mensaje}")
        return 1

    intencion = Intencion(
        intencion_id=contenedor.ids.nuevo("int"),
        mandato_id=a.mandato_id,
        comercio_id=carrito.comercio_id,
        carrito_id=a.carrito_id,
        monto=carrito.total,
    )
    recibo = contenedor.ejecutar_intencion(intencion, carrito_hash=carrito.hash_canonico)

    print(f"  intencion    {intencion.intencion_id}")
    print(f"  ejecutado    {recibo.ejecutado}")
    print(f"  motivo       {recibo.motivo}")
    if recibo.dictamen.violaciones:
        print("  violaciones:")
        for v in recibo.dictamen.violaciones:
            print(f"    - {v.tipo:26} {v.detalle}")
    if recibo.esperando_confirmacion:
        print(
            "\n  Queda esperando confirmacion humana:\n"
            f"\n    python -m agora.entradas.cli retomar {intencion.intencion_id} "
            f"{a.mandato_id} {a.carrito_id}"
        )
    return 0


def cmd_retomar(a, contenedor: Contenedor) -> int:
    """Resuelve una intencion que `pagar` dejo en `esperando_confirmacion_
    humana` -- la senal blanda de `dominio/mandato/politica.py` ("agota el
    mandato de una sola vez", tipico de un mandato cortado exacto al
    carrito por `EmitirMandato`). Pide de nuevo `mandato_id`/`carrito_id`
    porque `EjecutarIntencion.retomar` vuelve a evaluar la politica completa
    contra el mismo `Intencion` -- no alcanza con el `intencion_id` solo.
    """
    try:
        carrito = contenedor.carritos.obtener(a.carrito_id)
    except ErrorDeDominio as exc:
        print(f"[x] {exc.mensaje}")
        return 1

    intencion = Intencion(
        intencion_id=a.intencion_id, mandato_id=a.mandato_id,
        comercio_id=carrito.comercio_id, carrito_id=a.carrito_id, monto=carrito.total,
    )
    try:
        recibo = contenedor.ejecutar_intencion.retomar(
            intencion, aprueba=not a.rechazar, carrito_hash=carrito.hash_canonico,
        )
    except ErrorDeDominio as exc:
        print(f"[x] {exc.mensaje}")
        return 1

    print(f"  ejecutado    {recibo.ejecutado}")
    print(f"  motivo       {recibo.motivo}")
    return 0


def cmd_estado(a, contenedor: Contenedor) -> int:
    try:
        estado = contenedor.consultar_estado(a.intencion_id)
    except ErrorDeDominio as exc:
        print(f"[x] {exc.mensaje}")
        return 1
    print(f"  {estado.intencion_id}  {estado.estado}  {estado.detalle}")
    return 0


def cmd_mandatos(a, contenedor: Contenedor) -> int:
    mandatos = contenedor.mandatos.listar(contenedor.config.ambiente)
    if not mandatos:
        print("Sin mandatos.")
        return 0
    for m in mandatos:
        consumo = contenedor.consumo.consumo_de(m.mandato_id)
        print(
            f"  {m.mandato_id}  {m.comercio_id:24} {m.monto_max!s:>12}  "
            f"usos {consumo.usos}/{m.usos_max}"
        )
    return 0


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #


def _imprimir_traza(cuerpo: dict, ts: str) -> None:
    """Un turno, legible. El .jsonl es la fuente de verdad -- esto es solo
    la forma de mirarlo mientras corre."""
    clasificacion = cuerpo.get("clasificacion") or {}
    intencion = clasificacion.get("intencion") or "respaldo"
    print(f"\n{'=' * 72}")
    print(
        f"{ts}  conversacion {cuerpo.get('conversacion_id')}  "
        f"turno {cuerpo.get('turno')}  {cuerpo.get('duracion_ms')} ms"
    )
    print(f"  persona> {cuerpo.get('mensaje')}")
    print(
        f"  1. DECIDIR   intencion={intencion} origen={clasificacion.get('origen')} "
        f"confianza={clasificacion.get('confianza')}"
        + (f" motivo={clasificacion.get('motivo')}" if clasificacion.get("motivo") else "")
    )
    habilitadas = ", ".join(cuerpo.get("herramientas_habilitadas") or []) or "ninguna"
    print(
        f"  2. ENRUTAR   agente={cuerpo.get('agente') or '-'} "
        f"nodos={','.join(cuerpo.get('nodos') or []) or '-'}"
    )
    print(f"               herramientas ofrecidas: {habilitadas}")
    for contexto in cuerpo.get("contexto") or []:
        fuentes = ", ".join(contexto.get("fuentes") or []) or "sin fragmentos relevantes"
        print(
            f"  3. CONTEXTO  {contexto.get('nodo')}: {fuentes} "
            f"({contexto.get('caracteres')} caracteres)"
        )
    print(f"  4. EJECUTAR  {cuerpo.get('rondas')} ronda(s) del loop")
    for llamada in cuerpo.get("llamadas") or []:
        if llamada.get("fuera_de_ruta"):
            marca = "RECHAZADA (fuera de ruta)"
        elif llamada.get("error"):
            marca = "error"
        else:
            marca = "ok"
        print(
            f"     [{llamada.get('ronda')}] {llamada.get('herramienta')}"
            f"({llamada.get('argumentos')}) -> {marca}"
        )
        detalle = llamada.get("error") or llamada.get("resultado") or ""
        if detalle:
            print(f"         {detalle}")
    print(f"  agente>  {cuerpo.get('respuesta')}")


def cmd_trazas(a, contenedor: Contenedor) -> int:
    """Lee la bitacora de trazas. No la produce: el agente la escribe desde
    el proceso que atiende el chat (`servir_api` o `chat`), y esto es una
    ventana sobre ese archivo -- por eso se puede correr en otra terminal,
    en otra maquina con el archivo montado, o despues de que todo termino."""
    ruta = contenedor.config.trazas_path
    if not ruta.exists():
        print(f"[i] todavia no hay trazas en {ruta}")
        print("    se escriben solas cuando alguien chatea (servir_api, o el comando chat).")
        return 0

    def mostrar(linea: str) -> None:
        linea = linea.strip()
        if not linea:
            return
        try:
            registro = json.loads(linea)
        except json.JSONDecodeError:
            return
        if a.crudo:
            print(linea)
        else:
            _imprimir_traza(registro.get("cuerpo") or {}, registro.get("ts", ""))

    with ruta.open(encoding="utf-8") as f:
        lineas = f.readlines()
        for linea in lineas[-a.ultimas :] if a.ultimas > 0 else lineas:
            mostrar(linea)
        if not a.seguir:
            return 0
        print(f"\n[i] siguiendo {ruta} -- Ctrl+C para salir", flush=True)
        try:
            while True:
                linea = f.readline()
                if linea:
                    mostrar(linea)
                else:
                    time.sleep(0.4)
        except KeyboardInterrupt:
            return 0


def cmd_chat(a, contenedor: Contenedor) -> int:
    agente = construir_agente(contenedor)
    if agente is None:
        print(
            "[x] no hay DEEPSEEK_API_KEY configurada -- sin ella no hay agente "
            "de chat. Ver docs/variables-de-entorno.md."
        )
        return 1

    print("Chateando con el agente. Escriba 'salir' para terminar.\n")
    conversacion = agente.iniciar()
    while True:
        try:
            entrada = input("vos> ").strip()
        except EOFError:
            break
        if not entrada:
            continue
        if entrada.lower() in ("salir", "exit", "quit"):
            break
        contextos_antes = len(conversacion.contextos)
        try:
            respuesta = agente.turno(conversacion, entrada)
        except ErrorDeDominio as exc:
            print(f"[x] {exc.mensaje}")
            continue
        if getattr(a, "mostrar_intencion", False) and conversacion.clasificaciones:
            # Migracion a agentes, etapa 1: la decision del orquestador,
            # visible para verificar a mano que "decidir" y "ejecutar" van
            # separados. Sin clasificador (AGORA_CLASIFICADOR=apagado) no hay
            # clasificaciones y no se imprime nada.
            c = conversacion.clasificaciones[-1]
            print(
                f"  [intencion: {c.intencion.value if c.intencion else 'respaldo'} | "
                f"{c.origen.value} | confianza {c.confianza:.2f} | {c.motivo}]"
            )
            # Etapa 2: de que documentos salio el contexto de este turno.
            for nodo, contexto in conversacion.contextos[contextos_antes:]:
                fuentes = ", ".join(contexto.fuentes) or "sin fragmentos relevantes"
                print(f"  [contexto de {nodo}: {fuentes}]")
        print(f"agente> {respuesta}\n")
    return 0


# --------------------------------------------------------------------------- #


def _armar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agora", description="Agora -- linea de comandos")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("enrolar", help="Fase A: el titular autoriza por push")
    pe.add_argument("--telefono", required=True)
    pe.add_argument("--correo", default="titular+demo@agora.local")
    pe.add_argument("--titular", default="tit_demo")
    # Multi-comercio: enrolar vincula el medio con ESTE comercio (ver el
    # docstring de aplicacion/enrolar_medio.py) -- ya no hay "enrolar"
    # generico sin destino.
    pe.add_argument("--comercio", required=True, help="comercio_id con el que vincular el medio")

    pf = sub.add_parser("fuentes", help="medios de pago vivos de un titular")
    pf.add_argument("titular")

    pr = sub.add_parser("revocar", help="apaga un medio de pago")
    pr.add_argument("--id-externo", dest="id_externo", required=True)
    pr.add_argument("--proveedor", default="simulada", choices=["simulada", "wompi"])
    pr.add_argument("--titular", default="tit_demo")

    pc = sub.add_parser("comercios", help="busca comercios simulados")
    pc.add_argument("--buscar", default="")

    pp = sub.add_parser("productos", help="busca productos de un comercio")
    pp.add_argument("comercio_id")
    pp.add_argument("--buscar", default="")

    pv = sub.add_parser("producto", help="detalle de un producto")
    pv.add_argument("producto_id")

    pm = sub.add_parser("emitir", help="arma un carrito y firma el mandato")
    pm.add_argument("comercio_id")
    pm.add_argument("titular")
    pm.add_argument("--item", action="append", required=True, help="producto_id[:cantidad]")
    pm.add_argument("--justificacion", default="")

    pfi = sub.add_parser(
        "firmar", help="firma una propuesta que ya armo otro proceso (por ejemplo, el chat)"
    )
    pfi.add_argument("propuesta_id")
    pfi.add_argument("titular")

    pg = sub.add_parser("pagar", help="ejecuta el cobro de un carrito")
    pg.add_argument("mandato_id")
    pg.add_argument("carrito_id")

    pt = sub.add_parser("retomar", help="resuelve una intencion que quedo esperando confirmacion")
    pt.add_argument("intencion_id")
    pt.add_argument("mandato_id")
    pt.add_argument("carrito_id")
    pt.add_argument("--rechazar", action="store_true", help="rechaza en vez de aprobar")

    px = sub.add_parser("estado", help="estado de una intencion")
    px.add_argument("intencion_id")

    sub.add_parser("mandatos", help="mandatos emitidos y su consumo")
    ptz = sub.add_parser(
        "trazas",
        help="lee la trazabilidad del agente: como llego a cada respuesta",
    )
    ptz.add_argument(
        "--seguir", "-f", action="store_true",
        help="se queda esperando turnos nuevos, como tail -f. Pensado para "
        "una terminal aparte, al lado de la que corre servir_api",
    )
    ptz.add_argument(
        "--ultimas", "-n", type=int, default=5,
        help="cuantos turnos mostrar antes de seguir (0 = todos; default 5)",
    )
    ptz.add_argument(
        "--crudo", action="store_true",
        help="imprime el .jsonl tal cual, para pasarselo a jq",
    )

    pc = sub.add_parser("chat", help="chatear con el agente (necesita DEEPSEEK_API_KEY)")
    pc.add_argument(
        "--mostrar-intencion",
        action="store_true",
        help="imprime la intencion que clasifico el orquestador en cada turno "
        "(migracion a agentes, etapa 1)",
    )

    return p


def main() -> int:
    a = _armar_parser().parse_args()
    contenedor = _armar_contenedor()

    comandos = {
        "enrolar": cmd_enrolar,
        "fuentes": cmd_fuentes,
        "revocar": cmd_revocar,
        "comercios": cmd_comercios,
        "productos": cmd_productos,
        "producto": cmd_producto,
        "emitir": cmd_emitir,
        "firmar": cmd_firmar,
        "pagar": cmd_pagar,
        "retomar": cmd_retomar,
        "estado": cmd_estado,
        "mandatos": cmd_mandatos,
        "chat": cmd_chat,
        "trazas": cmd_trazas,
    }
    return comandos[a.cmd](a, contenedor)


if __name__ == "__main__":
    sys.exit(main())
