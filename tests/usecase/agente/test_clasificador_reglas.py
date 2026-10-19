"""`ClasificadorPorReglas`: el camino rapido deterministico. Lo que importa
probar no es solo que acierte, sino que SE ABSTENGA cuando hay duda -- una
regla que adivina es peor que no tener regla.

Los avisos del sistema de abajo reproducen el formato de los que arman
`entry_points/api_rest/app.py` (firmar/retomar) y `entry_points/api_rest/sesiones.py`
(webhook). Los reales, generados por las rutas de verdad, ya los cubre
`tests/entry_points/test_api_app.py`: ahi `_ModeloProgramable.generar` levanta
`AssertionError`, asi que si alguno de esos avisos dejara de resolverse por
reglas y cayera al clasificador con modelo, esas pruebas fallarian.
"""

from __future__ import annotations

import pytest

from agora.usecase.agente.clasificacion.reglas import ClasificadorPorReglas, normalizar
from agora.model.agente.intencion import OrigenDeClasificacion, TipoDeIntencion

AVISO_FIRMA = (
    "(la persona firmo la propuesta prp_1a2b3c4d5e6f desde el popup. El mandato quedo "
    "con mandato_id=mnd_0a1b2c3d4e5f, carrito_id=car_9f8e7d6c5b4a. Continua el flujo de "
    "compra llamando a pagar() con ese mandato_id y ese carrito_id.)"
)
AVISO_RETOMAR = (
    "(la persona aprobo desde el popup la confirmacion pendiente de la intencion "
    "int_abcdef123456. ejecutado=True, motivo=APPROVED. Confirma el estado con "
    "consultar_estado antes de contarle a la persona el resultado.)"
)
AVISO_WEBHOOK = (
    "(el webhook de la pasarela ya resolvio la intencion int_abcdef123456 de forma "
    "asincronica -- estado='aprobado'. Confirma con consultar_estado antes de contarle "
    "a la persona el resultado.)"
)


@pytest.fixture
def reglas() -> ClasificadorPorReglas:
    return ClasificadorPorReglas()


@pytest.mark.parametrize(
    "mensaje, esperada",
    [
        ("quiero comprar algo barato", TipoDeIntencion.CARRITO_PAGO),
        ("Cómpralo, porfa", TipoDeIntencion.CARRITO_PAGO),
        ("agregalo al carrito", TipoDeIntencion.CARRITO_PAGO),
        ("ya firme, el mandato es mnd_0a1b2c3d4e5f", TipoDeIntencion.CARRITO_PAGO),
        ("¿Qué tiendas hay?", TipoDeIntencion.CATALOGO),
        ("cuánto cuesta el cuaderno", TipoDeIntencion.CATALOGO),
        ("muestrame lo de prd_e4544c48a5f2", TipoDeIntencion.CATALOGO),
        ("¿cuál es el estado de mi pago?", TipoDeIntencion.ESTADO),
        ("ya confirmé en la otra terminal", TipoDeIntencion.ESTADO),
        ("¿sigue pendiente?", TipoDeIntencion.ESTADO),
        ("quiero vincular mi Nequi", TipoDeIntencion.MEDIOS_DE_PAGO),
        ("como revoco un medio de pago", TipoDeIntencion.MEDIOS_DE_PAGO),
        ("¿qué es un mandato?", TipoDeIntencion.SOPORTE),
        ("¿por qué me piden firmar?", TipoDeIntencion.SOPORTE),
        ("hola", TipoDeIntencion.FUERA_DE_ALCANCE),
        ("¡Muchas gracias!", TipoDeIntencion.FUERA_DE_ALCANCE),
    ],
)
def test_mensajes_inequivocos_se_deciden_por_reglas(reglas, mensaje, esperada):
    clasificacion = reglas.clasificar(mensaje)
    assert clasificacion.intencion is esperada, clasificacion.motivo
    assert clasificacion.origen is OrigenDeClasificacion.REGLAS
    assert clasificacion.confianza == 1.0


@pytest.mark.parametrize(
    "aviso, esperada",
    [
        (AVISO_FIRMA, TipoDeIntencion.CARRITO_PAGO),
        (AVISO_RETOMAR, TipoDeIntencion.ESTADO),
        (AVISO_WEBHOOK, TipoDeIntencion.ESTADO),
    ],
)
def test_los_avisos_del_sistema_nunca_necesitan_al_modelo(reglas, aviso, esperada):
    clasificacion = reglas.clasificar(aviso)
    assert clasificacion.decidida
    assert clasificacion.intencion is esperada


@pytest.mark.parametrize(
    "mensaje",
    [
        "si, dale",                        # continuacion: solo se entiende con historial
        "ese mismo",
        "ok",
        "que paso con mi compra, la quiero pagar de nuevo",  # estado + carrito
        "como funciona pagar con nequi",   # soporte + carrito + medios
        "hola, cual es el clima hoy",      # no es solo social y no calza con nada
    ],
)
def test_ante_la_duda_se_abstiene(reglas, mensaje):
    clasificacion = reglas.clasificar(mensaje)
    assert not clasificacion.decidida
    assert clasificacion.intencion is None
    assert clasificacion.origen is OrigenDeClasificacion.RESPALDO


def test_compra_absorbe_catalogo_porque_su_ruta_ya_lo_incluye(reglas):
    clasificacion = reglas.clasificar("quiero comprar los productos mas baratos de la tienda")
    assert clasificacion.intencion is TipoDeIntencion.CARRITO_PAGO
    assert "absorbe catalogo" in clasificacion.motivo


def test_compra_no_absorbe_estado(reglas):
    clasificacion = reglas.clasificar("quiero comprar otra vez, sigue pendiente la anterior?")
    assert not clasificacion.decidida
    assert "ambiguo" in clasificacion.motivo


def test_hola_con_un_pedido_no_es_solo_social(reglas):
    assert reglas.clasificar("hola, quiero comprar un cuaderno").intencion is (
        TipoDeIntencion.CARRITO_PAGO
    )


def test_ignora_el_historial(reglas):
    """Una regla que dependiera del contexto dejaria de ser inequivoca: el
    historial es asunto del clasificador con modelo."""
    from agora.model.agente.gateways.modelo_lenguaje import Mensaje

    historial = [Mensaje(rol="assistant", contenido="¿Queres que arme el carrito?")]
    assert not reglas.clasificar("si", historial).decidida


def test_normalizar_quita_tildes_mayusculas_y_espacios():
    assert normalizar("  ¿Cuánto   CUESTA?  ") == "cuanto cuesta?"
