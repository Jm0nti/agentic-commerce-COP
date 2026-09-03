"""`entradas/webhooks/wompi.py`: HTTP -> `ConciliarEvento` -> HTTP.

Dos grupos de pruebas. El primero usa un `ConciliarEvento` de mentiras (una
funcion que devuelve un `ResultadoConciliacion` fijo) para verificar solo el
cableado HTTP: que status 200 sale siempre, que el cuerpo, las cabeceras y
el `comercio_id` de la URL le llegan intactos a `conciliar_evento`, que la
respuesta refleja lo que devolvio. El segundo usa las piezas de verdad
(`AdaptadorSimulado` + `LibroDeConsumoEnMemoria` + `ConciliarEvento` real)
para confirmar que `crear_app` las conecta correctamente de punta a punta --
no solo que la ruta responde 200 en abstracto.

MULTI-COMERCIO: la ruta lleva `comercio_id` en el path
(`/pagos/wompi/transacciones/{comercio_id}`) -- ver el docstring del modulo
bajo prueba.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from agora.adaptadores.pasarelas.registro import RegistroDePasarelas
from agora.adaptadores.pasarelas.simulada import APROBADO, AdaptadorSimulado
from agora.adaptadores.persistencia.memoria import LibroDeConsumoEnMemoria
from agora.adaptadores.sistema.ids import GeneradorIdsUuid
from agora.aplicacion.conciliar_evento import ConciliarEvento, ResultadoConciliacion
from agora.dominio.comun.dinero import Dinero
from agora.dominio.mandato.modelo import Mandato
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, OrdenDeCobro, Proveedor
from agora.entradas.webhooks.wompi import crear_app

HOY = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
COMERCIO_ID = "com_x"


@dataclass
class _RelojFijo:
    cuando: datetime

    def ahora(self) -> datetime:
        return self.cuando


class _ConciliarEventoFijo:
    """No es un doble de `ConciliarEvento` reimplementando la traduccion --
    solo devuelve lo que se le configuro y anota con que lo llamaron, para
    que las pruebas de cableado puedan revisarlo."""

    def __init__(self, resultado: ResultadoConciliacion) -> None:
        self._resultado = resultado
        self.llamadas: list[tuple[bytes, dict[str, str], str]] = []

    def __call__(self, cuerpo: bytes, cabeceras: dict[str, str], comercio_id: str) -> ResultadoConciliacion:
        self.llamadas.append((cuerpo, cabeceras, comercio_id))
        return self._resultado


def test_salud_responde_ok():
    app = crear_app(_ConciliarEventoFijo(ResultadoConciliacion(procesado=True, motivo="x")))
    cliente = TestClient(app)

    respuesta = cliente.get("/salud")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}


def test_evento_procesado_responde_200_y_refleja_el_resultado():
    conciliar = _ConciliarEventoFijo(
        ResultadoConciliacion(procesado=True, motivo="APPROVED", intencion_id="int_1")
    )
    app = crear_app(conciliar)
    cliente = TestClient(app)

    respuesta = cliente.post(
        f"/pagos/wompi/transacciones/{COMERCIO_ID}",
        content=b'{"event": "transaction.updated"}',
        headers={"X-Event-Checksum": "abc123"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"procesado": True, "motivo": "APPROVED"}
    # El cuerpo crudo, las cabeceras y el comercio_id de la URL le llegan a
    # `conciliar_evento` intactos.
    assert len(conciliar.llamadas) == 1
    cuerpo, cabeceras, comercio_id = conciliar.llamadas[0]
    assert cuerpo == b'{"event": "transaction.updated"}'
    assert cabeceras.get("x-event-checksum") == "abc123"
    assert comercio_id == COMERCIO_ID


def test_evento_no_procesado_tambien_responde_200():
    """El corazon del modulo: nada que `ConciliarEvento` considere 'no hay
    nada que hacer' se convierte en un status distinto de 200. Reintentar no
    arregla un checksum invalido ni una reserva que ya no existe."""
    conciliar = _ConciliarEventoFijo(
        ResultadoConciliacion(procesado=False, motivo="evento_invalido")
    )
    app = crear_app(conciliar)
    cliente = TestClient(app)

    respuesta = cliente.post(f"/pagos/wompi/transacciones/{COMERCIO_ID}", content=b"esto no es JSON")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"procesado": False, "motivo": "evento_invalido"}


# -- de punta a punta, con las piezas de verdad ------------------------------ #


def _mandato() -> Mandato:
    return Mandato(
        mandato_id="mnd_1",
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


def test_de_punta_a_punta_con_adaptador_simulado_real():
    reloj = _RelojFijo(HOY)
    ids = GeneradorIdsUuid()
    consumo = LibroDeConsumoEnMemoria(reloj, ids)
    pasarela = AdaptadorSimulado(ids, Ambiente.SANDBOX)
    mandato = _mandato()

    consumo.reservar(mandato, "int_1", Dinero.de_pesos(2_000), Dinero.de_pesos(100_000))
    pendiente = pasarela.cobrar(
        OrdenDeCobro(
            intencion_id="int_1",
            medio=mandato.medio,
            monto=Dinero.de_pesos(2_000),
            glosa="compra de prueba",
            correo_pagador="cliente@correo-real.com",
        )
    )
    pasarela.resolver_pendiente(pendiente.id_externo, APROBADO)

    class _BitacoraQueIgnora:
        def anotar(self, evento, cuerpo) -> None:
            pass

    conciliar = ConciliarEvento(consumo, RegistroDePasarelas({}, por_defecto=pasarela), _BitacoraQueIgnora())
    app = crear_app(conciliar)
    cliente = TestClient(app)

    cuerpo = json.dumps(pasarela.evento_de(pendiente.id_externo)).encode("utf-8")
    respuesta = cliente.post(f"/pagos/wompi/transacciones/{COMERCIO_ID}", content=cuerpo)

    assert respuesta.status_code == 200
    assert respuesta.json()["procesado"] is True
    # La reserva ya no esta pendiente: `crear_app` de verdad llamo a la
    # `ConciliarEvento` real, que de verdad confirmo contra `consumo`.
    assert consumo.reserva_pendiente_de("int_1") is None
    assert consumo.consumo_de(mandato.mandato_id).usos == 1
