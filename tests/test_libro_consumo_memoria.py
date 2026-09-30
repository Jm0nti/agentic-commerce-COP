"""`LibroDeConsumoEnMemoria`: reserva atomica, y la condicion de carrera que
existe para evitar.

`docs/historico/analisis-codigo.md`, hallazgo 2: `Boveda` hace leer -> sumar -> escribir
sobre TODO el JSON (`nucleo.py:288-292`). Bajo dos cobros simultaneos, los dos
leen el mismo `gastado_dia` y el ultimo en escribir gana -- el tope diario
deja de ser un tope. La prueba de concurrencia de este archivo es la que
demuestra que el reemplazo no tiene el mismo defecto.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from agora.adaptadores.persistencia.memoria.libro_consumo import LibroDeConsumoEnMemoria
from agora.adaptadores.sistema.ids import GeneradorIdsUuid
from agora.model.commons.dinero import Dinero
from agora.model.mandato.modelo import Mandato
from agora.model.pago.modelo import Ambiente, MedioDePagoRef, Proveedor
from agora.model.mandato.gateways.repositorios import TopeAgotado


@dataclass
class _RelojFijo:
    cuando: datetime

    def ahora(self) -> datetime:
        return self.cuando


HOY = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def _mandato(ambiente: Ambiente = Ambiente.SANDBOX, mandato_id: str = "mnd_1") -> Mandato:
    return Mandato(
        mandato_id=mandato_id,
        titular_id="tit_1",
        medio=MedioDePagoRef(Proveedor.SIMULADA, ambiente, "1"),
        comercio_id="com_x",
        monto_max=Dinero.de_pesos(20_000),
        tope_total=Dinero.de_pesos(100_000),
        usos_max=10,
        expira_en=HOY,
        creado_en=HOY,
        llave_publica=b"",
    )


def _libro(reloj=None) -> LibroDeConsumoEnMemoria:
    return LibroDeConsumoEnMemoria(reloj or _RelojFijo(HOY), GeneradorIdsUuid())


def test_reservar_y_confirmar_suma_al_consumo():
    libro = _libro()
    m = _mandato()
    reserva = libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    libro.confirmar(reserva)

    consumo = libro.consumo_de(m.mandato_id)
    assert consumo.usos == 1
    assert consumo.acumulado == Dinero.de_pesos(2_050)


def test_liberar_no_deja_rastro_en_el_consumo():
    libro = _libro()
    m = _mandato()
    reserva = libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    libro.liberar(reserva)

    consumo = libro.consumo_de(m.mandato_id)
    assert consumo.usos == 0
    assert consumo.acumulado == Dinero.de_pesos(0)
    assert libro.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(0)


def test_reserva_pendiente_de_encuentra_una_reserva_viva():
    libro = _libro()
    m = _mandato()
    reserva = libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))

    assert libro.reserva_pendiente_de("int_1") == reserva


def test_reserva_pendiente_de_es_none_tras_confirmar():
    libro = _libro()
    m = _mandato()
    reserva = libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    libro.confirmar(reserva)

    assert libro.reserva_pendiente_de("int_1") is None


def test_reserva_pendiente_de_es_none_tras_liberar():
    libro = _libro()
    m = _mandato()
    reserva = libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    libro.liberar(reserva)

    assert libro.reserva_pendiente_de("int_1") is None


def test_reserva_pendiente_de_intencion_desconocida_es_none():
    libro = _libro()
    assert libro.reserva_pendiente_de("int_fantasma") is None


def test_reservar_ya_descuenta_del_cupo_antes_de_confirmar():
    """El punto de reservar: el cupo se aparta ANTES de saber si el cobro se
    aprueba. Si solo se descontara al confirmar, dos cobros PENDIENTE podrian
    los dos verse con cupo libre."""
    libro = _libro()
    m = _mandato()
    libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    assert libro.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(2_050)


def test_tope_diario_agotado_no_deja_reservar():
    libro = _libro()
    m = _mandato()
    libro.reservar(m, "int_1", Dinero.de_pesos(95_000), Dinero.de_pesos(100_000))

    with pytest.raises(TopeAgotado) as exc:
        libro.reservar(m, "int_2", Dinero.de_pesos(10_000), Dinero.de_pesos(100_000))
    assert exc.value.disponible == Dinero.de_pesos(5_000)
    assert exc.value.pedido == Dinero.de_pesos(10_000)


def test_ambientes_no_comparten_cupo():
    libro = _libro()
    sandbox = _mandato(Ambiente.SANDBOX, "mnd_sb")
    produccion = _mandato(Ambiente.PRODUCCION, "mnd_pr")

    libro.reservar(sandbox, "int_1", Dinero.de_pesos(90_000), Dinero.de_pesos(100_000))
    # Si compartieran cupo, esto fallaria con TopeAgotado.
    libro.reservar(produccion, "int_2", Dinero.de_pesos(90_000), Dinero.de_pesos(100_000))

    assert libro.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(90_000)
    assert libro.gastado_hoy(Ambiente.PRODUCCION) == Dinero.de_pesos(90_000)


def test_reserva_atomica_bajo_concurrencia():
    """El caso que `docs/historico/analisis-codigo.md` marca como el mas caro: dos
    cobros compiten por el ultimo tramo del tope diario. Con
    leer->sumar->escribir sobre un JSON completo, los dos podrian pasar. Aqui
    solo puede pasar uno."""
    libro = _libro()
    m = _mandato()
    tope = Dinero.de_pesos(100_000)
    # Deja exactamente un tramo de 15.000 libre.
    libro.reservar(m, "int_0", Dinero.de_pesos(85_000), tope)

    intentos = 10
    resultados: list[bool] = []
    lock_resultados = threading.Lock()

    def intentar(i: int) -> None:
        try:
            libro.reservar(m, f"int_{i}", Dinero.de_pesos(15_000), tope)
            ok = True
        except TopeAgotado:
            ok = False
        with lock_resultados:
            resultados.append(ok)

    hilos = [threading.Thread(target=intentar, args=(i,)) for i in range(1, intentos + 1)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    # Solo un hilo debio ganar el ultimo tramo de 15.000: si dos ganan, el
    # tope diario de 100.000 dejo de ser un tope.
    assert sum(resultados) == 1
    assert libro.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(100_000)
