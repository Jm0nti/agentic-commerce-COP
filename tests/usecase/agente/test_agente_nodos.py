"""Listas blancas por nodo (migracion a agentes, etapa 1): `validar_catalogo`
aplicado por nodo, la coherencia de `HERRAMIENTAS_POR_NODO`, y las rutas de
`agente/nodos.py`.

La prueba mas importante de este archivo es la de soporte: el agente de
soporte/FAQ nunca puede tener, ni por tabla ni por validacion, una
herramienta del camino del dinero. Si algun dia alguien se la asigna, esto
tiene que fallar antes de que la app levante.
"""

from __future__ import annotations

import pytest

from agora.usecase.agente.herramientas import (
    CATALOGO_DE_HERRAMIENTAS,
    HERRAMIENTAS_DEL_FLUJO_DE_DINERO,
    HERRAMIENTAS_POR_NODO,
    PROHIBIDAS,
    Herramienta,
    construir_herramientas,
    herramientas_para_nodo,
    validar_asignacion_por_nodo,
    validar_catalogo,
)
from agora.model.agente.intencion import (
    ClasificacionDeIntencion,
    OrigenDeClasificacion,
    TipoDeIntencion,
)
from agora.usecase.agente.nodos import (
    INSTRUCCIONES_POR_NODO,
    RUTA_DE_RESPALDO,
    RUTAS,
    Ruta,
    ruta_para,
)


def _funcion(*_a, **_k):
    return {"ok": True}


def _todas() -> list[Herramienta]:
    return construir_herramientas(
        buscar_comercios=_funcion,
        buscar_productos=_funcion,
        ver_producto=_funcion,
        armar_carrito=_funcion,
        pagar=_funcion,
        consultar_estado=_funcion,
    )


def _por_nombre(nombre: str) -> Herramienta:
    return next(h for h in _todas() if h.nombre == nombre)


def _decidida(intencion: TipoDeIntencion) -> ClasificacionDeIntencion:
    return ClasificacionDeIntencion(
        intencion=intencion, origen=OrigenDeClasificacion.REGLAS, confianza=1.0,
    )


# -- la tabla --------------------------------------------------------------- #


def test_la_tabla_real_es_coherente():
    validar_asignacion_por_nodo()


def test_la_tabla_tiene_los_siete_agentes_de_la_decision_3():
    assert set(HERRAMIENTAS_POR_NODO) == {
        "orquestador", "catalogo", "carrito_pago", "medios_de_pago", "estado", "soporte", "riesgo",
    }


def test_toda_herramienta_del_catalogo_tiene_exactamente_un_nodo_dueno():
    asignadas = [n for nombres in HERRAMIENTAS_POR_NODO.values() for n in nombres]
    assert sorted(asignadas) == sorted(CATALOGO_DE_HERRAMIENTAS)


def test_armar_carrito_y_pagar_siguen_en_el_mismo_nodo():
    """Decision 5 del documento, y el bug real de la etapa 6: separarlas
    exige releer `gap-chat-firma-mandato` y hablarlo con Juan antes."""
    assert set(HERRAMIENTAS_DEL_FLUJO_DE_DINERO) <= set(HERRAMIENTAS_POR_NODO["carrito_pago"])


def test_una_tabla_con_una_herramienta_en_dos_nodos_se_rechaza():
    tabla = {"catalogo": ("ver_producto",), "estado": ("ver_producto",)}
    with pytest.raises(RuntimeError, match="dos nodos"):
        validar_asignacion_por_nodo(tabla)


def test_una_tabla_con_una_herramienta_fuera_del_catalogo_se_rechaza():
    with pytest.raises(RuntimeError, match="catalogo autorizado"):
        validar_asignacion_por_nodo({"catalogo": ("borrar_todo",)})


@pytest.mark.parametrize("prohibida", PROHIBIDAS)
def test_una_tabla_con_una_herramienta_prohibida_se_rechaza(prohibida):
    with pytest.raises(RuntimeError):
        validar_asignacion_por_nodo({"soporte": (f"x_{prohibida}",)})


@pytest.mark.parametrize("nodo", [n for n in HERRAMIENTAS_POR_NODO if n != "carrito_pago"])
@pytest.mark.parametrize("herramienta", HERRAMIENTAS_DEL_FLUJO_DE_DINERO)
def test_ningun_nodo_fuera_de_carrito_pago_puede_ser_dueno_del_dinero(nodo, herramienta):
    with pytest.raises(RuntimeError, match="camino del dinero"):
        validar_asignacion_por_nodo({nodo: (herramienta,)})


# -- soporte: sin acceso fisico al dinero ------------------------------------ #


def test_soporte_no_tiene_ninguna_herramienta():
    assert HERRAMIENTAS_POR_NODO["soporte"] == ()
    assert not set(HERRAMIENTAS_POR_NODO["soporte"]) & set(HERRAMIENTAS_DEL_FLUJO_DE_DINERO)


@pytest.mark.parametrize("herramienta", HERRAMIENTAS_DEL_FLUJO_DE_DINERO)
def test_validar_catalogo_de_soporte_rechaza_toda_herramienta_de_dinero(herramienta):
    with pytest.raises(RuntimeError, match="no pertenece al dominio del nodo 'soporte'"):
        validar_catalogo([_por_nombre(herramienta)], nodo="soporte")


def test_soporte_recibe_cero_herramientas_aunque_le_pasen_todas():
    assert herramientas_para_nodo(_todas(), "soporte") == []


def test_la_ruta_de_soporte_no_habilita_nada_que_mueva_dinero():
    ruta = ruta_para(_decidida(TipoDeIntencion.SOPORTE))
    assert ruta.herramientas == frozenset()


# -- validar_catalogo por nodo ----------------------------------------------- #


def test_validar_catalogo_sin_nodo_se_comporta_como_antes():
    validar_catalogo(_todas())


def test_validar_catalogo_con_nodo_acepta_su_propia_lista_blanca():
    validar_catalogo([_por_nombre("ver_producto"), _por_nombre("buscar_comercios")], nodo="catalogo")


def test_validar_catalogo_con_nodo_rechaza_herramienta_valida_de_otro_dominio():
    with pytest.raises(RuntimeError, match="no pertenece al dominio del nodo 'catalogo'"):
        validar_catalogo([_por_nombre("consultar_estado")], nodo="catalogo")


def test_validar_catalogo_con_nodo_desconocido_levanta():
    with pytest.raises(RuntimeError, match="nodo desconocido"):
        validar_catalogo([], nodo="tesoreria")


def test_validar_catalogo_con_nodo_sigue_aplicando_prohibidas_primero():
    firmar = Herramienta(nombre="firmar_mandato", descripcion="", esquema={}, ejecutar=_funcion)
    with pytest.raises(RuntimeError, match="contiene 'firmar'"):
        validar_catalogo([firmar], nodo="carrito_pago")


@pytest.mark.parametrize("nodo", list(HERRAMIENTAS_POR_NODO))
def test_herramientas_para_nodo_devuelve_exactamente_su_lista_blanca(nodo):
    assert {h.nombre for h in herramientas_para_nodo(_todas(), nodo)} == set(
        HERRAMIENTAS_POR_NODO[nodo]
    )


# -- rutas -------------------------------------------------------------------- #


def test_toda_intencion_tiene_ruta():
    assert set(RUTAS) == set(TipoDeIntencion)


def test_toda_ruta_usa_nodos_declarados_y_con_instrucciones():
    for nodos in RUTAS.values():
        for nodo in nodos:
            assert nodo in HERRAMIENTAS_POR_NODO
            assert nodo in INSTRUCCIONES_POR_NODO


def test_ninguna_ruta_habilita_algo_fuera_del_catalogo():
    for intencion in TipoDeIntencion:
        assert ruta_para(_decidida(intencion)).herramientas <= set(CATALOGO_DE_HERRAMIENTAS)


def test_la_ruta_de_respaldo_es_el_agente_de_antes():
    """Sin clasificador, o sin certeza, el turno tiene que poder hacer lo
    mismo que antes de la etapa 1 -- ni mas, ni menos."""
    assert Ruta(clasificacion=None, nodos=RUTA_DE_RESPALDO).herramientas == set(
        CATALOGO_DE_HERRAMIENTAS
    )
    assert ruta_para(None).instrucciones() is None
    assert ruta_para(ClasificacionDeIntencion.respaldo("x")).instrucciones() is None


def test_la_ruta_de_compra_incluye_catalogo_para_ubicar_el_producto():
    ruta = ruta_para(_decidida(TipoDeIntencion.CARRITO_PAGO))
    assert ruta.herramientas == set(HERRAMIENTAS_POR_NODO["catalogo"]) | set(
        HERRAMIENTAS_POR_NODO["carrito_pago"]
    )


def test_la_ruta_de_estado_solo_consulta():
    assert ruta_para(_decidida(TipoDeIntencion.ESTADO)).herramientas == {"consultar_estado"}


def test_las_instrucciones_nombran_la_intencion_y_las_herramientas_habilitadas():
    texto = ruta_para(_decidida(TipoDeIntencion.ESTADO)).instrucciones()
    assert texto is not None
    assert "estado" in texto
    assert "consultar_estado" in texto
