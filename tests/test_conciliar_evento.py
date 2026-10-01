"""`ConciliarEventoUseCase`: el webhook -> estado.

Usa `AdaptadorSimulado` de verdad (no un doble a mano) para `validar_evento`/
`resultado_desde_evento`: un doble reimplementaria justo la traduccion que
estas pruebas quieren verificar que encaja con `LibroDeConsumo`. La unica
excepcion es la prueba de un evento invalido -- la simulada no valida nada
(ver su docstring), asi que ese caso usa un doble minimo que solo existe para
levantar donde `AdaptadorWompi.validar_evento` levantaria de verdad.

MULTI-COMERCIO: `ConciliarEventoUseCase` recibe un `SelectorDePasarela`, no una
pasarela fija, y `__call__` exige un `comercio_id` (el que trae la URL del
webhook -- ver el docstring del caso de uso). Estas pruebas envuelven su
pasarela falsa en `RegistroDePasarelas({}, por_defecto=pasarela)`, que
resuelve para cualquier `comercio_id` -- lo que se prueba aca es la
traduccion evento->estado, no el ruteo por comercio."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from agora.adaptadores.pasarelas.registro import RegistroDePasarelas
from agora.adaptadores.pasarelas.simulada import APROBADO, DECLINADO, AdaptadorSimulado
from agora.adaptadores.persistencia.memoria import LibroDeConsumoEnMemoria, RegistroDeEstadosEnMemoria
from agora.adaptadores.sistema.ids import GeneradorIdsUuid
from agora.usecase.conciliar_evento.conciliar_evento_use_case import ConciliarEventoUseCase
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import ErrorDePasarela
from agora.model.mandato.modelo import Mandato
from agora.model.pago.modelo import Ambiente, MedioDePagoRef, OrdenDeCobro, Proveedor

HOY = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
COMERCIO_ID = "com_x"


@dataclass
class _RelojFijo:
    cuando: datetime

    def ahora(self) -> datetime:
        return self.cuando


class _BitacoraEnLista:
    def __init__(self) -> None:
        self.eventos: list[tuple[str, object]] = []

    def anotar(self, evento: str, cuerpo: object) -> None:
        self.eventos.append((evento, cuerpo))


class _PasarelaQueRechazaTodo:
    """Solo para probar el camino de `validar_evento` invalido -- la
    simulada, a proposito, nunca invalida nada."""

    nombre = "rechaza-todo"

    def validar_evento(self, cuerpo: bytes, cabeceras: dict[str, str]) -> dict:
        raise ErrorDePasarela("checksum no coincide")

    def resultado_desde_evento(self, evento: dict):
        raise AssertionError("no deberia llamarse: validar_evento ya levanto")


def _mandato(mandato_id: str = "mnd_1") -> Mandato:
    return Mandato(
        mandato_id=mandato_id,
        titular_id="tit_1",
        medio=MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_1"),
        comercio_id=COMERCIO_ID,
        monto_max=Dinero.de_pesos(20_000),
        tope_total=Dinero.de_pesos(20_000),
        usos_max=5,
        expira_en=HOY,
        creado_en=HOY,
        llave_publica=b"",
    )


def _armar(estados=None):
    reloj = _RelojFijo(HOY)
    ids = GeneradorIdsUuid()
    consumo = LibroDeConsumoEnMemoria(reloj, ids)
    pasarela = AdaptadorSimulado(ids, Ambiente.SANDBOX)
    bitacora = _BitacoraEnLista()
    conciliar = ConciliarEventoUseCase(
        consumo, RegistroDePasarelas({}, por_defecto=pasarela), bitacora, estados=estados,
    )
    return conciliar, consumo, pasarela, bitacora


def _orden(intencion_id: str, correo: str) -> OrdenDeCobro:
    return OrdenDeCobro(
        intencion_id=intencion_id,
        medio=MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_1"),
        monto=Dinero.de_pesos(2_000),
        glosa="compra de prueba",
        correo_pagador=correo,
    )


def _reservar_y_cobrar_pendiente(consumo, pasarela, mandato, intencion_id):
    """Reproduce lo que deja `EjecutarIntencionUseCase._cobrar` cuando la pasarela
    devuelve PENDIENTE: la reserva viva, y un cobro pendiente del lado de la
    pasarela con la misma referencia."""
    consumo.reservar(mandato, intencion_id, Dinero.de_pesos(2_000), Dinero.de_pesos(100_000))
    return pasarela.cobrar(_orden(intencion_id, "cliente.pendiente@correo-real.com"))


def test_evento_aprobado_confirma_la_reserva():
    conciliar, consumo, pasarela, bitacora = _armar()
    mandato = _mandato()
    pendiente = _reservar_y_cobrar_pendiente(consumo, pasarela, mandato, "int_1")
    pasarela.resolver_pendiente(pendiente.id_externo, APROBADO)
    cuerpo = json.dumps(pasarela.evento_de(pendiente.id_externo)).encode("utf-8")

    resultado = conciliar(cuerpo, {}, COMERCIO_ID)

    assert resultado.procesado
    assert resultado.intencion_id == "int_1"
    assert consumo.consumo_de(mandato.mandato_id).usos == 1
    assert consumo.reserva_pendiente_de("int_1") is None
    assert bitacora.eventos[-1][0] == "conciliado"


def test_evento_declinado_libera_la_reserva():
    conciliar, consumo, pasarela, _ = _armar()
    mandato = _mandato()
    pendiente = _reservar_y_cobrar_pendiente(consumo, pasarela, mandato, "int_1")
    pasarela.resolver_pendiente(pendiente.id_externo, DECLINADO)
    cuerpo = json.dumps(pasarela.evento_de(pendiente.id_externo)).encode("utf-8")

    resultado = conciliar(cuerpo, {}, COMERCIO_ID)

    assert resultado.procesado
    assert consumo.consumo_de(mandato.mandato_id).usos == 0
    assert consumo.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(0)
    assert consumo.reserva_pendiente_de("int_1") is None


def test_evento_aprobado_actualiza_el_registro_de_estados_si_se_provee():
    estados = RegistroDeEstadosEnMemoria()
    conciliar, consumo, pasarela, _ = _armar(estados=estados)
    mandato = _mandato()
    pendiente = _reservar_y_cobrar_pendiente(consumo, pasarela, mandato, "int_1")
    pasarela.resolver_pendiente(pendiente.id_externo, APROBADO)
    cuerpo = json.dumps(pasarela.evento_de(pendiente.id_externo)).encode("utf-8")

    conciliar(cuerpo, {}, COMERCIO_ID)

    assert estados.obtener("int_1")[0] == "aprobado"


def test_evento_que_sigue_pendiente_no_hace_nada():
    conciliar, consumo, pasarela, _ = _armar()
    mandato = _mandato()
    pendiente = _reservar_y_cobrar_pendiente(consumo, pasarela, mandato, "int_1")
    cuerpo = json.dumps(pasarela.evento_de(pendiente.id_externo)).encode("utf-8")

    resultado = conciliar(cuerpo, {}, COMERCIO_ID)

    assert not resultado.procesado
    assert resultado.motivo == "sigue_pendiente"
    # La reserva sigue viva: nada se confirmo ni se libero todavia.
    assert consumo.reserva_pendiente_de("int_1") is not None


def test_evento_sin_reserva_pendiente_no_es_error():
    """Reintento tras un timeout, doble entrega, o un evento para una
    intencion que ya se concilio antes: no hay nada que hacer, y no es un
    error que deba tumbar el webhook."""
    conciliar, _, pasarela, bitacora = _armar()
    evento = {
        "event": "transaction.updated",
        "data": {"transaction": {"id": "tx_x", "reference": "int_fantasma", "status": "APPROVED"}},
    }
    cuerpo = json.dumps(evento).encode("utf-8")

    resultado = conciliar(cuerpo, {}, COMERCIO_ID)

    assert not resultado.procesado
    assert resultado.motivo == "sin_reserva_pendiente"
    assert bitacora.eventos[-1][0] == "evento_ignorado"


def test_evento_no_reconocido_no_es_error():
    conciliar, _, _, _ = _armar()
    cuerpo = json.dumps({"event": "algo.distinto", "data": {}}).encode("utf-8")

    resultado = conciliar(cuerpo, {}, COMERCIO_ID)

    assert not resultado.procesado
    assert resultado.motivo == "evento_no_reconocido"


def test_evento_invalido_no_es_error_y_no_propaga_la_excepcion():
    consumo = LibroDeConsumoEnMemoria(_RelojFijo(HOY), GeneradorIdsUuid())
    bitacora = _BitacoraEnLista()
    conciliar = ConciliarEventoUseCase(
        consumo, RegistroDePasarelas({}, por_defecto=_PasarelaQueRechazaTodo()), bitacora,
    )

    resultado = conciliar(b"cualquier cosa", {}, COMERCIO_ID)

    assert not resultado.procesado
    assert resultado.motivo == "evento_invalido"
    assert bitacora.eventos[-1][0] == "evento_ignorado"
