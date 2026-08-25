#!/usr/bin/env python3
"""Migra `boveda/secretos/fuentes.json` (v1) a la tabla `medio_de_pago` de
SQLite (etapa 3, `docs/arquitectura-v2.md`).

QUE SI MIGRA
------------
Los medios de pago que `boveda/enrolamiento.py:RegistroFuentes` guarda en
`fuentes.json` -- un `payment_source_id` de Wompi por entrada, vivo o
revocado, separado por modo (sandbox/produccion).

QUE NO MIGRA, A PROPOSITO
--------------------------
Los mandatos v1 de `boveda/secretos/estado.json`. Decision explicita de Juan
(25/08/2026, al pedir la etapa 3): se archivan tal cual quedan en `boveda/`,
sin ninguna fila nueva en `agora/`; de ahora en adelante solo se trabaja con
mandatos v2. Este script no lee `estado.json` ni lo menciona salvo en este
comentario -- no es un "todavia no", es un "no". (Y aunque se quisiera:
reescribir el payload canonico de un mandato v1 para que encaje en el
esquema v2 invalidaria su firma ed25519 original -- `dominio/mandato/
compat.py` documenta por que esa conversion no es posible sin pedirle al
titular que autorice de nuevo.)

COMO CORRE
----------
Dry-run por defecto: imprime que haria y no escribe nada en absoluto -- ni
siquiera crea el archivo SQLite destino. `--aplicar` para escribir de
verdad. Antes de escribir, si el destino ya existe, se copia a un
`<destino>.bak-<timestamp>` al lado: una migracion que se corre dos veces
por error no debe dejar a Juan sin como volver atras. La migracion en si es
idempotente (`INSERT OR REPLACE` por `(proveedor, ambiente, id_externo)`),
asi que correrla de nuevo sobre el mismo destino sin backup tampoco duplica
filas -- el backup es una red adicional, no lo unico que evita la perdida.

`--titular` es obligatorio: `fuentes.json` nunca guardo a nombre de quien
esta un medio de pago (obvio en la Fase A del PoC, donde solo existia un
titular). `medio_de_pago.titular_id` en SQLite si lo exige, asi que hay que
decirlo aqui, una vez, a mano -- no hay forma de inferirlo del archivo v1.

Este script vive fuera de `agora/` a proposito: no es parte del arbol que
`tests/test_fronteras.py` vigila (esa prueba solo camina `agora/`), y su
trabajo -- leer JSON de `boveda/`, escribir SQLite de `agora/` -- es
exactamente el tipo de cruce que un composition root haria si fuera un
comando de una sola vez en lugar de un servicio de larga vida.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent
if str(RAIZ_REPO) not in sys.path:
    # Para poder correr `python scripts/migrar_fuentes_a_sqlite.py` directo,
    # sin depender de que el paquete este instalado o de que se invoque con
    # `python -m`.
    sys.path.insert(0, str(RAIZ_REPO))

from agora.adaptadores.persistencia.sqlite.conexion import abrir_conexion  # noqa: E402

FUENTES_POR_DEFECTO = RAIZ_REPO / "boveda" / "secretos" / "fuentes.json"
DESTINO_POR_DEFECTO = RAIZ_REPO / "agora_datos" / "agora.db"

# v1 solo hablo con Wompi -- la pasarela simulada no existia todavia -- asi
# que el proveedor es fijo para toda fila migrada. Si `tipo` en v1 fuera
# "CARD" en vez de "NEQUI", el proveedor seguiria siendo Wompi: `tipo`
# describe el metodo, no quien procesa.
PROVEEDOR_V1 = "wompi"

MODOS_VALIDOS = ("sandbox", "produccion")


class ErrorDeMigracion(SystemExit):
    pass


def leer_fuentes(ruta: Path) -> dict[str, list[dict]]:
    if not ruta.exists():
        raise ErrorDeMigracion(f"no existe {ruta}")
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ErrorDeMigracion(f"{ruta} no es JSON valido: {exc}") from exc

    for modo in datos:
        if modo not in MODOS_VALIDOS:
            raise ErrorDeMigracion(
                f"'{modo}' en {ruta} no es un modo reconocido "
                f"(se esperaba {MODOS_VALIDOS}) -- revisar el archivo a mano "
                "antes de continuar; este script no adivina"
            )
    return datos


def filas_a_migrar(datos: dict[str, list[dict]], titular_id: str) -> list[tuple]:
    """Aplana `fuentes.json` a filas listas para `medio_de_pago`.

    Falla temprano (antes de tocar SQLite) si alguna entrada le falta un
    campo requerido -- mejor un error de migracion claro que una fila a medias.
    """
    filas = []
    for modo, entradas in datos.items():
        for entrada in entradas:
            faltantes = [
                campo
                for campo in ("payment_source_id", "estado", "creada_en")
                if campo not in entrada
            ]
            if faltantes:
                raise ErrorDeMigracion(
                    f"entrada en modo '{modo}' sin {faltantes}: {entrada}"
                )
            filas.append(
                (
                    PROVEEDOR_V1,
                    modo,
                    str(entrada["payment_source_id"]),
                    titular_id,
                    entrada["estado"],
                    entrada["creada_en"],
                )
            )
    return filas


def mostrar_plan(filas: list[tuple]) -> None:
    if not filas:
        print("fuentes.json no tiene ninguna entrada. Nada que migrar.")
        return
    print(f"{len(filas)} medio(s) de pago para migrar a `medio_de_pago`:\n")
    for proveedor, ambiente, id_externo, titular_id, estado, creado_en in filas:
        print(
            f"  [{ambiente:10s}] {proveedor}:{id_externo:12s} "
            f"titular={titular_id} estado={estado:12s} creado_en={creado_en}"
        )
    print(
        "\nCada fila usa INSERT OR REPLACE sobre (proveedor, ambiente, "
        "id_externo): correr esto de nuevo sobre el mismo destino actualiza, "
        "no duplica."
    )


def respaldar_si_existe(destino: Path) -> Path | None:
    if not destino.exists():
        return None
    marca = datetime.now().strftime("%Y%m%d%H%M%S")
    respaldo = destino.with_name(f"{destino.name}.bak-{marca}")
    shutil.copy2(destino, respaldo)
    return respaldo


def aplicar(destino: Path, filas: list[tuple]) -> None:
    respaldo = respaldar_si_existe(destino)
    if respaldo is not None:
        print(f"backup del destino existente: {respaldo}")

    con = abrir_conexion(destino)
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            con.executemany(
                "INSERT OR REPLACE INTO medio_de_pago "
                "(proveedor, ambiente, id_externo, titular_id, estado, creado_en) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                filas,
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
        else:
            con.execute("COMMIT")
    finally:
        con.close()
    print(f"{len(filas)} fila(s) escritas en {destino}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fuentes", type=Path, default=FUENTES_POR_DEFECTO,
        help=f"ruta de fuentes.json (default: {FUENTES_POR_DEFECTO})",
    )
    parser.add_argument(
        "--destino", type=Path, default=DESTINO_POR_DEFECTO,
        help=f"ruta del SQLite destino (default: {DESTINO_POR_DEFECTO})",
    )
    parser.add_argument(
        "--titular", required=True,
        help="titular_id a asignarle a cada medio migrado -- fuentes.json no lo guarda",
    )
    parser.add_argument(
        "--aplicar", action="store_true",
        help="escribe de verdad. Sin esta bandera solo se imprime el plan (dry-run)",
    )
    args = parser.parse_args(argv)

    datos = leer_fuentes(args.fuentes)
    filas = filas_a_migrar(datos, args.titular)
    mostrar_plan(filas)

    if not args.aplicar:
        print("\nDry-run: no se escribio nada. Vuelva a correr con --aplicar para migrar de verdad.")
        return 0

    if not filas:
        return 0

    aplicar(args.destino, filas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
