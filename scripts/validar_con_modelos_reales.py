"""Mide contra DeepSeek y OpenAI de verdad lo que ninguna sesion pudo medir.

Las cinco etapas de la migracion a agentes se construyeron sin salida de red
hacia `api.deepseek.com` ni `api.openai.com`, asi que todo lo que depende de
un modelo real quedo probado con dobles. Tres cosas quedaron SIN MEDIR, y las
tres son numeros que no se pueden elegir mirando una charla:

    1. la calidad del clasificador de intencion          (etapa 1)
    2. el piso del RAG de soporte                        (etapa 2)
       `agente/contexto_documental.py:PUNTAJE_MINIMO_POR_DEFECTO`
    3. el piso semantico del catalogo                    (etapa 4)
       `adaptadores/busqueda_productos/.../PARECIDO_MINIMO_POR_DEFECTO`

Este script las mide y propone un valor para cada umbral. No cambia nada:
imprime, y quien decide sos vos.

    python scripts/validar_con_modelos_reales.py
    python scripts/validar_con_modelos_reales.py --solo catalogo
    python scripts/validar_con_modelos_reales.py --json > medicion.json

QUE CUESTA
------------
El clasificador gasta una llamada a DeepSeek por mensaje ambiguo (los
inequivocos los resuelven las reglas, gratis). Soporte y catalogo embeben el
corpus y el catalogo una vez, mas una consulta por pregunta: con
`text-embedding-3-small` son centavos.

LO QUE ESTE SCRIPT NO MIDE
----------------------------
Si el modelo real entiende el aviso de reanudacion de la etapa 5 y llama a
`pagar()` con los ids correctos. Eso necesita una charla completa con firma
desde el popup -- la receta esta en `docs/arquitectura-agentes/
etapa-5-pausa-humana.md`, y se mira con `python -m agora.entradas.cli trazas
--seguir`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from agora.adaptadores.busqueda_productos.semantico_en_memoria import (  # noqa: E402
    PARECIDO_MINIMO_POR_DEFECTO,
)
from agora.agente.contexto_documental import (  # noqa: E402
    PUNTAJE_MINIMO_POR_DEFECTO,
    armar_consulta,
)
from agora.agente.intencion import TipoDeIntencion  # noqa: E402
from agora.composicion.agente import construir_clasificador  # noqa: E402
from agora.composicion.configuracion import ConfiguracionInvalida, leer_configuracion  # noqa: E402
from agora.composicion.contenedor import construir  # noqa: E402

# --------------------------------------------------------------------------- #
# 1. Clasificador de intencion: un conjunto etiquetado a mano
# --------------------------------------------------------------------------- #
# Escritos como escribe una persona, no como los escribiria quien conoce el
# codigo: sin nombres de herramientas, con errores de tipeo y sin tildes a
# veces. Los casos dificiles estan a proposito -- un conjunto que el
# clasificador acierta siempre no mide nada.

MENSAJES_ETIQUETADOS: tuple[tuple[str, TipoDeIntencion], ...] = (
    # catalogo
    ("que tiendas hay?", TipoDeIntencion.CATALOGO),
    ("mostrame los productos de la dulceria", TipoDeIntencion.CATALOGO),
    ("tenes algo de tecnologia?", TipoDeIntencion.CATALOGO),
    ("cuanto cuesta la chocolatina", TipoDeIntencion.CATALOGO),
    ("que venden ahi", TipoDeIntencion.CATALOGO),
    # carrito y pago
    ("quiero comprar las gomitas", TipoDeIntencion.CARRITO_PAGO),
    ("comprame dos chocolatinas", TipoDeIntencion.CARRITO_PAGO),
    ("dale, llevo ese", TipoDeIntencion.CARRITO_PAGO),
    ("armame el carrito con lo mas barato", TipoDeIntencion.CARRITO_PAGO),
    ("necesito pagar eso ya", TipoDeIntencion.CARRITO_PAGO),
    # medios de pago
    ("como vinculo mi nequi?", TipoDeIntencion.MEDIOS_DE_PAGO),
    ("quiero quitar mi tarjeta", TipoDeIntencion.MEDIOS_DE_PAGO),
    ("que medios de pago tengo activos", TipoDeIntencion.MEDIOS_DE_PAGO),
    ("puedo pagar con daviplata", TipoDeIntencion.MEDIOS_DE_PAGO),
    # estado
    ("como va mi pago?", TipoDeIntencion.ESTADO),
    ("ya se aprobo la compra?", TipoDeIntencion.ESTADO),
    ("que paso con la transaccion de ayer", TipoDeIntencion.ESTADO),
    ("sigue pendiente?", TipoDeIntencion.ESTADO),
    # soporte
    ("por que me piden confirmar?", TipoDeIntencion.SOPORTE),
    ("que es un mandato", TipoDeIntencion.SOPORTE),
    ("que pasa si el carrito cambia despues de firmar", TipoDeIntencion.SOPORTE),
    ("vos podes gastar mi plata sin que yo firme?", TipoDeIntencion.SOPORTE),
    ("como funciona esto", TipoDeIntencion.SOPORTE),
    # fuera de alcance
    ("hola!", TipoDeIntencion.FUERA_DE_ALCANCE),
    ("gracias, muy amable", TipoDeIntencion.FUERA_DE_ALCANCE),
    ("contame un chiste", TipoDeIntencion.FUERA_DE_ALCANCE),
    ("que dia es hoy", TipoDeIntencion.FUERA_DE_ALCANCE),
)

# --------------------------------------------------------------------------- #
# 2. Soporte: preguntas que SI estan en el corpus, y ajenas que no
# --------------------------------------------------------------------------- #

PREGUNTAS_DE_SOPORTE = (
    "por que me piden confirmar un pago?",
    "que pasa si el carrito cambia despues de que firmo?",
    "que controla el mandato exactamente?",
    "como vinculo un medio de pago nuevo?",
    "el asistente puede pagar sin mi?",
    "que significa que un pago quede pendiente?",
)
PREGUNTAS_AJENAS = (
    "cual es la capital de mongolia",
    "receta de arroz con pollo",
    "como cambio una llanta",
)

# --------------------------------------------------------------------------- #
# 3. Catalogo: necesidades descritas, no nombres de producto
# --------------------------------------------------------------------------- #

NECESIDADES = (
    "algo dulce para un antojo",
    "algo para tomar frio",
    "un regalo barato",
    "algo para la piel reseca",
    "algo salado para picar",
)
NECESIDADES_AJENAS = (
    "un tractor agricola usado",
    "clases de piano",
)


def _fallo(entrada: str, exc: Exception, detalle: list) -> None:
    """Una consulta que revienta no puede tirar la corrida entera: medir esto
    cuesta llamadas de verdad, y perder lo ya medido por un caso raro seria
    pagar dos veces. Se anota y se sigue."""
    print(f"  [x] '{entrada}': {type(exc).__name__}: {exc}")
    detalle.append({"entrada": entrada, "error": f"{type(exc).__name__}: {exc}"})


def _linea(titulo: str) -> None:
    print(f"\n{'=' * 74}\n{titulo}\n{'=' * 74}")


def _sugerir_piso(dentro: list[float], fuera: list[float]) -> tuple[float | None, str]:
    """Un piso que deje pasar lo relevante y corte lo ajeno.

    Si los dos grupos se solapan no hay umbral que los separe, y decirlo vale
    mas que inventar un numero: significa que el problema no es el piso sino
    lo que se esta embebiendo."""
    if not dentro:
        return None, "sin resultados relevantes: no hay nada que calibrar"
    peor_relevante = min(dentro)
    mejor_ajeno = max(fuera) if fuera else 0.0
    if mejor_ajeno >= peor_relevante:
        return None, (
            f"SE SOLAPAN (peor relevante {peor_relevante:.3f} <= mejor ajeno "
            f"{mejor_ajeno:.3f}): ningun piso los separa. Revisar el corpus o "
            "el texto que se embebe antes que el umbral."
        )
    sugerido = round((peor_relevante + mejor_ajeno) / 2, 2)
    return sugerido, (
        f"relevantes >= {peor_relevante:.3f}, ajenos <= {mejor_ajeno:.3f} -> "
        f"punto medio {sugerido}"
    )


# --------------------------------------------------------------------------- #


def medir_clasificador(contenedor, salida: dict[str, Any]) -> None:
    _linea("1. CLASIFICADOR DE INTENCION (etapa 1) -- DeepSeek real")
    if contenedor.modelo_lenguaje is None:
        print("[x] falta DEEPSEEK_API_KEY: no se puede medir.")
        salida["clasificador"] = {"error": "falta DEEPSEEK_API_KEY"}
        return

    clasificador = construir_clasificador(
        contenedor.config.clasificador_intencion, contenedor.modelo_lenguaje,
    )
    if clasificador is None:
        print("[x] AGORA_CLASIFICADOR=apagado: no hay clasificador que medir.")
        salida["clasificador"] = {"error": "clasificador apagado"}
        return

    aciertos = 0
    por_origen: dict[str, int] = {}
    errores: list[dict[str, str]] = []
    for mensaje, esperada in MENSAJES_ETIQUETADOS:
        try:
            c = clasificador.clasificar(mensaje)
        except Exception as exc:  # noqa: BLE001 -- ver _fallo()
            _fallo(mensaje, exc, errores)
            continue
        obtenida = c.intencion.value if c.intencion else "respaldo"
        por_origen[c.origen.value] = por_origen.get(c.origen.value, 0) + 1
        ok = c.intencion is esperada
        aciertos += ok
        marca = "ok " if ok else "NO "
        print(
            f"  {marca} {mensaje[:44]:<46} esperada={esperada.value:<17}"
            f"obtenida={obtenida:<17}{c.origen.value} {c.confianza:.2f}"
        )
        if not ok:
            errores.append(
                {"mensaje": mensaje, "esperada": esperada.value, "obtenida": obtenida,
                 "origen": c.origen.value, "motivo": c.motivo}
            )

    total = len(MENSAJES_ETIQUETADOS)
    print(f"\n  aciertos: {aciertos}/{total} ({100 * aciertos / total:.0f}%)")
    print(f"  origen:   {por_origen}")
    print(
        "\n  Como leerlo: un error hacia `respaldo` es BARATO (el turno corre "
        "con\n  las seis herramientas, como antes de la etapa 1). Un error "
        "entre dos\n  intenciones decididas es el caro: el turno corre con la "
        "lista blanca\n  equivocada y el modelo no puede hacer lo que le piden."
    )
    caros = [e for e in errores if e["obtenida"] != "respaldo"]
    if caros:
        print(f"  errores caros: {len(caros)} -- revisar el prompt de "
              "`agente/clasificacion/modelo.py` o las reglas")
    salida["clasificador"] = {
        "total": total, "aciertos": aciertos, "por_origen": por_origen,
        "errores": errores, "errores_caros": len(caros),
    }


def medir_soporte(contenedor, salida: dict[str, Any]) -> None:
    _linea("2. RAG DE SOPORTE (etapa 2) -- embeddings reales de OpenAI")
    buscador = contenedor.buscador_documental
    if buscador is None:
        print("[x] falta OPENAI_API_KEY: no se puede medir.")
        salida["soporte"] = {"error": "falta OPENAI_API_KEY"}
        return
    print(f"  corpus: {buscador.cantidad_de_fragmentos} fragmentos "
          f"de {contenedor.config.soporte_documentos_path}")
    print(f"  piso actual: PUNTAJE_MINIMO_POR_DEFECTO = {PUNTAJE_MINIMO_POR_DEFECTO}\n")

    dentro: list[float] = []
    fuera: list[float] = []
    detalle: list[dict[str, Any]] = []
    for pregunta, esperada_relevante in (
        [(p, True) for p in PREGUNTAS_DE_SOPORTE] + [(p, False) for p in PREGUNTAS_AJENAS]
    ):
        try:
            fragmentos = buscador.buscar(armar_consulta(pregunta, ()), limite=4)
        except Exception as exc:  # noqa: BLE001 -- ver _fallo()
            _fallo(pregunta, exc, detalle)
            continue
        etiqueta = "relevante" if esperada_relevante else "AJENA    "
        print(f"  [{etiqueta}] {pregunta}")
        for f in fragmentos:
            print(f"      {f.puntaje:.3f}  {f.fuente} :: {f.seccion[:44]}")
        if fragmentos:
            (dentro if esperada_relevante else fuera).append(fragmentos[0].puntaje)
        detalle.append({
            "pregunta": pregunta, "relevante": esperada_relevante,
            "puntajes": [round(f.puntaje, 4) for f in fragmentos],
            "fuentes": [f.fuente for f in fragmentos],
        })

    sugerido, razon = _sugerir_piso(dentro, fuera)
    print(f"\n  {razon}")
    if sugerido is not None:
        print(f"  -> sugerencia: PUNTAJE_MINIMO_POR_DEFECTO = {sugerido} "
              f"(hoy {PUNTAJE_MINIMO_POR_DEFECTO})")
        print("     en agora/agente/contexto_documental.py")
    salida["soporte"] = {
        "piso_actual": PUNTAJE_MINIMO_POR_DEFECTO, "piso_sugerido": sugerido,
        "razon": razon, "detalle": detalle,
    }


def medir_catalogo(contenedor, salida: dict[str, Any]) -> None:
    _linea("3. BUSQUEDA SEMANTICA DEL CATALOGO (etapa 4) -- embeddings reales")
    buscador = contenedor.buscador_semantico_productos
    if buscador is None:
        print("[x] falta OPENAI_API_KEY: no se puede medir.")
        salida["catalogo"] = {"error": "falta OPENAI_API_KEY"}
        return
    productos = [
        p
        for c in contenedor.catalogo.buscar_comercios()
        for p in contenedor.catalogo.buscar_productos(c.comercio_id)
    ]
    print(f"  catalogo: {len(productos)} productos")
    print(f"  piso actual: PARECIDO_MINIMO_POR_DEFECTO = {PARECIDO_MINIMO_POR_DEFECTO}\n")

    dentro: list[float] = []
    fuera: list[float] = []
    detalle: list[dict[str, Any]] = []
    for necesidad, esperada_relevante in (
        [(n, True) for n in NECESIDADES] + [(n, False) for n in NECESIDADES_AJENAS]
    ):
        try:
            puntuados = buscador.puntuar(necesidad, productos)[:4]
        except Exception as exc:  # noqa: BLE001 -- ver _fallo()
            _fallo(necesidad, exc, detalle)
            continue
        etiqueta = "necesidad" if esperada_relevante else "AJENA    "
        print(f"  [{etiqueta}] {necesidad}")
        for producto, parecido in puntuados:
            print(f"      {parecido:.3f}  {producto.nombre[:40]:<42} "
                  f"{producto.categoria}")
        if puntuados:
            (dentro if esperada_relevante else fuera).append(puntuados[0][1])
        detalle.append({
            "necesidad": necesidad, "relevante": esperada_relevante,
            "top": [{"producto": p.nombre, "parecido": round(v, 4)} for p, v in puntuados],
        })

    sugerido, razon = _sugerir_piso(dentro, fuera)
    print(f"\n  {razon}")
    if sugerido is not None:
        print(f"  -> sugerencia: PARECIDO_MINIMO_POR_DEFECTO = {sugerido} "
              f"(hoy {PARECIDO_MINIMO_POR_DEFECTO})")
        print("     en agora/adaptadores/busqueda_productos/"
              "semantico_en_memoria/buscador.py")
    print(
        "\n  Ojo con el juicio: que el top sea 'razonable' no alcanza. Lo que "
        "importa\n  es que las necesidades saquen puntajes CLARAMENTE mas "
        "altos que las ajenas.\n  Si no, el piso no separa nada y el modelo va "
        "a recibir relleno."
    )
    salida["catalogo"] = {
        "piso_actual": PARECIDO_MINIMO_POR_DEFECTO, "piso_sugerido": sugerido,
        "razon": razon, "detalle": detalle,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        prog="validar_con_modelos_reales",
        description="Mide contra DeepSeek/OpenAI reales lo que las cinco etapas "
        "no pudieron medir. No cambia nada: imprime.",
    )
    p.add_argument(
        "--solo", choices=["clasificador", "soporte", "catalogo"], action="append",
        help="medir solo esto (se puede repetir). Por defecto, las tres.",
    )
    p.add_argument("--json", action="store_true", help="ademas, un JSON al final")
    a = p.parse_args()
    cuales = a.solo or ["clasificador", "soporte", "catalogo"]

    load_dotenv()
    try:
        config = leer_configuracion(os.environ)
    except ConfiguracionInvalida as exc:
        print(f"[x] configuracion invalida: {exc}")
        return 1
    contenedor = construir(config)

    print("Llaves detectadas: "
          f"DEEPSEEK={'si' if config.deepseek_llave_api else 'NO'}  "
          f"OPENAI={'si' if config.openai_llave_api else 'NO'}")
    print("Esto hace llamadas REALES y cuesta (centavos). Ctrl+C para salir.")

    salida: dict[str, Any] = {}
    if "clasificador" in cuales:
        medir_clasificador(contenedor, salida)
    if "soporte" in cuales:
        medir_soporte(contenedor, salida)
    if "catalogo" in cuales:
        medir_catalogo(contenedor, salida)

    _linea("QUE QUEDA SIN MEDIR ACA")
    print(
        "  La lectura del aviso de reanudacion (etapa 5): si el modelo real\n"
        "  entiende que la persona firmo y llama a pagar() con los ids\n"
        "  correctos. Necesita una charla completa con firma desde el popup:\n\n"
        "    terminal 1:  python scripts/servir_api.py\n"
        "    terminal 2:  python -m agora.entradas.cli trazas --seguir\n"
        "    navegador:   comprar algo y firmar en el popup\n\n"
        "  En la traza tiene que verse el turno con \"pausa\": "
        '{"tipo": "firma_de_propuesta"...}\n'
        "  y, despues del click, un turno nuevo que llama a pagar UNA sola vez."
    )

    if a.json:
        print("\n" + json.dumps(salida, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
