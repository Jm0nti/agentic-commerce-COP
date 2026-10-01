"""La pasarela simulada: los cuatro desenlaces, a voluntad.

ADR-2 (`docs/arquitectura-v2.md`): la simulada no es un mock de pruebas, es
un adaptador de produccion para el modo demo, y tiene que poder reproducir
aprobado, declinado, declinado por antifraude y pendiente sin gastar y sin
depender de que Wompi coopere. Estas pruebas verifican los cuatro y, de paso,
que la heuristica por defecto reproduce la senal real documentada en
`docs/hallazgo-afe.md`: un correo en un dominio reservado por la RFC 2606
declina por antifraude.
"""

from __future__ import annotations

import pytest

from agora.adaptadores.pasarelas.simulada import (
    APROBADO,
    DECLINADO_ANTIFRAUDE,
    AdaptadorSimulado,
    Desenlace,
    GuionSimulado,
)
from agora.adaptadores.sistema.ids import GeneradorIdsUuid
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import ErrorDePasarela
from agora.model.pago.modelo import Ambiente, EstadoCobro, MedioDePagoRef, OrdenDeCobro, Proveedor


def _pasarela() -> AdaptadorSimulado:
    return AdaptadorSimulado(GeneradorIdsUuid(), Ambiente.SANDBOX)


def _orden(correo: str, monto_pesos: int = 15_000) -> OrdenDeCobro:
    return OrdenDeCobro(
        intencion_id="int_1",
        medio=MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_1"),
        monto=Dinero.de_pesos(monto_pesos),
        glosa="compra de prueba",
        correo_pagador=correo,
    )


def test_correo_normal_aprueba():
    r = _pasarela().cobrar(_orden("juan@correo-real.com"))
    assert r.estado is EstadoCobro.APROBADO
    assert r.afe_decision == "ACCEPT"
    assert not r.detenido_por_antifraude


def test_dominio_reservado_declina_por_antifraude():
    """Reproduce `docs/hallazgo-afe.md`: el correo `boveda+poc@example.com`
    -- un dominio que la RFC 2606 reserva y que nunca entrega -- fue lo que
    el motor antifraude de Wompi leyo como fraude en la primera corrida real.
    """
    r = _pasarela().cobrar(_orden("boveda+poc@example.com"))
    assert r.estado is EstadoCobro.RECHAZADO
    assert r.afe_decision == "DECLINE"
    assert r.detenido_por_antifraude


def test_marcador_declina_es_un_rechazo_generico_no_antifraude():
    r = _pasarela().cobrar(_orden("cliente.declina@correo-real.com"))
    assert r.estado is EstadoCobro.RECHAZADO
    assert not r.detenido_por_antifraude


def test_marcador_pendiente_queda_pendiente():
    r = _pasarela().cobrar(_orden("cliente.pendiente@correo-real.com"))
    assert r.estado is EstadoCobro.PENDIENTE
    assert not r.estado.es_final


def test_resolver_pendiente_cierra_el_ciclo():
    """Imita el webhook `transaction.updated` que en Wompi real convierte un
    PENDING en su estado final (`docs/arquitectura-v2.md`, pasos 7d-8)."""
    pasarela = _pasarela()
    r = pasarela.cobrar(_orden("cliente.pendiente@correo-real.com"))
    resuelto = pasarela.resolver_pendiente(r.id_externo, APROBADO)

    assert resuelto.estado is EstadoCobro.APROBADO
    assert pasarela.consultar_cobro(r.id_externo).estado is EstadoCobro.APROBADO


def test_referencia_es_la_intencion_no_un_uuid_nuevo():
    """ADR-6: la idempotencia se deriva de `intencion_id`."""
    r = _pasarela().cobrar(_orden("juan@correo-real.com"))
    assert r.referencia == "int_1"


def test_no_cobra_un_medio_de_otro_proveedor():
    orden = OrdenDeCobro(
        intencion_id="int_1",
        medio=MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22620436"),
        monto=Dinero.de_pesos(1_000),
        glosa="x",
        correo_pagador="juan@correo-real.com",
    )
    with pytest.raises(ErrorDePasarela):
        _pasarela().cobrar(orden)


def test_consultar_cobro_desconocido_levanta():
    with pytest.raises(ErrorDePasarela):
        _pasarela().consultar_cobro("sim_no_existe")


def test_guion_personalizado_gana_a_la_heuristica():
    """El operador de una demo puede forzar cualquier desenlace, sin
    depender del correo, inyectando su propio decisor."""
    siempre_antifraude = GuionSimulado(decisor=lambda orden: DECLINADO_ANTIFRAUDE)
    pasarela = AdaptadorSimulado(GeneradorIdsUuid(), Ambiente.SANDBOX, siempre_antifraude)

    r = pasarela.cobrar(_orden("cualquiera@correo-normal.com"))
    assert r.detenido_por_antifraude


def test_flujo_de_enrolamiento_completo():
    from agora.model.pago.gateways.pasarela import SolicitudEnrolamiento

    pasarela = _pasarela()
    en_proceso = pasarela.preparar_medio(
        SolicitudEnrolamiento("3001234567", "juan@correo-real.com", Ambiente.SANDBOX)
    )
    # El token queda aprobado de inmediato en la simulada (no hay push real
    # que esperar).
    assert pasarela.estado_medio_por_token(en_proceso.token).estado == "APPROVED"
    confirmado = pasarela.confirmar_medio(en_proceso.token, "juan@correo-real.com")
    assert confirmado.disponible
    assert confirmado.ref is not None
    assert confirmado.ref.proveedor is Proveedor.SIMULADA

    revocado = pasarela.revocar_medio(confirmado.ref)
    assert revocado.estado == "VOIDED"


def test_desenlace_es_un_value_object_comparable():
    a = Desenlace(EstadoCobro.APROBADO, "x", "ACCEPT")
    b = Desenlace(EstadoCobro.APROBADO, "x", "ACCEPT")
    assert a == b


# --------------------------------------------------------------------------- #
# resultado_desde_evento / evento_de (etapa 4)
# --------------------------------------------------------------------------- #


def test_evento_de_y_resultado_desde_evento_hacen_el_viaje_completo():
    """`evento_de` empaqueta el cobro como lo haria el webhook de Wompi;
    `resultado_desde_evento` lo desempaqueta. Juntos son lo que le permite a
    una demo ejercitar `ConciliarEventoUseCase` sin un servidor de Wompi real."""
    pasarela = _pasarela()
    r = pasarela.cobrar(_orden("cliente.pendiente@correo-real.com"))
    pasarela.resolver_pendiente(r.id_externo, APROBADO)

    evento = pasarela.evento_de(r.id_externo)
    traduccion = pasarela.resultado_desde_evento(evento)

    assert traduccion is not None
    intencion_id, resultado = traduccion
    assert intencion_id == "int_1"  # la simulada no antepone "agora-"
    assert resultado.estado is EstadoCobro.APROBADO


def test_resultado_desde_evento_ignora_otro_tipo_de_evento():
    pasarela = _pasarela()
    assert pasarela.resultado_desde_evento({"event": "algo.distinto", "data": {}}) is None


def test_resultado_desde_evento_ignora_evento_sin_referencia():
    pasarela = _pasarela()
    evento = {"event": "transaction.updated", "data": {"transaction": {"status": "APPROVED"}}}
    assert pasarela.resultado_desde_evento(evento) is None


def test_evento_de_cobro_desconocido_levanta():
    with pytest.raises(ErrorDePasarela):
        _pasarela().evento_de("sim_no_existe")
