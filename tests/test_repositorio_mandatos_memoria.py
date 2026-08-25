"""`RepositorioMandatosEnMemoria`: la version tipada de la guarda de ambiente.

Equivalente en la v1: `nucleo.py:319-330`, `tests/test_modos.py`. Alli el
ambiente vivia en un `dict` `modos` aparte, revisado a mano dentro de
`obtener`. Aqui es un parametro obligatorio del puerto -- no se puede llamar
`obtener(mandato_id)` sin decir desde que ambiente, asi que no se puede
olvidar la guarda.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agora.adaptadores.persistencia.memoria.repositorio_mandatos import (
    RepositorioMandatosEnMemoria,
)
from agora.dominio.comun.dinero import Dinero
from agora.dominio.comun.errores import MandatoDesconocido, MandatoDeOtroAmbiente
from agora.dominio.mandato.modelo import Mandato
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor

HOY = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def _mandato(mandato_id: str, ambiente: Ambiente) -> Mandato:
    return Mandato(
        mandato_id=mandato_id,
        titular_id="tit_1",
        medio=MedioDePagoRef(Proveedor.WOMPI, ambiente, "22620436"),
        comercio_id="com_x",
        monto_max=Dinero.de_pesos(5_000),
        tope_total=Dinero.de_pesos(5_000),
        usos_max=1,
        expira_en=HOY,
        creado_en=HOY,
        llave_publica=b"",
    )


def test_guardar_y_obtener_en_el_mismo_ambiente():
    repo = RepositorioMandatosEnMemoria()
    m = _mandato("mnd_1", Ambiente.SANDBOX)
    repo.guardar(m, Ambiente.SANDBOX)

    assert repo.obtener("mnd_1", Ambiente.SANDBOX) == m


def test_mandato_desconocido():
    repo = RepositorioMandatosEnMemoria()
    with pytest.raises(MandatoDesconocido):
        repo.obtener("mnd_fantasma", Ambiente.SANDBOX)


def test_mandato_de_sandbox_no_se_obtiene_desde_produccion():
    """El bug que esta guarda existe para evitar: un mandato de sandbox
    ejecutado en produccion mandaria un id de fuente de pago de sandbox a la
    Wompi real, donde ese numero pertenece a otra persona."""
    repo = RepositorioMandatosEnMemoria()
    m = _mandato("mnd_1", Ambiente.SANDBOX)
    repo.guardar(m, Ambiente.SANDBOX)

    with pytest.raises(MandatoDeOtroAmbiente, match="sandbox"):
        repo.obtener("mnd_1", Ambiente.PRODUCCION)


def test_listar_filtra_por_ambiente():
    repo = RepositorioMandatosEnMemoria()
    repo.guardar(_mandato("mnd_sb", Ambiente.SANDBOX), Ambiente.SANDBOX)
    repo.guardar(_mandato("mnd_pr", Ambiente.PRODUCCION), Ambiente.PRODUCCION)

    assert [m.mandato_id for m in repo.listar(Ambiente.SANDBOX)] == ["mnd_sb"]
    assert [m.mandato_id for m in repo.listar(Ambiente.PRODUCCION)] == ["mnd_pr"]
