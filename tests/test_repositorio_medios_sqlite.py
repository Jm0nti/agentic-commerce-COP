"""`RepositorioMediosSQLite`: sin equivalente en memoria probado en la etapa
2 (`RepositorioMediosEnMemoria` existia pero nada lo ejercitaba todavia --
nada de `agora/` lo necesita hasta `aplicacion/enrolar_medio.py`, etapa 5).
Aqui si se prueba, porque es el destino directo de `scripts/
migrar_fuentes_a_sqlite.py`.

Multi-comercio (1 de septiembre de 2026): `guardar` ahora exige
`comercio_id`, y el repositorio expone `vinculado_con`/`comercio_de` -- ver
el docstring de `puertos.repositorios.RepositorioMedios`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from agora.adaptadores.persistencia.sqlite.conexion import abrir_conexion
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
    repo.guardar(ref, "tit_1", "com_1")

    assert repo.vivos("tit_1", Ambiente.SANDBOX) == [ref]


def test_vivos_filtra_por_titular_y_ambiente(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    mio_sandbox = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "1")
    mio_produccion = MedioDePagoRef(Proveedor.WOMPI, Ambiente.PRODUCCION, "2")
    ajeno = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "3")
    repo.guardar(mio_sandbox, "tit_1", "com_1")
    repo.guardar(mio_produccion, "tit_1", "com_1")
    repo.guardar(ajeno, "tit_2", "com_1")

    assert repo.vivos("tit_1", Ambiente.SANDBOX) == [mio_sandbox]


def test_marcar_estado_saca_el_medio_de_vivos(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22620436")
    repo.guardar(ref, "tit_1", "com_1")
    repo.marcar_estado(ref, "VOIDED")

    assert repo.vivos("tit_1", Ambiente.SANDBOX) == []


def test_guardar_es_idempotente_por_proveedor_ambiente_id_externo(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22620436")
    repo.guardar(ref, "tit_1", "com_1")
    repo.guardar(ref, "tit_1", "com_1")

    assert repo.vivos("tit_1", Ambiente.SANDBOX) == [ref]


def test_el_medio_sobrevive_una_reconexion(tmp_path):
    ruta = tmp_path / "agora.db"
    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22620436")

    repo_1 = RepositorioMediosSQLite(ruta, _RelojFijo(HOY))
    repo_1.guardar(ref, "tit_1", "com_1")
    del repo_1

    repo_2 = RepositorioMediosSQLite(ruta, _RelojFijo(HOY))
    assert repo_2.vivos("tit_1", Ambiente.SANDBOX) == [ref]


# -- multi-comercio: vinculado_con / comercio_de ---------------------------- #


def test_vinculado_con_encuentra_el_medio_de_ese_comercio(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    ref_a = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "src_a")
    ref_b = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "src_b")
    repo.guardar(ref_a, "tit_1", "com_a")
    repo.guardar(ref_b, "tit_1", "com_b")

    assert repo.vinculado_con("tit_1", "com_a", Ambiente.SANDBOX) == ref_a
    assert repo.vinculado_con("tit_1", "com_b", Ambiente.SANDBOX) == ref_b


def test_vinculado_con_devuelve_none_si_nunca_se_enrolo_para_ese_comercio(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    repo.guardar(MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "src_a"), "tit_1", "com_a")

    assert repo.vinculado_con("tit_1", "com_nunca_vinculado", Ambiente.SANDBOX) is None


def test_vinculado_con_ignora_un_medio_revocado(tmp_path):
    """Un medio marcado como no disponible ya no cuenta como vinculacion
    valida -- hay que volver a enrolar, no reusar una fuente apagada."""
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "src_a")
    repo.guardar(ref, "tit_1", "com_a")
    repo.marcar_estado(ref, "VOIDED")

    assert repo.vinculado_con("tit_1", "com_a", Ambiente.SANDBOX) is None


def test_vinculado_con_el_mas_reciente_si_hay_varios_del_mismo_comercio(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    viejo = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "src_viejo")
    nuevo = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "src_nuevo")
    repo.guardar(viejo, "tit_1", "com_1")
    repo.guardar(nuevo, "tit_1", "com_1")

    assert repo.vinculado_con("tit_1", "com_1", Ambiente.SANDBOX) == nuevo


def test_comercio_de_devuelve_el_comercio_con_el_que_se_enrolo(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    ref = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "22620436")
    repo.guardar(ref, "tit_1", "com_1")

    assert repo.comercio_de(ref) == "com_1"


def test_comercio_de_devuelve_none_si_el_medio_no_esta_registrado(tmp_path):
    repo = RepositorioMediosSQLite(tmp_path / "agora.db", _RelojFijo(HOY))
    ajeno = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "nunca-existio")

    assert repo.comercio_de(ajeno) is None


def test_migracion_agrega_comercio_id_a_una_base_de_antes_de_multi_comercio(tmp_path):
    """`esquema.py:_migrar_columnas_nuevas`: una base armada antes del 1 de
    septiembre de 2026 no tiene `medio_de_pago.comercio_id` -- `CREATE TABLE
    IF NOT EXISTS` no le agrega la columna a una tabla que ya existia. Esta
    prueba arma esa base "vieja" a mano (sin pasar por `esquema.asegurar`,
    que ya trae la columna) y confirma que abrir una conexion normal
    (`abrir_conexion`, que llama a `asegurar` en cada apertura) la
    migra sola, sin perder las filas que ya estaban."""
    ruta = tmp_path / "agora_vieja.db"
    con_vieja = sqlite3.connect(str(ruta))
    con_vieja.execute(
        "CREATE TABLE medio_de_pago ("
        "proveedor TEXT NOT NULL, ambiente TEXT NOT NULL, id_externo TEXT NOT NULL, "
        "titular_id TEXT NOT NULL, estado TEXT NOT NULL, creado_en TEXT, "
        "PRIMARY KEY (proveedor, ambiente, id_externo))"
    )
    con_vieja.execute(
        "INSERT INTO medio_de_pago (proveedor, ambiente, id_externo, titular_id, estado) "
        "VALUES ('wompi', 'sandbox', 'src_de_antes', 'tit_1', 'AVAILABLE')"
    )
    con_vieja.commit()
    con_vieja.close()

    con = abrir_conexion(ruta)  # dispara la migracion
    con.close()

    repo = RepositorioMediosSQLite(ruta, _RelojFijo(HOY))
    ref_vieja = MedioDePagoRef(Proveedor.WOMPI, Ambiente.SANDBOX, "src_de_antes")
    # La fila vieja sigue viva -- la migracion no la perdio.
    assert repo.vivos("tit_1", Ambiente.SANDBOX) == [ref_vieja]
    # Pero no tiene comercio registrado: `comercio_de` no inventa uno, y
    # `vinculado_con` nunca la va a encontrar -- correcto, porque no hay
    # forma de saber con que comercio se creo de verdad.
    assert repo.comercio_de(ref_vieja) is None
    assert repo.vinculado_con("tit_1", "com_cualquiera", Ambiente.SANDBOX) is None
