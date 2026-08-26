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

    WOMPI_PUBLIC_KEY / WOMPI_PRIVATE_KEY / WOMPI_INTEGRITY_SECRET / WOMPI_EVENTS_SECRET
        Solo se leen si AGORA_PASARELA=wompi. Son las mismas variables que
        usa `boveda/nucleo.py` -- no hay una segunda copia de las
        credenciales para la casa nueva.

    PAGADOR_EMAIL / PAGADOR_NOMBRE / PAGADOR_TELEFONO / PAGADOR_DOCUMENTO / PAGADOR_TIPO_DOC
        Igual que `boveda/nucleo.py:perfil_pagador`. Importan de verdad: un
        cobro sin `customer_data` es el perfil que el antifraude de Wompi lee
        como fraude (`docs/hallazgo-afe.md`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ..adaptadores.pasarelas.wompi.config import ConfiguracionWompi
from ..adaptadores.pasarelas.wompi.config import ConfiguracionInvalida as ConfiguracionWompiInvalida
from ..dominio.pago.modelo import Ambiente

RAIZ_REPO = Path(__file__).resolve().parent.parent.parent
BITACORA_POR_DEFECTO = RAIZ_REPO / "agora_datos" / "recibos.jsonl"
SQLITE_POR_DEFECTO = RAIZ_REPO / "agora_datos" / "agora.db"

# Etapa 5: la llave de firma del titular, en disco, "igual que v1"
# (`boveda/secretos/firma.sk`/`firma.pk`). Sin cifrar -- ver el docstring de
# `adaptadores/sistema/firma_ed25519.py:cargar_o_generar_firmante`.
LLAVE_FIRMA_SK_POR_DEFECTO = RAIZ_REPO / "agora_datos" / "secretos" / "firma.sk"
LLAVE_FIRMA_PK_POR_DEFECTO = RAIZ_REPO / "agora_datos" / "secretos" / "firma.pk"

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


class ConfiguracionInvalida(ValueError):
    pass


@dataclass(frozen=True)
class ConfiguracionAgora:
    ambiente: Ambiente
    pasarela: str  # "simulada" | "wompi"
    correo_pagador: str
    datos_pagador: dict[str, str] = field(default_factory=dict)
    bitacora_path: Path = BITACORA_POR_DEFECTO
    wompi: ConfiguracionWompi | None = None
    persistencia: str = "memoria"  # "memoria" | "sqlite"
    sqlite_path: Path = SQLITE_POR_DEFECTO
    llave_firma_sk: Path = LLAVE_FIRMA_SK_POR_DEFECTO
    llave_firma_pk: Path = LLAVE_FIRMA_PK_POR_DEFECTO
    # Vacio = sin agente de chat disponible (`entradas/cli/` sigue sirviendo
    # para enrolar/revocar/emitir/pagar a mano). A diferencia de las demas
    # variables de este archivo, esta SI puede quedar vacia sin que
    # `leer_configuracion` la rechace: el resto de la app (mandatos, cobros,
    # catalogo) no depende de que haya una llave de DeepSeek.
    deepseek_llave_api: str = ""
    deepseek_modelo: str = DEEPSEEK_MODELO_POR_DEFECTO

    def __post_init__(self) -> None:
        if self.pasarela not in ("simulada", "wompi"):
            raise ConfiguracionInvalida(
                f"AGORA_PASARELA='{self.pasarela}' invalido: use 'simulada' o 'wompi'"
            )
        if self.pasarela == "wompi" and self.wompi is None:
            raise ConfiguracionInvalida(
                "AGORA_PASARELA=wompi exige las credenciales de Wompi "
                "(WOMPI_PUBLIC_KEY / WOMPI_PRIVATE_KEY / WOMPI_INTEGRITY_SECRET)"
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
            # No es un guardarrail que se pueda saltar con una bandera: quien
            # necesite reproducir ese estado lo hace explicitamente
            # instanciando los adaptadores en memoria a mano, no a traves de
            # `leer_configuracion`.
            raise ConfiguracionInvalida(
                "AGORA_PASARELA=wompi en AGORA_AMBIENTE=produccion exige "
                "AGORA_PERSISTENCIA=sqlite: la persistencia en memoria no "
                "sobrevive un reinicio y permitiria reusar un mandato agotado"
            )


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
    llave_firma_sk = (
        Path(entorno["AGORA_LLAVE_FIRMA_SK"])
        if "AGORA_LLAVE_FIRMA_SK" in entorno
        else LLAVE_FIRMA_SK_POR_DEFECTO
    )
    llave_firma_pk = (
        Path(entorno["AGORA_LLAVE_FIRMA_PK"])
        if "AGORA_LLAVE_FIRMA_PK" in entorno
        else LLAVE_FIRMA_PK_POR_DEFECTO
    )
    deepseek_llave_api = entorno.get("DEEPSEEK_API_KEY", "")
    deepseek_modelo = entorno.get("DEEPSEEK_MODELO", DEEPSEEK_MODELO_POR_DEFECTO)

    wompi = None
    if pasarela == "wompi":
        try:
            wompi = ConfiguracionWompi(
                ambiente=ambiente,
                llave_publica=entorno.get("WOMPI_PUBLIC_KEY", ""),
                llave_privada=entorno.get("WOMPI_PRIVATE_KEY", ""),
                secreto_integridad=entorno.get("WOMPI_INTEGRITY_SECRET", ""),
                secreto_eventos=entorno.get("WOMPI_EVENTS_SECRET", ""),
            )
        except ConfiguracionWompiInvalida as exc:
            # Se traduce a la `ConfiguracionInvalida` de este modulo para que
            # quien llame a `leer_configuracion` tenga un solo tipo de error
            # que atrapar, sin tener que conocer `adaptadores/pasarelas/
            # wompi/config.py`. Dos excepciones con el mismo nombre
            # (`ConfiguracionInvalida`) en modulos distintos, sin relacion de
            # herencia, es una trampa: un `except ConfiguracionInvalida`
            # aqui NO atraparia la de wompi si no se tradujera.
            raise ConfiguracionInvalida(str(exc)) from exc

    return ConfiguracionAgora(
        ambiente=ambiente,
        pasarela=pasarela,
        correo_pagador=correo,
        datos_pagador=datos_pagador,
        bitacora_path=bitacora,
        wompi=wompi,
        persistencia=persistencia,
        sqlite_path=sqlite_path,
        llave_firma_sk=llave_firma_sk,
        llave_firma_pk=llave_firma_pk,
        deepseek_llave_api=deepseek_llave_api,
        deepseek_modelo=deepseek_modelo,
    )
