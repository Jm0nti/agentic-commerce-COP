"""`RevocarMedio`: el boton de panico. Primero verifica que el medio
pertenezca al titular en este ambiente (revocar a ciegas puede apagar la
fuente equivocada), despues resuelve el comercio que lo creo
(`RepositorioMedios.comercio_de`) y le pide a la pasarela de ESE comercio
que revoque."""

from __future__ import annotations

import pytest

from agora.adaptadores.pasarelas.registro import RegistroDePasarelas
from agora.adaptadores.persistencia.memoria import RepositorioMediosEnMemoria
from agora.aplicacion.revocar_medio import RevocarMedio
from agora.dominio.comun.errores import MedioNoRegistrado
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor
from agora.puertos.pasarela import EstadoMedio

COMERCIO_ID = "com_1"


class _BitacoraEnLista:
    def __init__(self) -> None:
        self.eventos: list[tuple[str, object]] = []

    def anotar(self, evento: str, cuerpo: object) -> None:
        self.eventos.append((evento, cuerpo))


class _PasarelaFalsa:
    nombre = "falsa"

    def __init__(self) -> None:
        self.revocados: list[MedioDePagoRef] = []

    def revocar_medio(self, ref: MedioDePagoRef) -> EstadoMedio:
        self.revocados.append(ref)
        return EstadoMedio(estado="VOIDED", ref=ref)


REF = MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_1")


def test_camino_feliz_revoca_y_marca_el_estado():
    medios = RepositorioMediosEnMemoria()
    medios.guardar(REF, "tit_1", COMERCIO_ID)
    pasarela = _PasarelaFalsa()
    revocar = RevocarMedio(
        selector_pasarela=RegistroDePasarelas({}, por_defecto=pasarela),
        medios=medios, bitacora=_BitacoraEnLista(),
    )

    estado = revocar(REF, "tit_1")

    # Devuelve el `EstadoMedio` completo (7 sept 2026), no un string a
    # secas -- ver el docstring del modulo, seccion "DEVUELVE EstadoMedio".
    assert estado.estado == "VOIDED"
    assert pasarela.revocados == [REF]
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == []  # ya no esta vivo


def test_un_desenlace_solo_local_tambien_desactiva_y_propaga_el_aviso():
    """Cuando la pasarela no puede anular de verdad (Nequi por Wompi, ver
    `AdaptadorWompi.revocar_medio`) devuelve `estado="VOIDED_LOCAL"` con un
    aviso en `detalle` en vez de levantar. `RevocarMedio` tiene que: (a)
    desactivar el medio igual (cualquier estado != AVAILABLE alcanza), y
    (b) NO tirar ese aviso a la basura -- quien llama (CLI/API) lo necesita
    para avisarle al titular que todavia tiene que cancelarlo el mismo."""
    class _PasarelaQueNoPuedeAnular:
        nombre = "falsa"

        def revocar_medio(self, ref: MedioDePagoRef) -> EstadoMedio:
            return EstadoMedio(
                estado="VOIDED_LOCAL", ref=ref,
                detalle={"aviso": "cancelalo tambien desde tu app Nequi"},
            )

    medios = RepositorioMediosEnMemoria()
    medios.guardar(REF, "tit_1", COMERCIO_ID)
    bitacora = _BitacoraEnLista()
    revocar = RevocarMedio(
        selector_pasarela=RegistroDePasarelas({}, por_defecto=_PasarelaQueNoPuedeAnular()),
        medios=medios, bitacora=bitacora,
    )

    estado = revocar(REF, "tit_1")

    assert estado.estado == "VOIDED_LOCAL"
    assert estado.detalle == {"aviso": "cancelalo tambien desde tu app Nequi"}
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == []  # se desactivo igual
    evento, cuerpo = bitacora.eventos[-1]
    assert evento == "medio_revocado"
    assert cuerpo["detalle"] == {"aviso": "cancelalo tambien desde tu app Nequi"}


def test_medio_que_no_pertenece_al_titular_levanta_sin_llamar_a_la_pasarela():
    medios = RepositorioMediosEnMemoria()
    medios.guardar(REF, "tit_otro", COMERCIO_ID)
    pasarela = _PasarelaFalsa()
    revocar = RevocarMedio(
        selector_pasarela=RegistroDePasarelas({}, por_defecto=pasarela),
        medios=medios, bitacora=_BitacoraEnLista(),
    )

    with pytest.raises(MedioNoRegistrado):
        revocar(REF, "tit_1")
    assert pasarela.revocados == []
