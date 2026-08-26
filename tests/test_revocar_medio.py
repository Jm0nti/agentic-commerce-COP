"""`RevocarMedio`: el boton de panico. Primero verifica que el medio
pertenezca al titular en este ambiente (revocar a ciegas puede apagar la
fuente equivocada), despues le pide a la pasarela que revoque."""

from __future__ import annotations

import pytest

from agora.adaptadores.persistencia.memoria import RepositorioMediosEnMemoria
from agora.aplicacion.revocar_medio import RevocarMedio
from agora.dominio.comun.errores import MedioNoRegistrado
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor
from agora.puertos.pasarela import EstadoMedio


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
    medios.guardar(REF, "tit_1")
    pasarela = _PasarelaFalsa()
    revocar = RevocarMedio(pasarela=pasarela, medios=medios, bitacora=_BitacoraEnLista())

    estado = revocar(REF, "tit_1")

    assert estado == "VOIDED"
    assert pasarela.revocados == [REF]
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == []  # ya no esta vivo


def test_medio_que_no_pertenece_al_titular_levanta_sin_llamar_a_la_pasarela():
    medios = RepositorioMediosEnMemoria()
    medios.guardar(REF, "tit_otro")
    pasarela = _PasarelaFalsa()
    revocar = RevocarMedio(pasarela=pasarela, medios=medios, bitacora=_BitacoraEnLista())

    with pytest.raises(MedioNoRegistrado):
        revocar(REF, "tit_1")
    assert pasarela.revocados == []
