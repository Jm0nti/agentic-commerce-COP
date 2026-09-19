"""Leer el corpus de soporte del disco. Leer archivos es trabajo de
adaptador, no del agente ni del buscador: `BuscadorDocumentalLangChain`
recibe `DocumentoFuente` ya armados y no sabe que vinieron de Markdown en
disco.

POR QUE UN CORPUS CURADO (`docs/soporte/`) Y NO TODO `docs/`
--------------------------------------------------------------
`docs/` es documentacion de INGENIERIA: tiene rutas a archivos de secretos,
puertos, dominios del tunel, hallazgos internos, y cifras que ya quedaron
desactualizadas respecto del codigo. Un agente de soporte le contesta a la
persona que compra; indexar todo eso lo convertiria en un canal para
recitar detalles internos. `docs/soporte/` tiene solo lo que una persona
usuaria necesita saber, escrito para ella. Para agregar un documento, se
escribe ahi (o se apunta `AGORA_SOPORTE_DOCUMENTOS` a otra carpeta).
"""

from __future__ import annotations

from pathlib import Path

from ....puertos.recuperacion import DocumentoFuente


def cargar_markdown(directorio: Path, raiz: Path | None = None) -> list[DocumentoFuente]:
    """Todos los `*.md` bajo `directorio` (recursivo), en orden estable.
    `fuente` es la ruta relativa a `raiz` (o a `directorio`, si no se da),
    siempre con `/` -- la misma en Windows que en Linux, para que el modelo
    cite siempre igual. El titulo es el primer encabezado `# ` del archivo, o
    el nombre del archivo si no tiene."""
    if not directorio.is_dir():
        raise FileNotFoundError(f"no existe la carpeta de documentos de soporte: '{directorio}'")
    base = raiz or directorio
    documentos: list[DocumentoFuente] = []
    for ruta in sorted(directorio.rglob("*.md")):
        texto = ruta.read_text(encoding="utf-8")
        if not texto.strip():
            continue
        documentos.append(
            DocumentoFuente(
                fuente=_relativa(ruta, base, directorio),
                titulo=_titulo(texto, ruta),
                texto=texto,
            )
        )
    return documentos


def _titulo(texto: str, ruta: Path) -> str:
    for linea in texto.splitlines():
        if linea.startswith("# "):
            return linea[2:].strip()
    return ruta.stem


def _relativa(ruta: Path, base: Path, directorio: Path) -> str:
    """Relativa a `raiz` si el corpus vive adentro del repo; si alguien
    apunto `AGORA_SOPORTE_DOCUMENTOS` a una carpeta de afuera, relativa a esa
    carpeta -- nunca la ruta absoluta de la maquina."""
    try:
        return ruta.relative_to(base).as_posix()
    except ValueError:
        return ruta.relative_to(directorio).as_posix()
