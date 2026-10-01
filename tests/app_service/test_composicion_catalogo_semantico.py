"""`OPENAI_API_KEY` -> buscador semantico de catalogo en el `Contenedor`
real (migracion a agentes, etapa 4).

Mismo contrato que la etapa 2 con el buscador documental: sin llave no hay
buscador y la app no cambia; con llave se arma **sin tocar la red**, y los
dos indices (documentacion y catalogo) son distintos aunque compartan la
llave y el proveedor de embeddings.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agora.app_service.config.agente import construir_agente
from agora.app_service.config.configuracion import leer_configuracion
from agora.app_service.config.contenedor import construir
from agora.model.catalogo.gateways.busqueda_productos import FiltrosDeProducto
from agora.model.agente.gateways.modelo_lenguaje import RespuestaModelo


def _entorno(tmp_path, **extra) -> dict:
    return {
        "AGORA_BITACORA": str(tmp_path / "recibos.jsonl"),
        "PAGADOR_EMAIL": "juan@correo-real.com",
        **extra,
    }


def _contenedor(tmp_path, **extra):
    return construir(leer_configuracion(_entorno(tmp_path, **extra)))


def test_sin_llave_no_hay_buscador_semantico_de_productos(tmp_path):
    contenedor = _contenedor(tmp_path)

    assert contenedor.buscador_semantico_productos is None
    assert contenedor.navegar_catalogo._semantico is None


def test_con_llave_se_arma_sobre_el_catalogo_real_y_sin_tocar_la_red(tmp_path):
    """Construir el `Contenedor` no embebe nada: la lista de productos se
    guarda, y el indice se arma recien en la primera busqueda que lo
    necesite (decision 8 de la etapa 2, que sigue valiendo)."""
    contenedor = _contenedor(tmp_path, OPENAI_API_KEY="sk-de-mentira")

    buscador = contenedor.buscador_semantico_productos
    assert buscador is not None
    assert not buscador.indexado
    assert buscador.cantidad_de_productos > 0


def test_el_buscador_ve_todo_el_catalogo_no_un_solo_comercio(tmp_path):
    """`RepositorioCatalogo` solo sabe buscar por comercio; el contenedor
    recorre los comercios para armar el indice completo."""
    contenedor = _contenedor(tmp_path, OPENAI_API_KEY="sk-de-mentira")

    comercios = contenedor.catalogo.buscar_comercios()
    total = sum(len(contenedor.catalogo.buscar_productos(c.comercio_id)) for c in comercios)

    assert contenedor.buscador_semantico_productos.cantidad_de_productos == total
    assert len(comercios) > 1


def test_el_indice_del_catalogo_y_el_de_la_documentacion_son_distintos(tmp_path):
    """Decision 1: dos indices que nunca se mezclan. Comparten la llave y el
    proveedor de embeddings, nada mas."""
    contenedor = _contenedor(tmp_path, OPENAI_API_KEY="sk-de-mentira")

    assert contenedor.buscador_documental is not None
    assert contenedor.buscador_semantico_productos is not None
    assert contenedor.buscador_documental is not contenedor.buscador_semantico_productos


def test_navegar_catalogo_recibe_el_buscador(tmp_path):
    contenedor = _contenedor(tmp_path, OPENAI_API_KEY="sk-de-mentira")

    assert contenedor.navegar_catalogo._semantico is contenedor.buscador_semantico_productos


# -- la herramienta, de punta a punta ---------------------------------------- #


class _ModeloDeMentira:
    def generar(self, sistema, instruccion):
        raise AssertionError("no se usa")

    def responder(self, mensajes, herramientas):
        return RespuestaModelo(contenido="ok")


def _agente_real(tmp_path, **extra):
    contenedor = replace(_contenedor(tmp_path, **extra), modelo_lenguaje=_ModeloDeMentira())
    agente = construir_agente(contenedor)
    assert agente is not None
    return contenedor, agente


def test_buscar_productos_expone_los_filtros_duros_en_su_esquema(tmp_path):
    """Las reglas duras son parametros de la herramienta, no algo que el
    modelo filtre despues leyendo la lista: un filtro aplicado en codigo no
    se puede desobedecer."""
    _, agente = _agente_real(tmp_path)

    esquema = agente._herramientas["buscar_productos"].esquema

    assert {"solo_disponibles", "precio_min_cop", "precio_max_cop"} <= set(esquema["properties"])
    assert esquema["required"] == ["comercio_id"]


def test_la_herramienta_filtra_de_verdad_por_precio(tmp_path):
    contenedor, agente = _agente_real(tmp_path)
    comercio = contenedor.catalogo.buscar_comercios()[0]
    productos = contenedor.catalogo.buscar_productos(comercio.comercio_id)
    tope = min(p.precio.pesos for p in productos)

    resultado = agente._herramientas["buscar_productos"].ejecutar(
        comercio_id=comercio.comercio_id, precio_max_cop=tope,
    )

    assert resultado, "el catalogo semilla deberia tener al menos un producto en el tope"
    assert all(p["precio_cop"] <= tope for p in resultado)


def test_la_herramienta_filtra_de_verdad_por_disponibilidad(tmp_path):
    contenedor, agente = _agente_real(tmp_path)
    comercio = contenedor.catalogo.buscar_comercios()[0]

    resultado = agente._herramientas["buscar_productos"].ejecutar(
        comercio_id=comercio.comercio_id, solo_disponibles=True,
    )

    assert all(p["disponibilidad"] == "en_stock" for p in resultado)


def test_un_rango_invertido_del_modelo_no_tumba_el_turno(tmp_path):
    """`FiltrosDeProducto` levanta `ValueError`, que `Agente._ejecutar` no
    traduce -- por eso se atrapa en la frontera de traduccion y vuelve como
    resultado leible para que el modelo corrija."""
    contenedor, agente = _agente_real(tmp_path)
    comercio = contenedor.catalogo.buscar_comercios()[0]

    resultado = agente._herramientas["buscar_productos"].ejecutar(
        comercio_id=comercio.comercio_id, precio_min_cop=900_000, precio_max_cop=1_000,
    )

    assert "error" in resultado
    assert "filtros invalidos" in resultado["error"]


def test_sin_llave_la_busqueda_del_catalogo_sigue_siendo_la_estructurada(tmp_path):
    """Sin `OPENAI_API_KEY`, `buscar_productos` devuelve exactamente lo que
    devolvia antes de la etapa 4."""
    contenedor = _contenedor(tmp_path)
    comercio = contenedor.catalogo.buscar_comercios()[0]

    por_el_caso_de_uso = contenedor.navegar_catalogo.buscar_productos(
        comercio.comercio_id, "", filtros=FiltrosDeProducto(),
    )
    por_el_puerto = contenedor.catalogo.buscar_productos(comercio.comercio_id, "")

    assert por_el_caso_de_uso == por_el_puerto
