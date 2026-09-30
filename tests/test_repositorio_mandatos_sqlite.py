"""`RepositorioMandatosSQLite`: la misma guarda de ambiente que
`RepositorioMandatosEnMemoria` (`tests/test_repositorio_mandatos_memoria.py`),
mas la propiedad que solo SQLite ofrece -- el mandato sobrevive un reinicio.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agora.adaptadores.persistencia.sqlite.repositorio_mandatos import (
    RepositorioMandatosSQLite,
)
from agora.model.commons.dinero import Dinero
from agora.model.commons.errores import MandatoDesconocido, MandatoDeOtroAmbiente
from agora.model.mandato.modelo import Mandato
from agora.model.pago.modelo import Ambiente, MedioDePagoRef, Proveedor

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
        llave_publica=b"llave-publica-de-prueba",
        categorias=("comida", "domicilios"),
        carrito_hash="hash_x",
        firma=b"firma-de-prueba",
    )


def test_guardar_y_obtener_en_el_mismo_ambiente(tmp_path):
    repo = RepositorioMandatosSQLite(tmp_path / "agora.db")
    m = _mandato("mnd_1", Ambiente.SANDBOX)
    repo.guardar(m, Ambiente.SANDBOX)

    assert repo.obtener("mnd_1", Ambiente.SANDBOX) == m


def test_mandato_desconocido(tmp_path):
    repo = RepositorioMandatosSQLite(tmp_path / "agora.db")
    with pytest.raises(MandatoDesconocido):
        repo.obtener("mnd_fantasma", Ambiente.SANDBOX)


def test_mandato_de_sandbox_no_se_obtiene_desde_produccion(tmp_path):
    """El bug que esta guarda existe para evitar: un mandato de sandbox
    ejecutado en produccion mandaria un id de fuente de pago de sandbox a la
    Wompi real, donde ese numero pertenece a otra persona."""
    repo = RepositorioMandatosSQLite(tmp_path / "agora.db")
    m = _mandato("mnd_1", Ambiente.SANDBOX)
    repo.guardar(m, Ambiente.SANDBOX)

    with pytest.raises(MandatoDeOtroAmbiente, match="sandbox"):
        repo.obtener("mnd_1", Ambiente.PRODUCCION)


def test_listar_filtra_por_ambiente(tmp_path):
    repo = RepositorioMandatosSQLite(tmp_path / "agora.db")
    repo.guardar(_mandato("mnd_sb", Ambiente.SANDBOX), Ambiente.SANDBOX)
    repo.guardar(_mandato("mnd_pr", Ambiente.PRODUCCION), Ambiente.PRODUCCION)

    assert [m.mandato_id for m in repo.listar(Ambiente.SANDBOX)] == ["mnd_sb"]
    assert [m.mandato_id for m in repo.listar(Ambiente.PRODUCCION)] == ["mnd_pr"]


def test_guardar_es_idempotente_por_mandato_id(tmp_path):
    """`INSERT OR REPLACE`: volver a guardar el mismo mandato_id no revienta
    con una violacion de PRIMARY KEY."""
    repo = RepositorioMandatosSQLite(tmp_path / "agora.db")
    m = _mandato("mnd_1", Ambiente.SANDBOX)
    repo.guardar(m, Ambiente.SANDBOX)
    repo.guardar(m, Ambiente.SANDBOX)

    assert len(repo.listar(Ambiente.SANDBOX)) == 1


def test_el_mandato_sobrevive_una_reconexion(tmp_path):
    """Lo que la version en memoria no puede ofrecer: dos instancias del
    adaptador apuntando al mismo archivo ven el mismo mandato."""
    ruta = tmp_path / "agora.db"
    m = _mandato("mnd_1", Ambiente.SANDBOX)

    repo_1 = RepositorioMandatosSQLite(ruta)
    repo_1.guardar(m, Ambiente.SANDBOX)
    del repo_1

    repo_2 = RepositorioMandatosSQLite(ruta)
    assert repo_2.obtener("mnd_1", Ambiente.SANDBOX) == m
