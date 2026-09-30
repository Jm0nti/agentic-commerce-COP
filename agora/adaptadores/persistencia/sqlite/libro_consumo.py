"""`LibroDeConsumo` contra SQLite: la reserva atomica de verdad.

`LibroDeConsumoEnMemoria` (etapa 2) ya resolvia la condicion de carrera
dentro de UN proceso, con un `threading.Lock`. Ese lock no protege nada entre
DOS procesos, y no sobrevive un reinicio -- el consumo acumulado se pierde y
un mandato que se creia agotado vuelve a estar fresco. Contra dinero real,
eso no es aceptable (ver el docstring de la version en memoria).

Aqui la seccion critica de `reservar` -- leer `gastado_dia`, decidir si cabe,
escribirlo, insertar la reserva -- es una sola transaccion SQLite abierta con
`BEGIN IMMEDIATE`: toma el lock de escritura del archivo ANTES de leer, asi
que dos procesos que compiten por el ultimo tramo del tope diario no pueden
los dos leer el mismo `gastado_dia` y escribir cada uno el suyo. Uno espera
(hasta `busy_timeout`), el otro escribe y libera; el que esperaba lee el
valor ya actualizado.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ....model.commons.dinero import CERO, Dinero
from ....model.mandato.modelo import Consumo, Mandato
from ....model.pago.modelo import Ambiente
from ....model.mandato.gateways.repositorios import Reserva, TopeAgotado
from ....model.commons.gateways.sistema import GeneradorIds, Reloj
from .conexion import abrir_conexion


class LibroDeConsumoSQLite:
    """Implementa `puertos.repositorios.LibroDeConsumo`."""

    def __init__(self, ruta: Path, reloj: Reloj, ids: GeneradorIds) -> None:
        self._ruta = ruta
        self._reloj = reloj
        self._ids = ids

    # -- reserva -------------------------------------------------------------- #

    def reservar(
        self, mandato: Mandato, intencion_id: str, monto: Dinero, tope_dia: Dinero
    ) -> Reserva:
        ambiente = mandato.medio.ambiente.value
        hoy = self._reloj.ahora().date()
        dia = hoy.isoformat()
        reserva_id = self._ids.nuevo("rsv")

        con = abrir_conexion(self._ruta)
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                fila = con.execute(
                    "SELECT gastado_centavos, moneda FROM gastado_dia "
                    "WHERE ambiente = ? AND dia = ?",
                    (ambiente, dia),
                ).fetchone()
                gastado = Dinero.de_centavos(*fila) if fila else Dinero.de_centavos(0, monto.moneda)

                if (gastado + monto).excede(tope_dia):
                    raise TopeAgotado("tope_duro_diario", tope_dia - gastado, monto)

                nuevo_gastado = gastado + monto
                con.execute(
                    "INSERT INTO gastado_dia (ambiente, dia, gastado_centavos, moneda) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(ambiente, dia) DO UPDATE SET "
                    "gastado_centavos = excluded.gastado_centavos",
                    (ambiente, dia, nuevo_gastado.centavos, nuevo_gastado.moneda),
                )
                con.execute(
                    "INSERT INTO reserva (reserva_id, intencion_id, mandato_id, ambiente, "
                    "monto_centavos, monto_moneda, dia, estado, creada_en) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'pendiente', ?)",
                    (
                        reserva_id, intencion_id, mandato.mandato_id, ambiente,
                        monto.centavos, monto.moneda, dia,
                        self._reloj.ahora().isoformat(),
                    ),
                )
            except Exception:
                con.execute("ROLLBACK")
                raise
            else:
                con.execute("COMMIT")
        finally:
            con.close()

        return Reserva(
            reserva_id=reserva_id, intencion_id=intencion_id,
            mandato_id=mandato.mandato_id, monto=monto, dia=hoy,
        )

    def confirmar(self, reserva: Reserva) -> None:
        con = abrir_conexion(self._ruta)
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                fila = con.execute(
                    "SELECT estado FROM reserva WHERE reserva_id = ?", (reserva.reserva_id,)
                ).fetchone()
                if fila is None or fila[0] != "pendiente":
                    # Confirmar dos veces (reintento tras un timeout, por
                    # ejemplo) no debe duplicar el consumo: ya se confirmo, ya
                    # se libero, o nunca existio. No-op silencioso, igual que
                    # el adaptador en memoria -- pero la transaccion, aunque
                    # no escribio nada, se cierra explicitamente en vez de
                    # dejarla abierta para que `close()` la resuelva sola.
                    con.execute("ROLLBACK")
                    return
                con.execute(
                    "UPDATE reserva SET estado = 'confirmada' WHERE reserva_id = ?",
                    (reserva.reserva_id,),
                )
                con.execute(
                    "INSERT INTO consumo (mandato_id, usos, acumulado_centavos, acumulado_moneda) "
                    "VALUES (?, 1, ?, ?) "
                    "ON CONFLICT(mandato_id) DO UPDATE SET "
                    "usos = usos + 1, "
                    "acumulado_centavos = acumulado_centavos + excluded.acumulado_centavos",
                    (reserva.mandato_id, reserva.monto.centavos, reserva.monto.moneda),
                )
            except Exception:
                con.execute("ROLLBACK")
                raise
            else:
                con.execute("COMMIT")
        finally:
            con.close()

    def liberar(self, reserva: Reserva) -> None:
        con = abrir_conexion(self._ruta)
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                fila = con.execute(
                    "SELECT estado, ambiente FROM reserva WHERE reserva_id = ?",
                    (reserva.reserva_id,),
                ).fetchone()
                if fila is None or fila[0] != "pendiente":
                    con.execute("ROLLBACK")
                    return
                _estado, ambiente = fila
                con.execute(
                    "UPDATE reserva SET estado = 'liberada' WHERE reserva_id = ?",
                    (reserva.reserva_id,),
                )
                con.execute(
                    "UPDATE gastado_dia SET gastado_centavos = gastado_centavos - ? "
                    "WHERE ambiente = ? AND dia = ?",
                    (reserva.monto.centavos, ambiente, reserva.dia.isoformat()),
                )
            except Exception:
                con.execute("ROLLBACK")
                raise
            else:
                con.execute("COMMIT")
        finally:
            con.close()

    def reserva_pendiente_de(self, intencion_id: str) -> Reserva | None:
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                "SELECT reserva_id, mandato_id, monto_centavos, monto_moneda, dia "
                "FROM reserva WHERE intencion_id = ? AND estado = 'pendiente'",
                (intencion_id,),
            ).fetchone()
        finally:
            con.close()
        if fila is None:
            return None
        reserva_id, mandato_id, monto_centavos, monto_moneda, dia = fila
        return Reserva(
            reserva_id=reserva_id,
            intencion_id=intencion_id,
            mandato_id=mandato_id,
            monto=Dinero.de_centavos(monto_centavos, monto_moneda),
            dia=date.fromisoformat(dia),
        )

    # -- consultas -------------------------------------------------------------- #

    def consumo_de(self, mandato_id: str) -> Consumo:
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                "SELECT usos, acumulado_centavos, acumulado_moneda FROM consumo "
                "WHERE mandato_id = ?",
                (mandato_id,),
            ).fetchone()
        finally:
            con.close()
        if fila is None:
            return Consumo()
        usos, acumulado_centavos, moneda = fila
        return Consumo(usos=usos, acumulado=Dinero.de_centavos(acumulado_centavos, moneda))

    def gastado_hoy(self, ambiente: Ambiente) -> Dinero:
        hoy = self._reloj.ahora().date().isoformat()
        con = abrir_conexion(self._ruta)
        try:
            fila = con.execute(
                "SELECT gastado_centavos, moneda FROM gastado_dia WHERE ambiente = ? AND dia = ?",
                (ambiente.value, hoy),
            ).fetchone()
        finally:
            con.close()
        return Dinero.de_centavos(*fila) if fila else CERO
