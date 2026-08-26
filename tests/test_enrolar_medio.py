"""`EnrolarMedio`: token -> sondeo -> confirmacion -> `RepositorioMedios.
guardar`. Un doble de pasarela controla exactamente cuantas veces hay que
sondear antes de llegar a un estado final, para no depender de `time.sleep`
real en la prueba (se pasa `pausa_seg=0`)."""

from __future__ import annotations

import pytest

from agora.adaptadores.persistencia.memoria import RepositorioMediosEnMemoria
from agora.aplicacion.enrolar_medio import EnrolarMedio
from agora.dominio.comun.errores import MedioNoAprobado
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor
from agora.puertos.pasarela import EstadoMedio, MedioEnProceso


class _BitacoraEnLista:
    def __init__(self) -> None:
        self.eventos: list[tuple[str, object]] = []

    def anotar(self, evento: str, cuerpo: object) -> None:
        self.eventos.append((evento, cuerpo))


class _PasarelaFalsa:
    nombre = "falsa"

    def __init__(self, estados_token: list[str], estado_confirmacion: str = "AVAILABLE") -> None:
        self._estados_token = list(estados_token)
        self._estado_confirmacion = estado_confirmacion
        self.llamadas_confirmar = 0

    def preparar_medio(self, solicitud):
        return MedioEnProceso(token="tok_1", estado=self._estados_token.pop(0))

    def estado_medio_por_token(self, token: str) -> EstadoMedio:
        # No se queda sin elementos: el ultimo se repite en vez de agotarse,
        # para que un escenario de "nunca llega a un estado final" pueda
        # sondear tantas veces como el limite de tiempo lo permita sin un
        # IndexError.
        if len(self._estados_token) > 1:
            return EstadoMedio(estado=self._estados_token.pop(0))
        return EstadoMedio(estado=self._estados_token[0])

    def confirmar_medio(self, token: str, correo: str) -> EstadoMedio:
        self.llamadas_confirmar += 1
        if self._estado_confirmacion != "AVAILABLE":
            return EstadoMedio(estado=self._estado_confirmacion)
        ref = MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_nuevo")
        return EstadoMedio(estado="AVAILABLE", ref=ref)


def _armar(pasarela: _PasarelaFalsa) -> tuple[EnrolarMedio, RepositorioMediosEnMemoria]:
    medios = RepositorioMediosEnMemoria()
    enrolar = EnrolarMedio(
        pasarela=pasarela, medios=medios, bitacora=_BitacoraEnLista(),
        ambiente=Ambiente.SANDBOX, espera_seg=0.05, pausa_seg=0,
    )
    return enrolar, medios


def test_camino_feliz_sondea_hasta_aprobado_y_guarda_el_medio():
    pasarela = _PasarelaFalsa(estados_token=["PENDING", "PENDING", "APPROVED"])
    enrolar, medios = _armar(pasarela)

    ref = enrolar("3001234567", "titular@correo.com", "tit_1")

    assert ref.id_externo == "src_nuevo"
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == [ref]


def test_token_que_nunca_llega_a_approved_levanta():
    pasarela = _PasarelaFalsa(estados_token=["PENDING"] * 50)  # nunca llega a un final
    enrolar, medios = _armar(pasarela)

    with pytest.raises(MedioNoAprobado):
        enrolar("3001234567", "titular@correo.com", "tit_1")
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == []


def test_token_declinado_levanta_sin_llamar_a_confirmar():
    pasarela = _PasarelaFalsa(estados_token=["DECLINED"])
    enrolar, _ = _armar(pasarela)

    with pytest.raises(MedioNoAprobado):
        enrolar("3001234567", "titular@correo.com", "tit_1")
    assert pasarela.llamadas_confirmar == 0


def test_confirmacion_que_no_queda_disponible_levanta():
    pasarela = _PasarelaFalsa(estados_token=["APPROVED"], estado_confirmacion="DECLINED")
    enrolar, medios = _armar(pasarela)

    with pytest.raises(MedioNoAprobado):
        enrolar("3001234567", "titular@correo.com", "tit_1")
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == []


def test_al_avanzar_recibe_las_etapas():
    pasarela = _PasarelaFalsa(estados_token=["PENDING", "APPROVED"])
    enrolar, _ = _armar(pasarela)
    vistas: list[str] = []

    enrolar("3001234567", "titular@correo.com", "tit_1", al_avanzar=lambda etapa, _d: vistas.append(etapa))

    assert vistas == ["token", "sondeo", "lista"]
