"""El peldano 2 y el peldano 3 de la decision 1 (migracion a agentes, etapa
4): las reglas duras (`FiltrosDeProducto`) y el buscador semantico en
memoria.

La propiedad que mas importa de este archivo: **el camino semantico no puede
devolver nada que las reglas duras no hayan dejado pasar.** No porque el
adaptador se porte bien, sino porque solo ve los candidatos que le dan.
"""

from __future__ import annotations

import pytest

from agora.driven_adapters.busqueda_semantica_memoria import (
    PARECIDO_MINIMO_POR_DEFECTO,
    BuscadorSemanticoEnMemoria,
    texto_de,
)
from agora.model.catalogo.modelo import Disponibilidad, Producto
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import RecuperacionNoDisponible
from agora.model.catalogo.gateways.busqueda_productos import FiltrosDeProducto

CREMA = Producto(
    producto_id="prd_crema", comercio_id="com_1", nombre="Crema hidratante",
    descripcion="para piel seca y reseca", precio=Dinero.de_pesos(30_000), categoria="belleza",
)
SERUM = Producto(
    producto_id="prd_serum", comercio_id="com_1", nombre="Serum facial",
    descripcion="hidrata la piel", precio=Dinero.de_pesos(50_000), categoria="belleza",
)
AUDIFONOS = Producto(
    producto_id="prd_audifonos", comercio_id="com_1", nombre="Audifonos",
    descripcion="bluetooth", precio=Dinero.de_pesos(120_000), categoria="tecnologia",
)
CREMA_AGOTADA = Producto(
    producto_id="prd_crema2", comercio_id="com_1", nombre="Crema nutritiva",
    descripcion="para piel muy reseca", precio=Dinero.de_pesos(28_000), categoria="belleza",
    disponibilidad=Disponibilidad.AGOTADO,
)
TODOS = [CREMA, SERUM, AUDIFONOS, CREMA_AGOTADA]


class _EmbeddingsDeMentira:
    """Bolsa de palabras sobre un vocabulario fijo. No es un modelo: es un
    doble deterministico que hace que "piel reseca" se parezca a la crema y
    no a los audifonos, que es lo unico que estas pruebas necesitan."""

    VOCABULARIO = (
        "piel seca reseca hidrata hidratante nutritiva crema serum facial "
        "audifonos bluetooth belleza tecnologia"
    ).split()

    def __init__(self) -> None:
        self.documentos_embebidos = 0
        self.consultas_embebidas = 0

    def _vector(self, texto: str) -> list[float]:
        texto = texto.lower()
        return [1.0 if palabra in texto else 0.0 for palabra in self.VOCABULARIO]

    def embeber_documentos(self, textos):
        self.documentos_embebidos += 1
        return [self._vector(t) for t in textos]

    def embeber_consulta(self, texto):
        self.consultas_embebidas += 1
        return self._vector(texto)


class _EmbeddingsCaidos:
    def embeber_documentos(self, textos):
        raise RecuperacionNoDisponible("el proveedor no contesta")

    def embeber_consulta(self, texto):
        raise RecuperacionNoDisponible("el proveedor no contesta")


def _buscador(productos=None, embeddings=None) -> BuscadorSemanticoEnMemoria:
    return BuscadorSemanticoEnMemoria(
        productos if productos is not None else TODOS,
        embeddings or _EmbeddingsDeMentira(),
    )


# --------------------------------------------------------------------------- #
# Peldano 2: las reglas duras
# --------------------------------------------------------------------------- #


def test_sin_filtros_no_filtra_nada():
    """El default tiene que ser "igual que antes de la etapa 4": si esto
    cambia, `buscar_productos` empieza a esconder productos que hoy muestra."""
    filtros = FiltrosDeProducto()

    assert filtros.vacios
    assert filtros.aplicar(TODOS) == TODOS


def test_solo_disponibles_saca_lo_agotado():
    assert FiltrosDeProducto(solo_disponibles=True).aplicar(TODOS) == [CREMA, SERUM, AUDIFONOS]


def test_rango_de_precio_es_inclusivo_en_los_dos_extremos():
    filtros = FiltrosDeProducto(precio_min_cop=30_000, precio_max_cop=50_000)

    assert filtros.aplicar(TODOS) == [CREMA, SERUM]


def test_los_filtros_se_combinan():
    filtros = FiltrosDeProducto(solo_disponibles=True, precio_max_cop=40_000)

    assert filtros.aplicar(TODOS) == [CREMA]


def test_aplicar_conserva_el_orden_de_entrada():
    al_reves = list(reversed(TODOS))

    assert FiltrosDeProducto().aplicar(al_reves) == al_reves


def test_un_rango_invertido_se_rechaza_al_construirlo():
    """Un modelo puede inventar precio_min > precio_max. Que falle al armar
    el filtro -- y no que devuelva vacio en silencio -- es lo que permite
    contestarle algo util."""
    with pytest.raises(ValueError, match="rango de precio invalido"):
        FiltrosDeProducto(precio_min_cop=90_000, precio_max_cop=10_000)


@pytest.mark.parametrize("campo", ["precio_min_cop", "precio_max_cop"])
def test_un_precio_negativo_se_rechaza(campo):
    with pytest.raises(ValueError, match="no puede ser negativo"):
        FiltrosDeProducto(**{campo: -1})


# --------------------------------------------------------------------------- #
# Peldano 3: el buscador semantico
# --------------------------------------------------------------------------- #


def test_encuentra_por_significado_lo_que_el_substring_no_encontraria():
    """El caso que motiva la decision 1 del documento: "algo para piel
    reseca" no contiene la palabra "crema" ni "serum"."""
    encontrados = _buscador().buscar("algo para piel reseca", TODOS)

    # Las dos cremas primero. Cual de las dos gana depende del doble de
    # embeddings, no de la logica que se prueba aca: se asienta el conjunto.
    assert {p.producto_id for p in encontrados[:2]} == {"prd_crema", "prd_crema2"}
    assert AUDIFONOS not in encontrados


def test_nunca_devuelve_algo_que_no_este_en_candidatos():
    """LA propiedad de esta etapa. El indice conoce las cuatro cremas, pero
    si quien llama ya descarto una por una regla dura, el camino semantico
    no la puede resucitar."""
    solo_disponibles = FiltrosDeProducto(solo_disponibles=True).aplicar(TODOS)

    encontrados = _buscador().buscar("algo para piel reseca", solo_disponibles)

    assert CREMA_AGOTADA not in encontrados
    assert all(p in solo_disponibles for p in encontrados)


def test_con_candidatos_vacios_no_devuelve_nada_y_no_consulta_al_proveedor():
    embeddings = _EmbeddingsDeMentira()

    assert _buscador(embeddings=embeddings).buscar("piel reseca", []) == []
    assert embeddings.consultas_embebidas == 0


def test_una_consulta_vacia_no_consulta_al_proveedor():
    embeddings = _EmbeddingsDeMentira()

    assert _buscador(embeddings=embeddings).buscar("   ", TODOS) == []
    assert embeddings.consultas_embebidas == 0


def test_una_consulta_ajena_al_catalogo_no_devuelve_relleno():
    """Sin piso de parecido, un vector store siempre devuelve los `k` mas
    cercanos aunque no tengan nada que ver -- y el modelo los presentaria
    como respuesta."""
    assert _buscador().buscar("tractor agricola usado", TODOS) == []


def test_respeta_el_limite():
    encontrados = _buscador().buscar("piel hidratante crema serum", TODOS, limite=1)

    assert len(encontrados) == 1


def test_limite_invalido_se_rechaza():
    with pytest.raises(ValueError, match="limite invalido"):
        _buscador().buscar("piel", TODOS, limite=0)


def test_el_catalogo_se_embebe_recien_en_la_primera_busqueda_y_una_sola_vez():
    """Construir el `Contenedor` no puede tocar la red (decision 8 de la
    etapa 2, que sigue valiendo)."""
    embeddings = _EmbeddingsDeMentira()
    buscador = _buscador(embeddings=embeddings)

    assert not buscador.indexado
    assert embeddings.documentos_embebidos == 0

    buscador.buscar("piel reseca", TODOS)
    buscador.buscar("audifonos", TODOS)

    assert buscador.indexado
    assert embeddings.documentos_embebidos == 1


def test_una_falla_del_proveedor_no_deja_un_indice_a_medias():
    buscador = _buscador(embeddings=_EmbeddingsCaidos())

    with pytest.raises(RecuperacionNoDisponible):
        buscador.buscar("piel reseca", TODOS)

    assert not buscador.indexado


def test_un_catalogo_vacio_no_rompe():
    assert _buscador(productos=[]).buscar("lo que sea", TODOS) == []


def test_puntuar_devuelve_los_parecidos_de_mayor_a_menor():
    puntuados = _buscador().puntuar("algo para piel reseca", TODOS)

    assert [p.producto_id for p, _ in puntuados] == [
        p.producto_id for p, _ in sorted(puntuados, key=lambda x: -x[1])
    ]
    assert all(0.0 <= parecido <= 1.0001 for _, parecido in puntuados)


def test_puntuar_no_aplica_el_piso_porque_es_para_calibrarlo():
    """Un umbral que no se puede ver no se puede elegir, solo adivinar.
    `buscar` si lo aplica -- esta es la version cruda, para medir."""
    consulta = "tractor agricola usado"

    assert _buscador().buscar(consulta, TODOS) == []
    puntuados = _buscador().puntuar(consulta, TODOS)
    assert len(puntuados) == len(TODOS)
    assert all(parecido < PARECIDO_MINIMO_POR_DEFECTO for _, parecido in puntuados)


def test_puntuar_tampoco_puede_salirse_de_los_candidatos():
    solo_uno = [CREMA]

    puntuados = _buscador().puntuar("piel reseca", solo_uno)

    assert [p.producto_id for p, _ in puntuados] == ["prd_crema"]


def test_el_texto_embebido_no_incluye_precio_ni_disponibilidad():
    """Un precio no se parece a nada: meterlo en el vector solo agrega
    ruido, y peor -- haria que "barato" pareciera un atributo semantico
    cuando es una regla dura con su propio filtro."""
    texto = texto_de(CREMA)

    assert "Crema hidratante" in texto
    assert "piel seca" in texto
    assert "belleza" in texto
    assert "30000" not in texto.replace(".", "")
    assert Disponibilidad.EN_STOCK.value not in texto
