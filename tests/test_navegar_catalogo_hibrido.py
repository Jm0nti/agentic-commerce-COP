"""El enrutador de recuperacion de `NavegarCatalogo` (migracion a agentes,
etapa 4): los tres peldanos de la decision 1, en orden.

Lo que se prueba aca, sobre todo:

  - **lo estructurado gana**: si el match por substring encuentra algo, el
    peldano semantico ni se consulta. No es una optimizacion, es la decision
    1 ("preferida siempre que alcance: es auditable y no puede devolver un
    producto inexistente");
  - **las reglas duras no se evaden por el camino semantico**: el buscador
    solo ve candidatos ya filtrados;
  - **sin buscador semantico, el comportamiento es el de antes de la etapa 4**.
"""

from __future__ import annotations

import pytest

from agora.adaptadores.persistencia.memoria import (
    RepositorioCarritosEnMemoria,
    RepositorioPropuestasEnMemoria,
)
from agora.adaptadores.sistema import GeneradorIdsUuid
from agora.aplicacion.navegar_catalogo import NavegarCatalogo
from agora.dominio.catalogo.modelo import Comercio, Disponibilidad, Producto
from agora.dominio.comun.dinero import Dinero
from agora.dominio.comun.errores import ComercioDesconocido, RecuperacionNoDisponible
from agora.puertos.busqueda_productos import FiltrosDeProducto

COMERCIO = Comercio(comercio_id="com_1", nombre="BellezaSur", categoria="belleza")

CREMA = Producto(
    producto_id="prd_crema", comercio_id="com_1", nombre="Crema hidratante",
    descripcion="para piel seca", precio=Dinero.de_pesos(30_000), categoria="belleza",
)
SERUM = Producto(
    producto_id="prd_serum", comercio_id="com_1", nombre="Serum facial",
    descripcion="hidrata", precio=Dinero.de_pesos(50_000), categoria="belleza",
)
CREMA_AGOTADA = Producto(
    producto_id="prd_crema2", comercio_id="com_1", nombre="Crema nutritiva",
    descripcion="piel muy seca", precio=Dinero.de_pesos(28_000), categoria="belleza",
    disponibilidad=Disponibilidad.AGOTADO,
)
TODOS = [CREMA, SERUM, CREMA_AGOTADA]


class _CatalogoFalso:
    """Substring sobre nombre y descripcion, igual que el adaptador semilla."""

    def __init__(self) -> None:
        self.consultas: list[str] = []

    def buscar_comercios(self, consulta: str = ""):
        return [COMERCIO]

    def buscar_productos(self, comercio_id: str, consulta: str = ""):
        if comercio_id != "com_1":
            raise ComercioDesconocido(comercio_id)
        self.consultas.append(consulta)
        termino = consulta.strip().lower()
        if not termino:
            return list(TODOS)
        return [
            p for p in TODOS
            if termino in p.nombre.lower() or termino in p.descripcion.lower()
        ]

    def ver_producto(self, producto_id: str):
        return next(p for p in TODOS if p.producto_id == producto_id)


class _SemanticoEspia:
    def __init__(self, devuelve=None, falla: bool = False) -> None:
        self.pedidos: list[tuple[str, list[str], int]] = []
        self._devuelve = devuelve
        self._falla = falla

    def buscar(self, consulta, candidatos, limite=5):
        self.pedidos.append((consulta, [p.producto_id for p in candidatos], limite))
        if self._falla:
            raise RecuperacionNoDisponible("el proveedor no contesta")
        return list(self._devuelve if self._devuelve is not None else candidatos[:limite])


def _navegar(semantico=None, catalogo=None) -> NavegarCatalogo:
    return NavegarCatalogo(
        catalogo=catalogo or _CatalogoFalso(),
        carritos=RepositorioCarritosEnMemoria(),
        ids=GeneradorIdsUuid(),
        propuestas=RepositorioPropuestasEnMemoria(),
        semantico=semantico,
    )


# -- peldano 1: estructurado, y gana ---------------------------------------- #


def test_sin_semantico_se_comporta_como_antes_de_la_etapa_4():
    nav = _navegar()

    assert [p.producto_id for p in nav.buscar_productos("com_1")] == [
        "prd_crema", "prd_serum", "prd_crema2",
    ]
    assert [p.producto_id for p in nav.buscar_productos("com_1", "serum")] == ["prd_serum"]


def test_si_lo_estructurado_encuentra_algo_el_semantico_no_se_consulta():
    """Decision 1: lo auditable primero. Ademas ahorra una llamada a
    embeddings en el caso mas frecuente."""
    espia = _SemanticoEspia()
    nav = _navegar(semantico=espia)

    encontrados = nav.buscar_productos("com_1", "crema")

    assert [p.producto_id for p in encontrados] == ["prd_crema", "prd_crema2"]
    assert espia.pedidos == []


def test_una_consulta_vacia_no_llega_al_semantico():
    espia = _SemanticoEspia()
    nav = _navegar(semantico=espia)

    nav.buscar_productos("com_1", "   ")

    assert espia.pedidos == []


def test_propaga_comercio_desconocido():
    with pytest.raises(ComercioDesconocido):
        _navegar().buscar_productos("com_x", "crema")


# -- peldano 2: reglas duras sobre cualquier peldano ------------------------- #


def test_los_filtros_se_aplican_a_lo_estructurado():
    nav = _navegar()

    encontrados = nav.buscar_productos(
        "com_1", "crema", filtros=FiltrosDeProducto(solo_disponibles=True),
    )

    assert [p.producto_id for p in encontrados] == ["prd_crema"]


def test_el_semantico_solo_ve_candidatos_ya_filtrados():
    """La propiedad que no se negocia: una regla dura no se evade por el
    camino semantico. El buscador ni siquiera ve el producto agotado."""
    espia = _SemanticoEspia()
    nav = _navegar(semantico=espia)

    nav.buscar_productos(
        "com_1", "algo para piel reseca", filtros=FiltrosDeProducto(solo_disponibles=True),
    )

    _, candidatos, _ = espia.pedidos[0]
    assert candidatos == ["prd_crema", "prd_serum"]
    assert "prd_crema2" not in candidatos


def test_si_los_filtros_no_dejan_candidatos_el_semantico_no_se_consulta():
    espia = _SemanticoEspia()
    nav = _navegar(semantico=espia)

    encontrados = nav.buscar_productos(
        "com_1", "algo para piel reseca", filtros=FiltrosDeProducto(precio_max_cop=1),
    )

    assert encontrados == []
    assert espia.pedidos == []


# -- peldano 3: semantico como respaldo -------------------------------------- #


def test_cuando_lo_estructurado_no_encuentra_nada_entra_el_semantico():
    """El caso del documento: la persona describe la necesidad en vez de
    nombrar el producto."""
    espia = _SemanticoEspia(devuelve=[CREMA])
    nav = _navegar(semantico=espia)

    encontrados = nav.buscar_productos("com_1", "algo para piel reseca")

    assert [p.producto_id for p in encontrados] == ["prd_crema"]
    consulta, candidatos, limite = espia.pedidos[0]
    assert consulta == "algo para piel reseca"
    # Todo el comercio como candidato: lo estructurado ya fallo.
    assert candidatos == ["prd_crema", "prd_serum", "prd_crema2"]
    assert limite == 5


def test_el_limite_semantico_se_puede_ajustar():
    espia = _SemanticoEspia()
    nav = _navegar(semantico=espia)

    nav.buscar_productos("com_1", "algo para piel reseca", limite_semantico=2)

    assert espia.pedidos[0][2] == 2


def test_si_el_proveedor_de_embeddings_esta_caido_la_busqueda_devuelve_vacio():
    """Una busqueda sin resultados es una respuesta valida del catalogo (lo
    dice `puertos/catalogo.py`), asi que el turno sigue. Lo que NO puede
    pasar es que una charla se caiga porque OpenAI no contesto."""
    nav = _navegar(semantico=_SemanticoEspia(falla=True))

    assert nav.buscar_productos("com_1", "algo para piel reseca") == []


def test_el_semantico_nunca_se_usa_para_reordenar_lo_que_ya_se_encontro():
    """Si lo estructurado acerto, el orden del catalogo es el que vale: un
    modelo de embeddings no tiene autoridad para reordenar un resultado
    exacto."""
    espia = _SemanticoEspia(devuelve=[SERUM])
    nav = _navegar(semantico=espia)

    encontrados = nav.buscar_productos("com_1", "crema")

    assert [p.producto_id for p in encontrados] == ["prd_crema", "prd_crema2"]
    assert espia.pedidos == []
