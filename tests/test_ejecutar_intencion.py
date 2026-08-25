"""`EjecutarIntencion` de punta a punta, con adaptadores de verdad.

Es lo que hoy es `Boveda.ejecutar` (`boveda/nucleo.py:337-408`), partido en
caso de uso (`aplicacion/ejecutar_intencion.py`, sin cambios en esta etapa) y
adaptadores (`adaptadores/pasarelas/simulada/`,
`adaptadores/persistencia/memoria/`, `adaptadores/sistema/`, todos nuevos).
Esta prueba es la que demuestra que las piezas encajan igual que encajaban
dentro de `Boveda` -- mismo orden de controles, mismo resultado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agora.adaptadores.pasarelas.simulada import AdaptadorSimulado
from agora.adaptadores.persistencia.memoria import (
    LibroDeConsumoEnMemoria,
    RepositorioMandatosEnMemoria,
)
from agora.adaptadores.sistema import GeneradorIdsUuid, VerificadorEd25519
from agora.aplicacion.ejecutar_intencion import EjecutarIntencion
from agora.dominio.comun.dinero import Dinero
from agora.dominio.mandato.modelo import Intencion, Mandato
from agora.dominio.mandato.politica import Decision
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor
from agora.dominio.pago.topes import TopesDuros

AHORA = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)


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


def _mandato(sk: Ed25519PrivateKey, **kw) -> Mandato:
    pub = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    base = dict(
        mandato_id="mnd_prueba01",
        titular_id="tit_1",
        medio=MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_1"),
        comercio_id="com_x",
        monto_max=Dinero.de_pesos(8_000),
        tope_total=Dinero.de_pesos(8_000),
        usos_max=1,
        expira_en=AHORA + timedelta(hours=1),
        creado_en=AHORA,
        llave_publica=pub,
    )
    base.update(kw)
    m = Mandato(**base)
    return Mandato(**{**base, "firma": sk.sign(m.canonico())})


def _intencion(monto_pesos: int, comercio="com_x", **kw) -> Intencion:
    return Intencion(
        intencion_id=kw.pop("intencion_id", "int_1"),
        mandato_id=kw.pop("mandato_id", "mnd_prueba01"),
        comercio_id=comercio,
        carrito_id="car_1",
        monto=Dinero.de_pesos(monto_pesos),
        **kw,
    )


def _armar(correo: str = "juan@correo-real.com"):
    """Wiring manual, sin pasar por `composicion/`: esta prueba quiere
    controlar cada pieza (el reloj fijo, el mandato exacto) para que los
    escenarios sean deterministas."""
    reloj = _RelojFijo(AHORA)
    ids = GeneradorIdsUuid()
    mandatos = RepositorioMandatosEnMemoria()
    consumo = LibroDeConsumoEnMemoria(reloj, ids)
    pasarela = AdaptadorSimulado(ids, Ambiente.SANDBOX)
    bitacora = _BitacoraEnLista()

    ejecutar = EjecutarIntencion(
        mandatos=mandatos,
        consumo=consumo,
        pasarela=pasarela,
        topes=TopesDuros(),
        reloj=reloj,
        bitacora=bitacora,
        verificador=VerificadorEd25519(),
        ambiente=Ambiente.SANDBOX,
        correo_pagador=correo,
        datos_pagador={},
    )
    return ejecutar, mandatos, consumo, pasarela, bitacora


def test_camino_feliz_aprueba_y_confirma_el_consumo():
    sk = Ed25519PrivateKey.generate()
    ejecutar, mandatos, consumo, _, bitacora = _armar()
    m = _mandato(sk, monto_max=Dinero.de_pesos(20_000), tope_total=Dinero.de_pesos(20_000),
                 usos_max=5)  # usos_max > 1 para no disparar la senal "ultimo uso"
    mandatos.guardar(m, Ambiente.SANDBOX)

    recibo = ejecutar(_intencion(2_050))

    assert recibo.ejecutado
    assert recibo.dictamen.decision is Decision.PERMITIR
    assert not recibo.aprobado_pese_a_violacion
    assert consumo.consumo_de(m.mandato_id).usos == 1
    assert bitacora.eventos[-1][0] == "cobro"


def test_tope_duro_por_transaccion_bloquea_antes_de_mirar_el_mandato():
    sk = Ed25519PrivateKey.generate()
    ejecutar, mandatos, consumo, _, _ = _armar()
    m = _mandato(sk, monto_max=Dinero.de_pesos(100_000), tope_total=Dinero.de_pesos(100_000))
    mandatos.guardar(m, Ambiente.SANDBOX)

    # 45.000 cabe en el mandato pero no en el tope duro de 20.000/tx.
    recibo = ejecutar(_intencion(45_000))

    assert not recibo.ejecutado
    assert recibo.dictamen.decision is Decision.BLOQUEAR
    assert "tope_duro_transaccion" in recibo.motivo
    # Ni siquiera se reservo cupo: el tope duro corta antes de tocar el libro.
    assert consumo.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(0)


def test_tope_diario_agotado_bloquea_y_no_reserva_de_mas():
    """El tope diario es del ambiente, no del mandato (igual que en la v1,
    donde `gastado_dia_cop` era compartido -- `docs/analisis-codigo.md`,
    hallazgo 13). El mandato se emite con mucho margen propio (monto_max y
    tope_total altos) para que lo unico que se este probando sea el tope
    duro de 100.000/dia, no ninguna senal blanda de la politica."""
    sk = Ed25519PrivateKey.generate()
    ejecutar, mandatos, consumo, _, _ = _armar()
    m = _mandato(
        sk, monto_max=Dinero.de_pesos(1_000_000),
        tope_total=Dinero.de_pesos(1_000_000), usos_max=999,
    )
    mandatos.guardar(m, Ambiente.SANDBOX)

    for i in range(5):  # 5 x 20.000 = 100.000: el tope diario exacto.
        recibo = ejecutar(_intencion(20_000, intencion_id=f"int_{i}"))
        assert recibo.ejecutado, recibo.dictamen

    recibo = ejecutar(_intencion(1_000, intencion_id="int_final"))
    assert not recibo.ejecutado
    assert "tope_duro_diario" in recibo.motivo


def test_monto_sobre_mandato_bloquea_y_libera_la_reserva():
    sk = Ed25519PrivateKey.generate()
    ejecutar, mandatos, consumo, _, _ = _armar()
    m = _mandato(sk)  # monto_max = 8.000
    mandatos.guardar(m, Ambiente.SANDBOX)

    recibo = ejecutar(_intencion(15_000))

    assert not recibo.ejecutado
    assert recibo.dictamen.decision is Decision.BLOQUEAR
    assert {v.tipo for v in recibo.dictamen.violaciones} >= {
        "monto_sobre_mandato", "tope_total_agotado"
    }
    # La reserva se libero: el cupo diario vuelve a cero.
    assert consumo.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(0)
    assert consumo.consumo_de(m.mandato_id).usos == 0


def test_confirmar_tambien_detiene_y_libera_pero_no_es_un_bloqueo():
    """Hoy `CONFIRMAR` se comporta como `BLOQUEAR` (se detiene, se libera la
    reserva): todavia no existe el mecanismo de retomar tras preguntarle al
    humano (etapas 4-5). Lo que si distingue un caso del otro es el
    `Dictamen.decision` que queda en el recibo -- por eso importa que este
    caso no pierda su propia senal."""
    sk = Ed25519PrivateKey.generate()
    ejecutar, mandatos, consumo, _, _ = _armar()
    m = _mandato(sk, monto_max=Dinero.de_pesos(8_000), tope_total=Dinero.de_pesos(8_000), usos_max=1)
    mandatos.guardar(m, Ambiente.SANDBOX)

    # Cabe exacto: no hay violacion, pero se lo gasta todo de una -> CONFIRMAR.
    recibo = ejecutar(_intencion(8_000))

    assert not recibo.ejecutado
    assert recibo.dictamen.decision is Decision.CONFIRMAR
    assert recibo.dictamen.violaciones == []
    assert recibo.dictamen.senales
    assert consumo.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(0)


def test_sin_exigir_mandato_deja_pasar_un_cobro_que_el_mandato_no_autorizaba():
    """Reproduce el hallazgo central de la PoC (`docs/analisis-codigo.md`):
    un mandato que autoriza 8.000 termina en un cobro `APPROVED` de 15.000,
    con la violacion registrada al lado. Esta vez, con la pasarela simulada,
    el resultado es reproducible en vez de depender de una corrida real."""
    sk = Ed25519PrivateKey.generate()
    ejecutar, mandatos, consumo, _, _ = _armar()
    m = _mandato(sk)  # monto_max = tope_total = 8.000
    mandatos.guardar(m, Ambiente.SANDBOX)

    recibo = ejecutar(_intencion(15_000), exigir_mandato=False)

    assert recibo.ejecutado
    assert recibo.aprobado_pese_a_violacion
    assert {v.tipo for v in recibo.dictamen.violaciones} >= {"monto_sobre_mandato"}
    assert consumo.consumo_de(m.mandato_id).acumulado == Dinero.de_pesos(15_000)


def test_declinado_por_antifraude_no_consume_el_mandato():
    """Equivalente a `tests/test_modos.py::test_un_declined_no_consume_el_
    mandato` en la v1: solo un APROBADO suma usos."""
    sk = Ed25519PrivateKey.generate()
    ejecutar, mandatos, consumo, _, _ = _armar(correo="boveda+poc@example.com")
    m = _mandato(sk, monto_max=Dinero.de_pesos(20_000), tope_total=Dinero.de_pesos(20_000),
                 usos_max=5)
    mandatos.guardar(m, Ambiente.SANDBOX)

    recibo = ejecutar(_intencion(2_000))

    assert not recibo.ejecutado
    assert recibo.dictamen.decision is Decision.PERMITIR  # el mandato lo dejo pasar
    assert recibo.detenido_por_antifraude
    assert consumo.consumo_de(m.mandato_id).usos == 0
    # DECLINED es un estado final: la reserva se libero.
    assert consumo.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(0)


def test_pendiente_deja_la_reserva_viva():
    """El cambio grande de la v2 frente a la v1 (`docs/arquitectura-v2.md`,
    seccion 6): `EjecutarIntencion` no espera. Un `PENDING` no se confirma ni
    se libera -- lo cierra `ConciliarEvento` desde el webhook (etapa 4)."""
    sk = Ed25519PrivateKey.generate()
    ejecutar, mandatos, consumo, _, _ = _armar(correo="cliente.pendiente@correo-real.com")
    m = _mandato(sk, monto_max=Dinero.de_pesos(20_000), tope_total=Dinero.de_pesos(20_000),
                 usos_max=5)
    mandatos.guardar(m, Ambiente.SANDBOX)

    recibo = ejecutar(_intencion(2_000))

    assert not recibo.ejecutado  # PENDING no es APROBADO
    assert recibo.motivo == "PENDING"
    assert consumo.consumo_de(m.mandato_id).usos == 0
    # La reserva sigue viva: el cupo diario la sigue contando.
    assert consumo.gastado_hoy(Ambiente.SANDBOX) == Dinero.de_pesos(2_000)


def test_mandato_de_otro_ambiente_no_se_ejecuta():
    sk = Ed25519PrivateKey.generate()
    ejecutar, mandatos, _, _, _ = _armar()
    m = _mandato(sk)
    mandatos.guardar(m, Ambiente.PRODUCCION)  # se guarda en produccion...

    with pytest.raises(Exception, match="produccion"):
        ejecutar(_intencion(2_000))  # ...pero se ejecuta en sandbox
