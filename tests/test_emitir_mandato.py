"""`EmitirMandato`: la firma del humano. Verifica que el mandato que sale
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
from agora.aplicacion.emitir_mandato import EmitirMandato
from agora.dominio.catalogo.modelo import Carrito, ItemCarrito
from agora.dominio.comun.dinero import Dinero
from agora.dominio.comun.errores import (
    PropuestaDesconocida,
    PropuestaInvalida,
    SinMedioDePagoVivo,
)
from agora.dominio.mandato.modelo import PropuestaDeMandato
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor

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
        medios.guardar(MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_1"), "tit_1")
    mandatos = RepositorioMandatosEnMemoria()
    firmante = cargar_o_generar_firmante(tmp_path / "firma.sk", tmp_path / "firma.pk")
    emitir = EmitirMandato(
        carritos=carritos, propuestas=propuestas, medios=medios, mandatos=mandatos,
        firmante=firmante, ids=GeneradorIdsUuid(), reloj=_RelojFijo(AHORA),
        bitacora=_BitacoraEnLista(), ambiente=Ambiente.SANDBOX,
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


def test_usa_el_medio_mas_reciente(tmp_path):
    carritos = RepositorioCarritosEnMemoria()
    carritos.guardar(_carrito())
    propuestas = RepositorioPropuestasEnMemoria()
    propuestas.guardar(_propuesta())
    medios = RepositorioMediosEnMemoria()
    medios.guardar(MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_viejo"), "tit_1")
    medios.guardar(MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_nuevo"), "tit_1")
    firmante = cargar_o_generar_firmante(tmp_path / "firma.sk", tmp_path / "firma.pk")
    emitir = EmitirMandato(
        carritos=carritos, propuestas=propuestas, medios=medios,
        mandatos=RepositorioMandatosEnMemoria(), firmante=firmante, ids=GeneradorIdsUuid(),
        reloj=_RelojFijo(AHORA), bitacora=_BitacoraEnLista(), ambiente=Ambiente.SANDBOX,
    )

    mandato = emitir("prp_1", "tit_1")

    assert mandato.medio.id_externo == "src_nuevo"
