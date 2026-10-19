"""El corpus real de `docs/soporte/`: lo que el nodo de soporte puede llegar a
ponerle delante al modelo. Estas pruebas no miran codigo, miran el
contenido -- es la segunda capa de la regla "ninguna cifra sale de una
recuperacion" (la primera es `usecase/agente/contexto_documental.py:sin_cifras`)."""

from __future__ import annotations

import re

import pytest

from agora.driven_adapters.recuperacion_langchain import cargar_markdown
from agora.app_service.config.configuracion import RAIZ_REPO, SOPORTE_DOCUMENTOS_POR_DEFECTO

_DOCUMENTOS = cargar_markdown(SOPORTE_DOCUMENTOS_POR_DEFECTO, raiz=RAIZ_REPO)

# Cifras escritas en palabras que la mascara de digitos no atraparia.
_CIFRAS_EN_PALABRAS = re.compile(
    r"\b(mil|millon(es)?|cientos?|doscientos|trescientos|quinientos|veinte|treinta|"
    r"cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)\b",
    re.IGNORECASE,
)
# Cosas de ingenieria que no tienen por que llegarle a una persona usuaria.
_INTERNO = re.compile(
    r"(secretos/|\.env|sk-|prv_|pub_|integrity|events_secret|ngrok|localhost|"
    r"agora_datos|\.py\b|sqlite)",
    re.IGNORECASE,
)


def test_el_corpus_existe_y_tiene_documentos():
    assert len(_DOCUMENTOS) >= 3
    assert all(d.fuente.startswith("docs/soporte/") for d in _DOCUMENTOS)


@pytest.mark.parametrize("documento", _DOCUMENTOS, ids=lambda d: d.fuente)
def test_ningun_documento_de_soporte_tiene_digitos(documento):
    assert not re.search(r"\d", documento.texto), (
        f"{documento.fuente} tiene digitos. Montos, topes y limites salen del "
        "mandato real, nunca de la documentacion de soporte."
    )
    assert not re.search(r"\d", documento.fuente)


@pytest.mark.parametrize("documento", _DOCUMENTOS, ids=lambda d: d.fuente)
def test_ningun_documento_de_soporte_escribe_cifras_en_palabras(documento):
    encontradas = _CIFRAS_EN_PALABRAS.findall(documento.texto)
    assert not encontradas, f"{documento.fuente}: {encontradas}"


@pytest.mark.parametrize("documento", _DOCUMENTOS, ids=lambda d: d.fuente)
def test_ningun_documento_de_soporte_filtra_detalles_internos(documento):
    encontradas = _INTERNO.findall(documento.texto)
    assert not encontradas, f"{documento.fuente}: {encontradas}"


@pytest.mark.parametrize("documento", _DOCUMENTOS, ids=lambda d: d.fuente)
def test_cada_documento_tiene_titulo_propio(documento):
    assert documento.texto.lstrip().startswith("# ")
