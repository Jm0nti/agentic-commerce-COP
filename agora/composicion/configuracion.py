"""Lectura del entorno. El unico lugar de `agora/` autorizado a hacerlo.

`docs/analisis-codigo.md` (hallazgo 5): hoy `os.environ` se lee dentro de
`ClienteWompi.__init__` (`boveda/nucleo.py:124-126`), lo que hace imposible
tener dos configuraciones en el mismo proceso y obliga a las pruebas a usar
`monkeypatch.setenv`. Aqui se lee una vez, en el composition root, y circula
despues como objetos inmutables.

Variables reconocidas (ver tambien `docs/variables-de-entorno.md`, que documenta
las de Wompi):

    AGORA_AMBIENTE      sandbox | produccion     (default: sandbox)
    AGORA_PASARELA      simulada | wompi         (default: simulada)
    AGORA_BITACORA      ruta del .jsonl propio de agora/ (default: agora_datos/recibos.jsonl)
    AGORA_PERSISTENCIA  memoria | sqlite         (default: memoria)
    AGORA_SQLITE_PATH   ruta del archivo SQLite (default: agora_datos/agora.db).
        Solo se lee si AGORA_PERSISTENCIA=sqlite.

    AGORA_WOMPI_COMERCIOS
        Multi-comercio (1 de septiembre de 2026): ruta a un JSON con las
        credenciales de CADA comercio real de Wompi, indexado por el mismo
        `comercio_id` que usa el catalogo (`agora/adaptadores/catalogo/
        semilla/datos/catalogo.json`). Solo se lee si AGORA_PASARELA=wompi.
        Default: agora_datos/secretos/comercios_wompi.json (ya en
        `.gitignore`, igual que el resto de `agora_datos/secretos/`) --
        el puente remoto no deja escribir archivos que empiecen por `.env`,
        asi que un JSON aparte, no variables `WOMPI_*` sueltas, es la unica
        forma practica de guardar credenciales de MAS de un comercio.

        Forma del archivo:

            {
              "com_xxxxxxxxxxxx": {
                "public_key": "pub_test_...",
                "private_key": "prv_test_...",
                "integrity_secret": "test_integrity_...",
                "events_secret": "test_events_..."
              },
              "com_yyyyyyyyyyyy": { ... }
            }

        Cada entrada se valida igual que antes (`ConfiguracionWompi.
        __post_init__`: faltan credenciales, o el prefijo de la llave
        publica no coincide con AGORA_AMBIENTE). Un comercio del catalogo
        que no tenga entrada aca no puede cobrar contra Wompi --
        `SelectorDePasarela.para(ese_comercio_id)` levanta
        `ComercioSinCredencialesWompi` en el momento de usarlo, no al
        arrancar (agregar un comercio nuevo al catalogo no exige reiniciar
        con TODAS las credenciales ya resueltas).

        La URL que cada comercio real tiene que registrar en su propio
        dashboard de Wompi (seccion Eventos) NO vive en este archivo -- se
        arma sola a partir del `comercio_id`: ver el docstring de
        `entradas/webhooks/wompi.py`.

    AGORA_CLASIFICADOR  hibrido | reglas | apagado   (default: hibrido)
        Migracion a agentes, etapa 1 (`docs/etapa-1-agentes-clasificador-de-
        intencion.md`): como decide el agente la intencion de cada mensaje
        antes de ejecutar el turno.
          hibrido  reglas deterministicas primero; si se abstienen, una
                   llamada extra a DeepSeek para clasificar (con historial).
          reglas   solo reglas; lo que no resuelven va por la ruta de
                   respaldo (las seis herramientas, como antes). Sin costo
                   extra de API.
          apagado  sin clasificador: el agente de la etapa 7 tal cual. Es el
                   interruptor para una demo si el enrutamiento molesta.
        Solo tiene efecto si hay DEEPSEEK_API_KEY (sin ella no hay agente).

    PAGADOR_EMAIL / PAGADOR_NOMBRE / PAGADOR_TELEFONO / PAGADOR_DOCUMENTO / PAGADOR_TIPO_DOC
        Igual que `boveda/nucleo.py:perfil_pagador`. Importan de verdad: un
        cobro sin `customer_data` es el perfil que el antifraude de Wompi lee
        como fraude (`docs/hallazgo-afe.md`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ..adaptadores.pasarelas.wompi.config import ConfiguracionWompi
from ..adaptadores.pasarelas.wompi.config import ConfiguracionInvalida as ConfiguracionWompiInvalida
from ..dominio.pago.modelo import Ambiente

RAIZ_REPO = Path(__file__).resolve().parent.parent.parent
BITACORA_POR_DEFECTO = RAIZ_REPO / "agora_datos" / "recibos.jsonl"
SQLITE_POR_DEFECTO = RAIZ_REPO / "agora_datos" / "agora.db"
COMERCIOS_WOMPI_POR_DEFECTO = RAIZ_REPO / "agora_datos" / "secretos" / "comercios_wompi.json"

# `deepseek-chat` de nuevo aca, no importado de `adaptadores/llm/deepseek/
# config.py`: `composicion/` no deberia depender de la forma interna de un
# adaptador solo para copiar un default.
DEEPSEEK_MODELO_POR_DEFECTO = "deepseek-chat"

# A proposito NO en un dominio reservado (a diferencia del viejo default de
# `boveda/nucleo.py:perfil_pagador`, `boveda+poc@example.com`): ese fue el
# correo que produjo el rechazo real por antifraude (`docs/hallazgo-afe.md`).
# Un default que reproduce esa senal sin que nadie lo pida haria que la
# pasarela simulada declinara por defecto y confundiria una primera corrida.
# Para reproducir el hallazgo a proposito, use un correo en `example.com`
# (ver `adaptadores/pasarelas/simulada/guion.py`).
CORREO_POR_DEFECTO = "demo@agora.local"

MODOS_CLASIFICADOR = ("hibrido", "reglas", "apagado")
CLASIFICADOR_POR_DEFECTO = "hibrido"


class ConfiguracionInvalida(ValueError):
    pass


@dataclass(frozen=True)
class ConfiguracionAgora:
    ambiente: Ambiente
    pasarela: str  # "simulada" | "wompi"
    correo_pagador: str
    datos_pagador: dict[str, str] = field(default_factory=dict)
    bitacora_path: Path = BITACORA_POR_DEFECTO
    # Multi-comercio: registro de credenciales por comercio_id, no una
    # unica `ConfiguracionWompi`. Vacio cuando `pasarela == "simulada"` (no
    # hace falta credenciales de nadie para la demo sin dinero real).
    wompi: dict[str, ConfiguracionWompi] = field(default_factory=dict)
    persistencia: str = "memoria"  # "memoria" | "sqlite"
    sqlite_path: Path = SQLITE_POR_DEFECTO
    # Vacio = sin agente de chat disponible (`entradas/cli/` sigue sirviendo
    # para enrolar/revocar/emitir/pagar a mano). A diferencia de las demas
    # variables de este archivo, esta SI puede quedar vacia sin que
    # `leer_configuracion` la rechace: el resto de la app (mandatos, cobros,
    # catalogo) no depende de que haya una llave de DeepSeek.
    deepseek_llave_api: str = ""
    deepseek_modelo: str = DEEPSEEK_MODELO_POR_DEFECTO
    # Migracion a agentes, etapa 1 -- ver AGORA_CLASIFICADOR en el docstring.
    clasificador_intencion: str = CLASIFICADOR_POR_DEFECTO

    def __post_init__(self) -> None:
        if self.clasificador_intencion not in MODOS_CLASIFICADOR:
            raise ConfiguracionInvalida(
                f"AGORA_CLASIFICADOR='{self.clasificador_intencion}' invalido: use "
                + " | ".join(f"'{m}'" for m in MODOS_CLASIFICADOR)
            )
        if self.pasarela not in ("simulada", "wompi"):
            raise ConfiguracionInvalida(
                f"AGORA_PASARELA='{self.pasarela}' invalido: use 'simulada' o 'wompi'"
            )
        if self.pasarela == "wompi" and not self.wompi:
            raise ConfiguracionInvalida(
                "AGORA_PASARELA=wompi exige al menos un comercio con "
                "credenciales en el registro (AGORA_WOMPI_COMERCIOS, "
                "default agora_datos/secretos/comercios_wompi.json)"
            )
        if self.persistencia not in ("memoria", "sqlite"):
            raise ConfiguracionInvalida(
                f"AGORA_PERSISTENCIA='{self.persistencia}' invalido: use 'memoria' o 'sqlite'"
            )
        if (
            self.pasarela == "wompi"
            and self.ambiente is Ambiente.PRODUCCION
            and self.persistencia == "memoria"
        ):
            # `LibroDeConsumoEnMemoria` pierde el consumo acumulado si el
            # proceso reinicia -- un mandato que se creia agotado vuelve a
            # estar fresco. Contra dinero real (wompi + produccion) eso no es
            # aceptable (docs/etapa-2-completa.md, "Decision importante").
            # Se aplica al PROCESO completo, no comercio por comercio: los N
            # comercios reales de un mismo proceso comparten la misma
            # persistencia (`composicion/contenedor.py` arma un solo
            # `LibroDeConsumo`), asi que si CUALQUIERA de ellos cobra contra
            # produccion, todos necesitan sqlite. No es un guardarrail que
            # se pueda saltar con una bandera: quien necesite reproducir ese
            # estado lo hace explicitamente instanciando los adaptadores en
            # memoria a mano, no a traves de `leer_configuracion`.
            raise ConfiguracionInvalida(
                "AGORA_PASARELA=wompi en AGORA_AMBIENTE=produccion exige "
                "AGORA_PERSISTENCIA=sqlite: la persistencia en memoria no "
                "sobrevive un reinicio y permitiria reusar un mandato agotado"
            )


def _cargar_registro_wompi(ruta: Path, ambiente: Ambiente) -> dict[str, ConfiguracionWompi]:
    """Lee el JSON de credenciales por comercio. Cada entrada se traduce a
    una `ConfiguracionWompi` propia -- multiples comercios en el mismo
    proceso es justo lo que ese tipo ya soporta desde la etapa 2 (leer el
    entorno UNA vez, circular como objeto inmutable despues, sin que
    `ClienteWompi` vuelva a tocar `os.environ`)."""
    if not ruta.exists():
        raise ConfiguracionInvalida(
            f"AGORA_PASARELA=wompi pero no existe el registro de credenciales "
            f"'{ruta}' -- cree el archivo (ver el docstring de este modulo) "
            "o apunte AGORA_WOMPI_COMERCIOS a otro."
        )
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfiguracionInvalida(f"'{ruta}' no es JSON valido: {exc}") from exc
    if not isinstance(crudo, dict) or not crudo:
        raise ConfiguracionInvalida(
            f"'{ruta}' tiene que ser un objeto JSON no vacio, comercio_id -> credenciales"
        )

    registro: dict[str, ConfiguracionWompi] = {}
    for comercio_id, entrada in crudo.items():
        if not isinstance(entrada, dict):
            raise ConfiguracionInvalida(
                f"'{ruta}': la entrada de '{comercio_id}' tiene que ser un objeto JSON"
            )
        try:
            registro[comercio_id] = ConfiguracionWompi(
                ambiente=ambiente,
                llave_publica=entrada.get("public_key", ""),
                llave_privada=entrada.get("private_key", ""),
                secreto_integridad=entrada.get("integrity_secret", ""),
                secreto_eventos=entrada.get("events_secret", ""),
            )
        except ConfiguracionWompiInvalida as exc:
            raise ConfiguracionInvalida(f"comercio '{comercio_id}' en '{ruta}': {exc}") from exc
    return registro


def leer_configuracion(entorno: Mapping[str, str]) -> ConfiguracionAgora:
    """Construye la configuracion a partir de un mapping tipo `os.environ`.

    Recibe el mapping por parametro (en vez de leer `os.environ` adentro)
    para que quede claro que esta funcion es pura frente a lo que se le pasa,
    y para que una prueba pueda armar un entorno de mentiras con un `dict`
    comun sin `monkeypatch`. Quien orquesta el arranque real (un futuro
    `entradas/cli/__main__.py`) es quien de verdad lee `os.environ` y se lo
    pasa aqui.
    """
    ambiente = Ambiente(entorno.get("AGORA_AMBIENTE", "sandbox"))
    pasarela = entorno.get("AGORA_PASARELA", "simulada")
    correo = entorno.get("PAGADOR_EMAIL", CORREO_POR_DEFECTO)

    campos_pagador = {
        "full_name": entorno.get("PAGADOR_NOMBRE", ""),
        "phone_number": entorno.get("PAGADOR_TELEFONO", ""),
        "legal_id": entorno.get("PAGADOR_DOCUMENTO", ""),
        "legal_id_type": entorno.get("PAGADOR_TIPO_DOC", "CC"),
    }
    datos_pagador = {k: v for k, v in campos_pagador.items() if v}
    if "legal_id" not in datos_pagador:
        datos_pagador.pop("legal_id_type", None)

    bitacora = Path(entorno["AGORA_BITACORA"]) if "AGORA_BITACORA" in entorno else BITACORA_POR_DEFECTO
    persistencia = entorno.get("AGORA_PERSISTENCIA", "memoria")
    sqlite_path = (
        Path(entorno["AGORA_SQLITE_PATH"]) if "AGORA_SQLITE_PATH" in entorno else SQLITE_POR_DEFECTO
    )
    deepseek_llave_api = entorno.get("DEEPSEEK_API_KEY", "")
    deepseek_modelo = entorno.get("DEEPSEEK_MODELO", DEEPSEEK_MODELO_POR_DEFECTO)
    clasificador_intencion = entorno.get("AGORA_CLASIFICADOR", CLASIFICADOR_POR_DEFECTO)

    wompi: dict[str, ConfiguracionWompi] = {}
    if pasarela == "wompi":
        ruta_comercios = (
            Path(entorno["AGORA_WOMPI_COMERCIOS"])
            if "AGORA_WOMPI_COMERCIOS" in entorno
            else COMERCIOS_WOMPI_POR_DEFECTO
        )
        wompi = _cargar_registro_wompi(ruta_comercios, ambiente)

    return ConfiguracionAgora(
        ambiente=ambiente,
        pasarela=pasarela,
        correo_pagador=correo,
        datos_pagador=datos_pagador,
        bitacora_path=bitacora,
        wompi=wompi,
        persistencia=persistencia,
        sqlite_path=sqlite_path,
        deepseek_llave_api=deepseek_llave_api,
        deepseek_modelo=deepseek_modelo,
        clasificador_intencion=clasificador_intencion,
    )
