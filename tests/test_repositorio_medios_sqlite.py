"""`RepositorioMediosSQLite`: sin equivalente en memoria probado en la etapa
2 (`RepositorioMediosEnMemoria` existia pero nada lo ejercitaba todavia --
nada de `agora/` lo necesita hasta `aplicacion/enrolar_medio.py`, etapa 5).
Aqui si se prueba, porque es el destino directo de `scripts/
migrar_fuentes_a_sqlite.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from agora.adaptadores.persistencia.sqlite.repositorio_medios import (
    RepositorioMediosSQLite,
)
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor


@dataclass
class _RelojFijo:
    cuando: datetime

    def ahora(self) -> datetime:
        return self.cuando


HOY = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def test_guardar_y_listar_vivos(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22620436")
    repo.guardar(ref, "tit_1")

    assert repo.vivos("tit_1", Ambiente.SANDBOX) == [ref]


def test_vivos_filtra_por_titular_y_ambiente(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    mio_sandbox = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "1")
    mio_produccion = MedioDePagoRef(Proveedor.WOMPI, Ambiente.PRODUCCION, "2")
    ajeno = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "3")
    repo.guardar(mio_sandbox, "tit_1")
    repo.guardar(mio_produccion, "tit_1")
    repo.guardar(ajeno, "tit_2")

    assert repo.vivos("tit_1", Ambiente.SANDBOX) == [mio_sandbox]


def test_marcar_estado_saca_el_medio_de_vivos(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22620436")
    repo.guardar(ref, "tit_1")
    repo.marcar_estado(ref, "VOIDED")

    assert repo.vivos("tit_1", Ambiente.SANDBOX) == []


def test_guardar_es_idempotente_por_proveedor_ambiente_id_externo(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22620436")
    repo.guardar(ref, "tit_1")
    repo.guardar(ref, "tit_1")

    assert repo.vivos("tit_1", Ambiente.SANDBOX) == [ref]


def test_el_medio_sobrevive_una_reconexion(tmp_path):
    ruta = tmp_path / "agora.db"
    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22620436")

    repo_1 = RepositorioMediosSQLite(ruta, _RelojFijo(HOY))
    repo_1.guardar(ref, "tit_1")
    del repo_1

    repo_2 = RepositorioMediosSQLite(ruta, _RelojFijo(HOY))
    assert repo_2.vivos("tit_1", Ambiente.SANDBOX) == [ref]
