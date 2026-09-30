#!/usr/bin/env python3
"""Fabrica el catalogo de comercios simulados con DeepSeek (etapa 5).

Composition root de este comando: lee `DEEPSEEK_API_KEY` del entorno, arma
`AdaptadorDeepSeek` y corre `aplicacion/generar_catalogo_semilla.py` una vez
por cada comercio pedido, escribiendo el resultado en `agora/adaptadores/
catalogo/semilla/datos/catalogo.json` -- el archivo que
`RepositorioCatalogoSemilla` lee en tiempo de ejecucion, sin red.

    export DEEPSEEK_API_KEY=sk-...
    python scripts/generar_catalogo_semilla.py

Por defecto genera un comercio por cada categoria de una lista fija pensada
para una demo colombiana (tecnologia, moda, hogar, restaurantes, libros).
`--categorias` la reemplaza, `--por-categoria` pide mas de un comercio por
categoria, `--productos` controla cuantos productos tiene cada uno.

Sin `--agregar`, cada corrida reemplaza el catalogo entero (son datos
fabricados, no evidencia -- no hace falta preservarlos como
`recibos.jsonl`), con un backup automatico del archivo anterior si ya
existia. Con `--agregar`, los comercios nuevos se suman a los que ya estaban
en el archivo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]  # solo para sys.path
if str(_REPO) not in sys.path:
    # Para poder correr `python scripts/generar_catalogo_semilla.py` directo,
    # sin depender de que el paquete este instalado (mismo patron que los
    # demas scripts/).
    sys.path.insert(0, str(_REPO))

from agora.adaptadores.catalogo.semilla import RUTA_POR_DEFECTO  # noqa: E402
from agora.adaptadores.catalogo.semilla import serializacion  # noqa: E402
from agora.adaptadores.llm.deepseek import (  # noqa: E402
    AdaptadorDeepSeek,
    ConfiguracionDeepSeek,
    ConfiguracionInvalida,
)
from agora.adaptadores.sistema.ids import GeneradorIdsUuid  # noqa: E402
from agora.aplicacion.generar_catalogo_semilla import GenerarCatalogoSemilla  # noqa: E402
from agora.dominio.comun.errores import ErrorDeModeloDeLenguaje  # noqa: E402
from agora.composicion.configuracion import RAIZ_REPO  # noqa: E402
from utilidades.env import cargar_env_desde_archivo  # noqa: E402

CATEGORIAS_POR_DEFECTO = ("tecnologia", "moda", "hogar", "restaurantes", "libros")


def _leer_configuracion(entorno: dict) -> ConfiguracionDeepSeek:
    llave = entorno.get("DEEPSEEK_API_KEY", "")
    modelo = entorno.get("DEEPSEEK_MODELO")
    kwargs = {"llave_api": llave}
    if modelo:
        kwargs["modelo"] = modelo
    return ConfiguracionDeepSeek(**kwargs)


def _cargar_existente(ruta: Path) -> tuple[list[dict], list[dict]]:
    if not ruta.exists():
        return [], []
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return datos.get("comercios", []), datos.get("productos", [])


def _respaldar_si_existe(ruta: Path) -> Path | None:
    if not ruta.exists():
        return None
    marca = datetime.now().strftime("%Y%m%d%H%M%S")
    respaldo = ruta.with_name(f"{ruta.stem}.bak-{marca}{ruta.suffix}")
    shutil.copy2(ruta, respaldo)
    return respaldo


def generar(
    generar_uno: GenerarCatalogoSemilla,
    categorias: list[str],
    por_categoria: int,
    productos: int,
) -> tuple[list[dict], list[dict]]:
    """Corre el caso de uso una vez por comercio pedido. Si DeepSeek falla o
    devuelve algo invalido a mitad de camino, se detiene ahi -- no escribe un
    catalogo a medias con lo que alcanzo a salir bien."""
    comercios_json: list[dict] = []
    productos_json: list[dict] = []
    for categoria in categorias:
        for i in range(por_categoria):
            print(f"generando comercio {i + 1}/{por_categoria} de '{categoria}'...")
            generado = generar_uno(categoria, cantidad_productos=productos)
            comercios_json.append(serializacion.comercio_a_json(generado.comercio))
            productos_json.extend(serializacion.producto_a_json(p) for p in generado.productos)
            print(
                f"  {generado.comercio.nombre!r} -- {len(generado.productos)} producto(s)"
            )
    return comercios_json, productos_json


def main(argv: list[str] | None = None) -> int:
    cargar_env_desde_archivo(RAIZ_REPO / ".env")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--categorias", nargs="+", default=list(CATEGORIAS_POR_DEFECTO),
        help=f"categorias a generar (default: {' '.join(CATEGORIAS_POR_DEFECTO)})",
    )
    parser.add_argument(
        "--por-categoria", type=int, default=1,
        help="cuantos comercios generar por categoria (default: 1)",
    )
    parser.add_argument(
        "--productos", type=int, default=5,
        help="cuantos productos por comercio (default: 5)",
    )
    parser.add_argument(
        "--destino", type=Path, default=RUTA_POR_DEFECTO,
        help=f"ruta del catalogo.json destino (default: {RUTA_POR_DEFECTO})",
    )
    parser.add_argument(
        "--agregar", action="store_true",
        help="suma los comercios nuevos a los que ya haya en --destino, en vez de reemplazar",
    )
    args = parser.parse_args(argv)

    try:
        config = _leer_configuracion(os.environ)
    except ConfiguracionInvalida as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    modelo = AdaptadorDeepSeek(config)
    ids = GeneradorIdsUuid()
    generar_uno = GenerarCatalogoSemilla(modelo, ids)

    try:
        comercios_nuevos, productos_nuevos = generar(
            generar_uno, args.categorias, args.por_categoria, args.productos
        )
    except ErrorDeModeloDeLenguaje as exc:
        print(f"\nerror generando catalogo: {exc}", file=sys.stderr)
        print(
            "nada se escribio en disco -- el catalogo anterior (si existia) sigue intacto.",
            file=sys.stderr,
        )
        return 1

    if args.agregar:
        comercios_previos, productos_previos = _cargar_existente(args.destino)
        comercios_nuevos = comercios_previos + comercios_nuevos
        productos_nuevos = productos_previos + productos_nuevos

    respaldo = _respaldar_si_existe(args.destino)
    if respaldo is not None:
        print(f"backup del catalogo anterior: {respaldo}")

    args.destino.parent.mkdir(parents=True, exist_ok=True)
    args.destino.write_text(
        json.dumps(
            {"comercios": comercios_nuevos, "productos": productos_nuevos},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"\n{len(comercios_nuevos)} comercio(s), {len(productos_nuevos)} "
        f"producto(s) escritos en {args.destino}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
