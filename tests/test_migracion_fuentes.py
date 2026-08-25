"""`scripts/migrar_fuentes_a_sqlite.py`: dry-run por defecto, backup antes de
escribir, y la promesa central -- que NO toca `estado.json` (mandatos v1),
solo se prueba por omision: ningun test de este archivo le pasa ese archivo
al script, y `filas_a_migrar` solo conoce las columnas de `medio_de_pago`.

Corre el script real con `subprocess`, no importandolo, porque es un
`if __name__ == "__main__"` pensado para invocarse por linea de comandos --
probarlo asi es lo mas cerca de como Juan lo va a correr de verdad.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ_REPO / "scripts" / "migrar_fuentes_a_sqlite.py"

FUENTES_DE_PRUEBA = {
    "sandbox": [
        {
            "payment_source_id": 111,
            "tipo": "NEQUI",
            "modo": "sandbox",
            "referencia_publica": "300****789",
            "email": "titular@correo.com",
            "estado": "AVAILABLE",
            "creada_en": "2026-06-01T10:00:00+00:00",
            "token": "tok_sandbox",
        },
    ],
    "produccion": [
        {
            "payment_source_id": 222,
            "tipo": "NEQUI",
            "modo": "produccion",
            "referencia_publica": "300****789",
            "email": "titular@correo.com",
            "estado": "VOIDED",
            "creada_en": "2026-07-01T10:00:00+00:00",
            "token": "tok_produccion",
        },
    ],
}


def _correr(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=30,
    )


def _escribir_fuentes(tmp_path: Path, datos: dict) -> Path:
    ruta = tmp_path / "fuentes.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


def test_dry_run_no_escribe_nada(tmp_path):
    fuentes = _escribir_fuentes(tmp_path, FUENTES_DE_PRUEBA)
    destino = tmp_path / "agora.db"

    r = _correr("--fuentes", str(fuentes), "--destino", str(destino), "--titular", "tit_1")

    assert r.returncode == 0, r.stderr
    assert not destino.exists()
    assert "Dry-run" in r.stdout
    assert "111" in r.stdout and "222" in r.stdout


def test_aplicar_escribe_las_filas_correctas(tmp_path):
    fuentes = _escribir_fuentes(tmp_path, FUENTES_DE_PRUEBA)
    destino = tmp_path / "agora.db"

    r = _correr(
        "--fuentes", str(fuentes), "--destino", str(destino),
        "--titular", "tit_1", "--aplicar",
    )
    assert r.returncode == 0, r.stderr
    assert destino.exists()

    con = sqlite3.connect(str(destino))
    filas = con.execute(
        "SELECT proveedor, ambiente, id_externo, titular_id, estado FROM medio_de_pago "
        "ORDER BY ambiente"
    ).fetchall()
    con.close()

    assert filas == [
        ("wompi", "produccion", "222", "tit_1", "VOIDED"),
        ("wompi", "sandbox", "111", "tit_1", "AVAILABLE"),
    ]


def test_aplicar_dos_veces_no_duplica_y_deja_backup(tmp_path):
    fuentes = _escribir_fuentes(tmp_path, FUENTES_DE_PRUEBA)
    destino = tmp_path / "agora.db"

    _correr("--fuentes", str(fuentes), "--destino", str(destino), "--titular", "tit_1", "--aplicar")
    r2 = _correr("--fuentes", str(fuentes), "--destino", str(destino), "--titular", "tit_1", "--aplicar")

    assert r2.returncode == 0, r2.stderr
    respaldos = list(tmp_path.glob("agora.db.bak-*"))
    assert len(respaldos) == 1

    con = sqlite3.connect(str(destino))
    total = con.execute("SELECT COUNT(*) FROM medio_de_pago").fetchone()[0]
    con.close()
    assert total == 2  # no duplico: INSERT OR REPLACE sobre la misma llave


def test_no_migra_mandatos_v1_el_script_no_conoce_esa_forma(tmp_path):
    """`estado.json` (mandatos v1) tiene una forma completamente distinta a
    `fuentes.json`. Si alguien intentara apuntar `--fuentes` a un
    `estado.json` de verdad, el script debe rechazarlo por forma invalida en
    vez de migrar filas basura a `medio_de_pago` -- nunca produce una fila de
    tipo "mandato"."""
    fuentes = _escribir_fuentes(tmp_path, {"sandbox": [{"algo": "que no es una fuente"}]})
    destino = tmp_path / "agora.db"

    r = _correr("--fuentes", str(fuentes), "--destino", str(destino), "--titular", "tit_1")
    assert r.returncode != 0
    assert not destino.exists()


def test_modo_desconocido_se_rechaza(tmp_path):
    fuentes = _escribir_fuentes(tmp_path, {"modo_raro": []})
    destino = tmp_path / "agora.db"

    r = _correr("--fuentes", str(fuentes), "--destino", str(destino), "--titular", "tit_1")
    assert r.returncode != 0
    assert "modo_raro" in r.stderr or "modo_raro" in r.stdout


def test_fuentes_inexistente_se_rechaza(tmp_path):
    r = _correr(
        "--fuentes", str(tmp_path / "no_existe.json"),
        "--destino", str(tmp_path / "agora.db"),
        "--titular", "tit_1",
    )
    assert r.returncode != 0


def test_titular_es_obligatorio(tmp_path):
    fuentes = _escribir_fuentes(tmp_path, FUENTES_DE_PRUEBA)
    r = _correr("--fuentes", str(fuentes), "--destino", str(tmp_path / "agora.db"))
    assert r.returncode != 0
    assert "titular" in r.stderr.lower()


def test_fuentes_json_vacio_no_falla_y_no_escribe(tmp_path):
    fuentes = _escribir_fuentes(tmp_path, {"sandbox": [], "produccion": []})
    destino = tmp_path / "agora.db"

    r = _correr(
        "--fuentes", str(fuentes), "--destino", str(destino),
        "--titular", "tit_1", "--aplicar",
    )
    assert r.returncode == 0, r.stderr
    assert not destino.exists()
