"""Lo que el refactor a la Clean Architecture de Bancolombia NO puede cambiar.

`evolucion-refactor/roadmap-clean-architecture-bancolombia.md`, Fase 0. Mover
archivos no deberia romper ninguna de estas tres cosas, y si alguna se rompe
no hay otra prueba que lo note a tiempo:

  R2  un mandato ya firmado y guardado en SQLite tiene que seguir verificando
      (la firma cubre `Mandato.canonico()`: nombres de campo, valores de enum,
      formato de `Dinero`);
  R3  el agente decide con `tipo` y `reintentable` de cada error
      (`ErrorDeDominio.to_json`), y `recibos.jsonl` los guarda: ni un nombre
      ni un `reintentable` cambian sin decidirlo;
  R4  la raiz del repo sale de `pyproject.toml`: si se cuenta mal, SQLite crea
      un `agora.db` vacio en otra carpeta y la app arranca como si nada.

Cuando el refactor mueva un modulo, se actualizan los imports de este archivo
-- nunca los valores esperados.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import agora
from agora.driven_adapters.catalogo_semilla.repositorio import (
    RUTA_POR_DEFECTO as CATALOGO_POR_DEFECTO,
)
from agora.driven_adapters.persistencia_sqlite.serializacion import fila_a_mandato, mandato_a_fila
from agora.driven_adapters.firma_ed25519.firma_ed25519 import VerificadorEd25519
from agora.composicion import configuracion
from agora.model.commons.errores import ErrorDeDominio
from agora.model.pago.modelo import Ambiente
from agora.entradas.api.app import RAIZ_ESTATICO

# -- R2: mandato dorado ------------------------------------------------------ #
# Firmado una vez (30 sep 2026) con una llave de prueba fija y guardado tal como
# lo escribe `RepositorioMandatosSQLite`. La llave privada no esta aca a
# proposito: lo que se prueba es que lo YA firmado sigue valiendo.
FILA_DORADA = (
    "mnd_dorado", "sandbox", "tit_dorado",
    "simulada", "sandbox", "src_dorado",
    "com_dorado",
    800000, "COP",
    2000000, "COP",
    2, "2026-10-01T12:00:00+00:00", "2026-09-30T12:00:00+00:00",
    bytes.fromhex("03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"),
    '["dulces", "papeleria"]',
    "c" * 64,
    2,
    bytes.fromhex(
        "39ab7024c95020155f7285cf8ee1ce85c2889c1b6c496c98b32587229d37d624"
        "0b9c09bb3039a91b9221b825a952c1edfa9579ebbc059563b7daf89e406cbc00"
    ),
)


def test_un_mandato_firmado_y_guardado_sigue_verificando() -> None:
    mandato = fila_a_mandato(FILA_DORADA)

    assert VerificadorEd25519().verifica(mandato.firma, mandato.canonico(), mandato.llave_publica)
    assert mandato_a_fila(mandato, Ambiente.SANDBOX) == FILA_DORADA


# -- R3: lo que el agente lee de cada error ---------------------------------- #
ERRORES_ESPERADOS: dict[str, bool] = {  # nombre -> reintentable
    "CarritoDesconocido": False,
    "CobroRechazado": False,
    "ComercioDesconocido": False,
    "ComercioSinCredencialesWompi": False,
    "CredencialesInvalidas": False,
    "ErrorDeAutenticacion": False,
    "ErrorDeCatalogo": False,
    "ErrorDeConsumo": False,
    "ErrorDeMandato": False,
    "ErrorDeModeloDeLenguaje": False,
    "ErrorDePasarela": False,
    "ErrorDeRecuperacion": False,
    "EstadoDesconocido": False,
    "FirmaInvalida": False,
    "LimiteExcedido": False,
    "MandatoAgotado": False,
    "MandatoDeOtroAmbiente": False,
    "MandatoDesconocido": False,
    "MandatoVencido": False,
    "MedioDePagoRevocado": False,
    "MedioNoAprobado": False,
    "MedioNoRegistrado": False,
    "ModeloNoDisponible": True,
    "NombreDeUsuarioYaExiste": False,
    "PasarelaNoDisponible": True,
    "ProductoDeOtroComercio": False,
    "ProductoDesconocido": False,
    "ProductoNoDisponible": False,
    "PropuestaDesconocida": False,
    "PropuestaInvalida": False,
    "RechazadoPorAntifraude": False,
    "RecuperacionNoDisponible": True,
    "ReservaNoEncontrada": False,
    "RespuestaDeEmbeddingsInvalida": False,
    "RespuestaModeloInvalida": False,
    "SesionInvalida": False,
    "SinLlaveDeFirma": False,
    "SinMedioDePagoVivo": False,
    "SinMedioVinculadoAlComercio": False,
    "TopeDiarioAgotado": True,
    "TopeDuroExcedido": False,
}


def _subclases(clase: type) -> list[type]:
    return [s for c in clase.__subclasses__() for s in (c, *_subclases(c))]


def test_los_errores_que_ve_el_agente_no_cambian() -> None:
    # Importar todo agora/: tras el refactor los errores pueden vivir en otros
    # modulos, y una subclase solo existe si su modulo se importo.
    # `agora.__path__`: `agora/` y cada modulo del scaffold ya migrado.
    for raiz in map(Path, agora.__path__):
        for archivo in raiz.rglob("*.py"):
            partes = ("agora", *archivo.relative_to(raiz).with_suffix("").parts)
            importlib.import_module(".".join(partes[:-1] if partes[-1] == "__init__" else partes))

    encontrados = {
        c.__name__: c.reintentable
        for c in _subclases(ErrorDeDominio)
        if c.__module__.startswith("agora.")
    }
    assert encontrados == ERRORES_ESPERADOS


# -- R4: rutas que dependen de la raiz del repo ------------------------------ #


def test_la_raiz_del_repo_es_la_carpeta_de_pyproject() -> None:
    raiz = configuracion.RAIZ_REPO

    assert (raiz / "pyproject.toml").is_file()
    assert configuracion.SQLITE_POR_DEFECTO == raiz / "agora_datos" / "agora.db"
    assert configuracion.BITACORA_POR_DEFECTO == raiz / "agora_datos" / "recibos.jsonl"
    assert configuracion.COMERCIOS_WOMPI_POR_DEFECTO == raiz / "agora_datos" / "secretos" / "comercios_wompi.json"
    assert any(configuracion.SOPORTE_DOCUMENTOS_POR_DEFECTO.glob("*.md"))


def test_los_datos_que_viajan_con_su_modulo_existen() -> None:
    assert CATALOGO_POR_DEFECTO.is_file()
    assert (RAIZ_ESTATICO / "chat.html").is_file()
