"""`EmitirMandatoUseCase`: la firma del humano. Verifica que el mandato que sale
valida contra `VerificadorEd25519`, que `carrito_hash` sale del carrito
guardado (no de lo que diga la propuesta), y las tres formas de fallar antes
de firmar -- incluida la propuesta que no se busco desde
`RepositorioPropuestas` (etapa 6): `emitir()` ahora recibe `propuesta_id`,
nunca el objeto `PropuestaDeMandato` directo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from agora.adaptadores.persistencia.memoria import (
    RepositorioCarritosEnMemoria,
    RepositorioMandatosEnMemoria,
    RepositorioMediosEnMemoria,
    RepositorioPropuestasEnMemoria,
)
from agora.adaptadores.sistema import GeneradorIdsUuid, VerificadorEd25519, cargar_o_generar_firmante
from agora.usecase.emitir_mandato.emitir_mandato_use_case import EmitirMandatoUseCase
from agora.model.catalogo.modelo import Carrito, ItemCarrito
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import (
    PropuestaDesconocida,
    PropuestaInvalida,
    SinMedioDePagoVivo,
    SinMedioVinculadoAlComercio,
)
from agora.model.mandato.modelo import PropuestaDeMandato
from agora.model.pago.modelo import Ambiente, MedioDePagoRef, Proveedor

AHORA = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


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


class _SelectorFirmanteFijo:
    """Test double de `puertos.firma.SelectorDeFirmante`: estas pruebas
    ejercitan la logica PROPIA de `EmitirMandatoUseCase` (limites, resolucion de
    medio, comercio_id), no la resolucion multi-usuario de la llave -- un
    selector que siempre devuelve el mismo `Firmante` alcanza, igual que
    `RegistroDeFirmantes` haria con un solo titular ya provisto."""

    def __init__(self, firmante) -> None:
        self._firmante = firmante

    def para(self, titular_id: str):
        return self._firmante


def _carrito() -> Carrito:
    return Carrito(
        carrito_id="car_1", comercio_id="com_1",
        items=(ItemCarrito(producto_id="prd_1", nombre="Audifonos", cantidad=1,
                            precio_unitario=Dinero.de_pesos(120_000)),),
    )


def _propuesta(**kw) -> PropuestaDeMandato:
    base = dict(
        propuesta_id="prp_1", carrito_id="car_1", comercio_id="com_1",
        monto_max=Dinero.de_pesos(120_000), usos_max=1, vigencia_minutos=30,
    )
    base.update(kw)
    return PropuestaDeMandato(**base)


def _armar(tmp_path, con_medio: bool = True):
    carritos = RepositorioCarritosEnMemoria()
    carritos.guardar(_carrito())
    propuestas = RepositorioPropuestasEnMemoria()
    propuestas.guardar(_propuesta())
    medios = RepositorioMediosEnMemoria()
    if con_medio:
        # "com_1": el mismo comercio de `_carrito()`/`_propuesta()` -- este
        # medio esta VINCULADO a ese comercio, no solo "vivo".
        medios.guardar(MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_1"), "tit_1", "com_1")
    mandatos = RepositorioMandatosEnMemoria()
    firmante = cargar_o_generar_firmante(tmp_path / "firma.sk", tmp_path / "firma.pk")
    emitir = EmitirMandatoUseCase(
        carritos=carritos, propuestas=propuestas, medios=medios, mandatos=mandatos,
        selector_firmante=_SelectorFirmanteFijo(firmante), ids=GeneradorIdsUuid(),
        reloj=_RelojFijo(AHORA), bitacora=_BitacoraEnLista(), ambiente=Ambiente.SANDBOX,
    )
    return emitir, mandatos, firmante, propuestas


def test_camino_feliz_firma_un_mandato_valido(tmp_path):
    emitir, mandatos, firmante, _ = _armar(tmp_path)

    mandato = emitir("prp_1", "tit_1")

    assert mandato.titular_id == "tit_1"
    assert mandato.comercio_id == "com_1"
    assert mandato.monto_max == Dinero.de_pesos(120_000)
    assert mandato.carrito_hash == _carrito().hash_canonico
    assert mandato.llave_publica == firmante.llave_publica()
    assert VerificadorEd25519().verifica(mandato.firma, mandato.canonico(), mandato.llave_publica)
    assert mandatos.obtener(mandato.mandato_id, Ambiente.SANDBOX) == mandato


def test_propuesta_con_comercio_que_no_coincide_con_el_carrito_levanta(tmp_path):
    emitir, _, _, propuestas = _armar(tmp_path)
    propuestas.guardar(_propuesta(propuesta_id="prp_ajena", comercio_id="com_ajeno"))
    with pytest.raises(PropuestaInvalida):
        emitir("prp_ajena", "tit_1")


def test_sin_medio_de_pago_vivo_levanta(tmp_path):
    emitir, _, _, _ = _armar(tmp_path, con_medio=False)
    with pytest.raises(SinMedioDePagoVivo):
        emitir("prp_1", "tit_1")


def test_propuesta_desconocida_levanta(tmp_path):
    emitir, _, _, _ = _armar(tmp_path)
    with pytest.raises(PropuestaDesconocida):
        emitir("prp_nunca_existio", "tit_1")


def test_usa_el_medio_mas_reciente_vinculado_a_ese_comercio(tmp_path):
    """Multi-comercio: "el mas reciente" ya no es global -- es el mas
    reciente ENTRE los vinculados a `propuesta.comercio_id` ("com_1"). Un
    medio vinculado a otro comercio ("com_ajeno") no es candidato aunque sea
    mas nuevo que cualquiera de los de "com_1"."""
    carritos = RepositorioCarritosEnMemoria()
    carritos.guardar(_carrito())
    propuestas = RepositorioPropuestasEnMemoria()
    propuestas.guardar(_propuesta())
    medios = RepositorioMediosEnMemoria()
    medios.guardar(MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_viejo"), "tit_1", "com_1")
    medios.guardar(MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_nuevo"), "tit_1", "com_1")
    # Mas nuevo que los dos anteriores, pero vinculado a OTRO comercio: no
    # deberia poder elegirse para firmar contra "com_1".
    medios.guardar(MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_ajeno"), "tit_1", "com_ajeno")
    firmante = cargar_o_generar_firmante(tmp_path / "firma.sk", tmp_path / "firma.pk")
    emitir = EmitirMandatoUseCase(
        carritos=carritos, propuestas=propuestas, medios=medios,
        mandatos=RepositorioMandatosEnMemoria(), selector_firmante=_SelectorFirmanteFijo(firmante),
        ids=GeneradorIdsUuid(), reloj=_RelojFijo(AHORA), bitacora=_BitacoraEnLista(),
        ambiente=Ambiente.SANDBOX,
    )

    mandato = emitir("prp_1", "tit_1")

    assert mandato.medio.id_externo == "src_nuevo"


def test_medio_vivo_pero_de_otro_comercio_levanta_sin_medio_vinculado(tmp_path):
    """El caso central de la vinculacion por comercio (1 de septiembre de
    2026): el titular SI tiene un medio vivo -- lo enrolo para comprar en
    otro comercio -- pero nunca lo vinculo con "com_1". Tiene que levantar
    `SinMedioVinculadoAlComercio`, NUNCA `SinMedioDePagoVivo` (esa es para
    "no enrolo nada todavia") -- son dos situaciones distintas y quien
    reciba el error necesita distinguirlas para saber si hay que enrolar
    por primera vez o solo vincular un comercio nuevo."""
    carritos = RepositorioCarritosEnMemoria()
    carritos.guardar(_carrito())
    propuestas = RepositorioPropuestasEnMemoria()
    propuestas.guardar(_propuesta())
    medios = RepositorioMediosEnMemoria()
    medios.guardar(MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_1"), "tit_1", "com_otro")
    firmante = cargar_o_generar_firmante(tmp_path / "firma.sk", tmp_path / "firma.pk")
    emitir = EmitirMandatoUseCase(
        carritos=carritos, propuestas=propuestas, medios=medios,
        mandatos=RepositorioMandatosEnMemoria(), selector_firmante=_SelectorFirmanteFijo(firmante),
        ids=GeneradorIdsUuid(), reloj=_RelojFijo(AHORA), bitacora=_BitacoraEnLista(),
        ambiente=Ambiente.SANDBOX,
    )

    with pytest.raises(SinMedioVinculadoAlComercio):
        emitir("prp_1", "tit_1")
