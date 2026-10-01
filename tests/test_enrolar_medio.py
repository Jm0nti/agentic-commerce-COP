"""`EnrolarMedioUseCase`: token -> sondeo -> confirmacion -> `RepositorioMedios.
guardar`. Un doble de pasarela controla exactamente cuantas veces hay que
sondear antes de llegar a un estado final, para no depender de `time.sleep`
real en la prueba (se pasa `pausa_seg=0`).

MULTI-COMERCIO: los tres pasos y `EnrolarMedioUseCase` reciben un
`SelectorDePasarela`, no una `PasarelaDePagos` fija. Estas pruebas usan
`RegistroDePasarelas({}, por_defecto=pasarela)` -- la unica pasarela falsa
resuelve para cualquier `comercio_id`, que es exactamente el comportamiento
de `AGORA_PASARELA=simulada` en produccion -- y mandan un `comercio_id` fijo
("com_1") en cada llamada, ya que lo que se prueba aca es el sondeo, no el
ruteo por comercio (eso lo cubre `test_emitir_mandato.py`)."""

from __future__ import annotations

import pytest

from agora.adaptadores.pasarelas.registro import RegistroDePasarelas
from agora.adaptadores.persistencia.memoria import RepositorioMediosEnMemoria
from agora.usecase.enrolar_medio.enrolar_medio_use_case import EnrolarMedioUseCase
from agora.model.commons.errores import MedioNoAprobado
from agora.model.pago.modelo import Ambiente, MedioDePagoRef, Proveedor
from agora.model.pago.gateways.pasarela import EstadoMedio, MedioEnProceso

COMERCIO_ID = "com_1"


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


def _selector(pasarela: _PasarelaFalsa) -> RegistroDePasarelas:
    return RegistroDePasarelas({}, por_defecto=pasarela)


def _armar(pasarela: _PasarelaFalsa) -> tuple[EnrolarMedioUseCase, RepositorioMediosEnMemoria]:
    medios = RepositorioMediosEnMemoria()
    enrolar = EnrolarMedioUseCase(
        selector_pasarela=_selector(pasarela), medios=medios, bitacora=_BitacoraEnLista(),
        ambiente=Ambiente.SANDBOX, espera_seg=0.05, pausa_seg=0,
    )
    return enrolar, medios


def test_camino_feliz_sondea_hasta_aprobado_y_guarda_el_medio():
    pasarela = _PasarelaFalsa(estados_token=["PENDING", "PENDING", "APPROVED"])
    enrolar, medios = _armar(pasarela)

    ref = enrolar("3001234567", "titular@correo.com", "tit_1", COMERCIO_ID)

    assert ref.id_externo == "src_nuevo"
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == [ref]


def test_token_que_nunca_llega_a_approved_levanta():
    pasarela = _PasarelaFalsa(estados_token=["PENDING"] * 50)  # nunca llega a un final
    enrolar, medios = _armar(pasarela)

    with pytest.raises(MedioNoAprobado):
        enrolar("3001234567", "titular@correo.com", "tit_1", COMERCIO_ID)
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == []


def test_token_declinado_levanta_sin_llamar_a_confirmar():
    pasarela = _PasarelaFalsa(estados_token=["DECLINED"])
    enrolar, _ = _armar(pasarela)

    with pytest.raises(MedioNoAprobado):
        enrolar("3001234567", "titular@correo.com", "tit_1", COMERCIO_ID)
    assert pasarela.llamadas_confirmar == 0


def test_confirmacion_que_no_queda_disponible_levanta():
    pasarela = _PasarelaFalsa(estados_token=["APPROVED"], estado_confirmacion="DECLINED")
    enrolar, medios = _armar(pasarela)

    with pytest.raises(MedioNoAprobado):
        enrolar("3001234567", "titular@correo.com", "tit_1", COMERCIO_ID)
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == []


def test_al_avanzar_recibe_las_etapas():
    pasarela = _PasarelaFalsa(estados_token=["PENDING", "APPROVED"])
    enrolar, _ = _armar(pasarela)
    vistas: list[str] = []

    enrolar(
        "3001234567", "titular@correo.com", "tit_1", COMERCIO_ID,
        al_avanzar=lambda etapa, _d: vistas.append(etapa),
    )

    assert vistas == ["token", "sondeo", "lista"]


# -- Las piezas granulares que usa la web (etapa 8): mismo doble de pasarela,
# pero cada clase se prueba por separado en vez de solo a traves del sondeo
# bloqueante de `EnrolarMedioUseCase`. -------------------------------------------- #

from agora.usecase.confirmar_enrolamiento.confirmar_enrolamiento_use_case import (
    ConfirmarEnrolamientoUseCase,
)
from agora.usecase.consultar_enrolamiento.consultar_enrolamiento_use_case import (
    ConsultarEnrolamientoUseCase,
)
from agora.usecase.iniciar_enrolamiento.iniciar_enrolamiento_use_case import IniciarEnrolamientoUseCase


def test_iniciar_enrolamiento_devuelve_el_proceso_sin_bloquear():
    pasarela = _PasarelaFalsa(estados_token=["PENDING"])
    iniciar = IniciarEnrolamientoUseCase(selector_pasarela=_selector(pasarela), ambiente=Ambiente.SANDBOX)

    proceso = iniciar("3001234567", "titular@correo.com", COMERCIO_ID)

    assert proceso.token == "tok_1"
    assert proceso.estado == "PENDING"


def test_consultar_enrolamiento_delega_en_la_pasarela():
    pasarela = _PasarelaFalsa(estados_token=["PENDING", "APPROVED"])
    pasarela.preparar_medio(None)  # consume el primer estado, como haria iniciar()
    consultar = ConsultarEnrolamientoUseCase(selector_pasarela=_selector(pasarela))

    estado = consultar("tok_1", COMERCIO_ID)

    assert estado.estado == "APPROVED"


def test_confirmar_enrolamiento_guarda_el_medio_cuando_el_estado_es_approved():
    pasarela = _PasarelaFalsa(estados_token=["APPROVED"])
    medios = RepositorioMediosEnMemoria()
    bitacora = _BitacoraEnLista()
    confirmar = ConfirmarEnrolamientoUseCase(selector_pasarela=_selector(pasarela), medios=medios, bitacora=bitacora)

    ref = confirmar("tok_1", "titular@correo.com", "tit_1", "APPROVED", COMERCIO_ID)

    assert ref.id_externo == "src_nuevo"
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == [ref]
    assert pasarela.llamadas_confirmar == 1
    assert bitacora.eventos and bitacora.eventos[0][0] == "medio_enrolado"


def test_confirmar_enrolamiento_no_confirma_si_el_estado_token_no_es_approved():
    pasarela = _PasarelaFalsa(estados_token=["DECLINED"])
    medios = RepositorioMediosEnMemoria()
    confirmar = ConfirmarEnrolamientoUseCase(selector_pasarela=_selector(pasarela), medios=medios, bitacora=_BitacoraEnLista())

    with pytest.raises(MedioNoAprobado):
        confirmar("tok_1", "titular@correo.com", "tit_1", "DECLINED", COMERCIO_ID)

    assert pasarela.llamadas_confirmar == 0
    assert medios.vivos("tit_1", Ambiente.SANDBOX) == []


def test_confirmar_enrolamiento_levanta_si_la_pasarela_no_deja_el_medio_disponible():
    pasarela = _PasarelaFalsa(estados_token=["APPROVED"], estado_confirmacion="DECLINED")
    medios = RepositorioMediosEnMemoria()
    confirmar = ConfirmarEnrolamientoUseCase(selector_pasarela=_selector(pasarela), medios=medios, bitacora=_BitacoraEnLista())

    with pytest.raises(MedioNoAprobado):
        confirmar("tok_1", "titular@correo.com", "tit_1", "APPROVED", COMERCIO_ID)

    assert medios.vivos("tit_1", Ambiente.SANDBOX) == []
