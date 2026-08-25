"""`LibroDeConsumoSQLite`: la misma reserva atomica que `LibroDeConsumoEnMemoria`
(`tests/test_libro_consumo_memoria.py`), pero verificada donde importa de
verdad -- entre conexiones SQLite independientes, no entre hilos que
comparten un objeto Python.

Cada llamada de `LibroDeConsumoSQLite` abre su propia conexion
(`conexion.py`). Eso significa que la prueba de concurrencia de este archivo
no esta probando un `threading.Lock` de Python: esta probando que
`BEGIN IMMEDIATE` + WAL + `busy_timeout` de SQLite de verdad serializan el
acceso al archivo, que es la propiedad que la version en memoria no puede
ofrecer (no sobrevive un reinicio del proceso) y que la etapa 3 existe para
conseguir.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest

from agora.adaptadores.persistencia.sqlite.libro_consumo import LibroDeConsumoSQLite
from agora.adaptadores.sistema.ids import GeneradorIdsUuid
from agora.dominio.comun.dinero import Dinero
from agora.dominio.mandato.modelo import Mandato
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor
from agora.puertos.repositorios import TopeAgotado


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


def _libro(tmp_path, reloj=None) -> LibroDeConsumoSQLite:
    return LibroDeConsumoSQLite(tmp_path / "agora.db", reloj or _RelojFijo(HOY), GeneradorIdsUuid())


def test_reservar_y_confirmar_suma_al_consumo(tmp_path):
    libro = _libro(tmp_path)
    m = _mandato()
    reserva = libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    libro.confirmar(reserva)

    consumo = libro.consumo_de(m.mandato_id)
    assert consumo.usos == 1
    assert consumo.acumulado == Dinero.de_pesos(2_050)


def test_confirmar_dos_veces_no_duplica_el_consumo(tmp_path):
    """Reintento tras un timeout, por ejemplo: `confirmar` debe ser un no-op
    la segunda vez, no sumar de nuevo."""
    libro = _libro(tmp_path)
    m = _mandato()
    reserva = libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    libro.confirmar(reserva)
    libro.confirmar(reserva)  # no-op: la reserva ya no esta "pendiente"

    consumo = libro.consumo_de(m.mandato_id)
    assert consumo.usos == 1
    assert consumo.acumulado == Dinero.de_pesos(2_050)


def test_liberar_no_deja_rastro_en_el_consumo(tmp_path):
    libro = _libro(tmp_path)
    m = _mandato()
    reserva = libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    libro.liberar(reserva)

    consumo = libro.consumo_de(m.mandato_id)
    assert consumo.usos == 0
    assert consumo.acumulado == Dinero.de_pesos(0)
    assert libro.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(0)


def test_liberar_dos_veces_no_devuelve_cupo_dos_veces(tmp_path):
    libro = _libro(tmp_path)
    m = _mandato()
    reserva = libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    libro.liberar(reserva)
    libro.liberar(reserva)  # no-op

    assert libro.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(0)


def test_reservar_ya_descuenta_del_cupo_antes_de_confirmar(tmp_path):
    libro = _libro(tmp_path)
    m = _mandato()
    libro.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    assert libro.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(2_050)


def test_tope_diario_agotado_no_deja_reservar(tmp_path):
    libro = _libro(tmp_path)
    m = _mandato()
    libro.reservar(m, "int_1", Dinero.de_pesos(95_000), Dinero.de_pesos(100_000))

    with pytest.raises(TopeAgotado) as exc:
        libro.reservar(m, "int_2", Dinero.de_pesos(10_000), Dinero.de_pesos(100_000))
    assert exc.value.disponible == Dinero.de_pesos(5_000)
    assert exc.value.pedido == Dinero.de_pesos(10_000)


def test_ambientes_no_comparten_cupo(tmp_path):
    libro = _libro(tmp_path)
    sandbox = _mandato(Ambiente.SANDBOX, "mnd_sb")
    produccion = _mandato(Ambiente.PRODUCCION, "mnd_pr")

    libro.reservar(sandbox, "int_1", Dinero.de_pesos(90_000), Dinero.de_pesos(100_000))
    # Si compartieran cupo, esto fallaria con TopeAgotado.
    libro.reservar(produccion, "int_2", Dinero.de_pesos(90_000), Dinero.de_pesos(100_000))

    assert libro.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(90_000)
    assert libro.gastado_hoy(Ambiente.PRODUCCION) == Dinero.de_pesos(90_000)


def test_el_consumo_sobrevive_una_reconexion(tmp_path):
    """Lo que la version en memoria no puede ofrecer: dos instancias del
    adaptador apuntando al mismo archivo ven el mismo estado, como si el
    proceso hubiera reiniciado entre medio."""
    ruta = tmp_path / "agora.db"
    m = _mandato()

    libro_1 = LibroDeConsumoSQLite(ruta, _RelojFijo(HOY), GeneradorIdsUuid())
    reserva = libro_1.reservar(m, "int_1", Dinero.de_pesos(2_050), Dinero.de_pesos(100_000))
    libro_1.confirmar(reserva)
    del libro_1  # nada de estado en memoria que "recordar": todo esta en el archivo

    libro_2 = LibroDeConsumoSQLite(ruta, _RelojFijo(HOY), GeneradorIdsUuid())
    consumo = libro_2.consumo_de(m.mandato_id)
    assert consumo.usos == 1
    assert consumo.acumulado == Dinero.de_pesos(2_050)
    assert libro_2.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(2_050)


def test_reserva_atomica_entre_conexiones_sqlite_independientes(tmp_path):
    """El caso que le importa a la etapa 3: dos cobros compiten por el ultimo
    tramo del tope diario, cada uno desde su PROPIA conexion SQLite (no un
    lock de Python compartido). Con leer->sumar->escribir sobre un JSON
    completo (`docs/analisis-codigo.md` hallazgo 2), los dos podrian pasar.
    Aqui, `BEGIN IMMEDIATE` toma el lock de escritura del archivo antes de
    leer: solo puede pasar uno."""
    ruta = tmp_path / "agora.db"
    m = _mandato()
    tope = Dinero.de_pesos(100_000)

    libro_setup = LibroDeConsumoSQLite(ruta, _RelojFijo(HOY), GeneradorIdsUuid())
    # Deja exactamente un tramo de 15.000 libre.
    libro_setup.reservar(m, "int_0", Dinero.de_pesos(85_000), tope)

    intentos = 10
    resultados: list[bool] = []
    lock_resultados = threading.Lock()

    def intentar(i: int) -> None:
        # Cada hilo arma su PROPIO adaptador (y por lo tanto abre sus propias
        # conexiones SQLite) -- es lo mas cerca que una prueba de un solo
        # proceso puede llegar a simular dos procesos distintos compitiendo
        # por el mismo archivo.
        libro = LibroDeConsumoSQLite(ruta, _RelojFijo(HOY), GeneradorIdsUuid())
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
    libro_verificacion = LibroDeConsumoSQLite(ruta, _RelojFijo(HOY), GeneradorIdsUuid())
    assert libro_verificacion.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(100_000)


def test_dia_de_la_reserva_es_el_del_reloj_inyectado(tmp_path):
    libro = _libro(tmp_path)
    m = _mandato()
    reserva = libro.reservar(m, "int_1", Dinero.de_pesos(1_000), Dinero.de_pesos(100_000))
    assert reserva.dia == date(2026, 8, 25)
