"""`SondeoDePagosPendientes` (etapa 9), aislado de hilos, `time.sleep` real
y del resto de la app: `una_pasada()` se llama directo, con dobles simples
en vez de `AlmacenDeSesiones`/`consultar_estado` reales -- lo mismo que
`tests/test_enrolar_medio.py` hace con `_PasarelaFalsa` para no depender de
sondeo real contra una pasarela."""

from __future__ import annotations

from dataclasses import dataclass

from agora.model.commons.errores import EstadoDesconocido
from agora.entradas.api.sondeo_pagos import SondeoDePagosPendientes


@dataclass
class _EstadoFalso:
    intencion_id: str
    estado: str
    detalle: str = ""


class _SesionesFalsas:
    """Sustituye a `AlmacenDeSesiones`: solo lo que `SondeoDePagosPendientes`
    de verdad usa (`pendientes()`, `resolver_pendiente()`)."""

    def __init__(self, pendientes: dict[str, str]) -> None:
        self._pendientes = dict(pendientes)
        self.resueltas: list[tuple[str, str]] = []

    def pendientes(self) -> dict[str, str]:
        return dict(self._pendientes)

    def resolver_pendiente(self, intencion_id: str, estado: str) -> str | None:
        self._pendientes.pop(intencion_id, None)
        self.resueltas.append((intencion_id, estado))
        return f"avisado:{intencion_id}"


def _consultar_con(estados: dict[str, str]):
    """`estados` mapea intencion_id -> estado a devolver. Una intencion sin
    entrada levanta `EstadoDesconocido`, como haria `ConsultarEstado` real
    contra un registro que nunca oyo hablar de ese id."""

    def consultar(intencion_id: str) -> _EstadoFalso:
        if intencion_id not in estados:
            raise EstadoDesconocido(f"no hay estado para '{intencion_id}'")
        return _EstadoFalso(intencion_id=intencion_id, estado=estados[intencion_id])

    return consultar


def test_una_pasada_resuelve_las_que_ya_llegaron_a_un_estado_final():
    sesiones = _SesionesFalsas({"int_1": "ses_1", "int_2": "ses_2"})
    consultar = _consultar_con({"int_1": "aprobado", "int_2": "rechazado"})
    sondeo = SondeoDePagosPendientes(sesiones, consultar)

    sondeo.una_pasada()

    assert sorted(sesiones.resueltas) == [("int_1", "aprobado"), ("int_2", "rechazado")]


def test_una_pasada_deja_en_paz_las_que_siguen_pendientes():
    sesiones = _SesionesFalsas({"int_1": "ses_1"})
    consultar = _consultar_con({"int_1": "pendiente"})
    sondeo = SondeoDePagosPendientes(sesiones, consultar)

    sondeo.una_pasada()

    assert sesiones.resueltas == []
    assert sesiones.pendientes() == {"int_1": "ses_1"}


def test_una_pasada_ignora_un_registro_huerfano_sin_tumbar_el_resto():
    sesiones = _SesionesFalsas({"int_huerfano": "ses_1", "int_2": "ses_2"})
    consultar = _consultar_con({"int_2": "aprobado"})  # int_huerfano no esta
    sondeo = SondeoDePagosPendientes(sesiones, consultar)

    sondeo.una_pasada()

    assert sesiones.resueltas == [("int_2", "aprobado")]


def test_una_pasada_no_muere_si_consultar_estado_explota_para_una_intencion():
    sesiones = _SesionesFalsas({"int_1": "ses_1", "int_2": "ses_2"})

    def consultar(intencion_id: str) -> _EstadoFalso:
        if intencion_id == "int_1":
            raise RuntimeError("la base de datos esta de mal humor")
        return _EstadoFalso(intencion_id=intencion_id, estado="aprobado")

    sondeo = SondeoDePagosPendientes(sesiones, consultar)

    sondeo.una_pasada()  # no debe levantar

    assert sesiones.resueltas == [("int_2", "aprobado")]


def test_iniciar_y_detener_no_dejan_el_hilo_colgado():
    sesiones = _SesionesFalsas({})
    sondeo = SondeoDePagosPendientes(sesiones, _consultar_con({}), intervalo_seg=0.01)

    sondeo.iniciar()
    sondeo.detener()

    assert sondeo._hilo is not None
    assert not sondeo._hilo.is_alive()
