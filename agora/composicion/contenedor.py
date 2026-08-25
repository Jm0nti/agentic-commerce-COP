"""El composition root: el unico sitio que arma `EjecutarIntencion` con
adaptadores de verdad.

Todo lo demas de `agora/` recibe sus dependencias por constructor y no sabe
como se construyeron -- ese es el punto de que existan los puertos. Aqui es
donde se decide, entre otras cosas, la pregunta que le faltaba a la etapa 2
para estar completa: que pasarela usar.

`docs/arquitectura-v2.md`, tabla de la seccion 2: `composicion/` puede
importar todo; nadie puede importar a `composicion/`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..adaptadores.pasarelas.simulada import AdaptadorSimulado, GuionSimulado
from ..adaptadores.pasarelas.wompi import AdaptadorWompi
from ..adaptadores.persistencia.memoria import (
    LibroDeConsumoEnMemoria,
    RepositorioMandatosEnMemoria,
    RepositorioMediosEnMemoria,
)
from ..adaptadores.persistencia.sqlite import (
    LibroDeConsumoSQLite,
    RepositorioMandatosSQLite,
    RepositorioMediosSQLite,
)
from ..adaptadores.sistema import (
    BitacoraJsonl,
    GeneradorIdsUuid,
    RelojDelSistema,
    VerificadorEd25519,
)
from ..aplicacion.ejecutar_intencion import EjecutarIntencion
from ..dominio.mandato.modelo import Verificador
from ..dominio.pago.topes import TopesDuros
from ..puertos.pasarela import PasarelaDePagos
from ..puertos.repositorios import LibroDeConsumo, RepositorioMandatos, RepositorioMedios
from ..puertos.sistema import Bitacora, GeneradorIds, Reloj
from .configuracion import ConfiguracionAgora


@dataclass(frozen=True)
class Contenedor:
    """Todo lo que un punto de entrada (`entradas/`, etapa 5) va a necesitar.

    Se expone como un solo objeto, no como variables sueltas, para que
    agregar una dependencia nueva no obligue a tocar la firma de cada punto
    de entrada que llama a `construir`.
    """

    config: ConfiguracionAgora
    ejecutar_intencion: EjecutarIntencion
    mandatos: RepositorioMandatos
    medios: RepositorioMedios
    consumo: LibroDeConsumo
    pasarela: PasarelaDePagos
    reloj: Reloj
    ids: GeneradorIds
    bitacora: Bitacora
    verificador: Verificador


def construir(
    config: ConfiguracionAgora, guion_simulado: GuionSimulado | None = None
) -> Contenedor:
    """Arma el contenedor a partir de una `ConfiguracionAgora` ya leida.

    `guion_simulado` solo tiene efecto si `config.pasarela == "simulada"`:
    existe para que una demo o una prueba puedan forzar un desenlace concreto
    (por ejemplo, para mostrar el rechazo por antifraude a voluntad) sin
    tocar variables de entorno.

    Persistencia: `config.persistencia` decide entre memoria (pruebas y
    `pasarela="simulada"`) y SQLite (etapa 3: reserva/confirmacion atomica
    que sobrevive un reinicio). `ConfiguracionAgora.__post_init__` ya rechaza
    la combinacion `pasarela="wompi"` + `ambiente=produccion` +
    `persistencia="memoria"` antes de que `construir` se llame -- ver el
    docstring de `LibroDeConsumoEnMemoria` para el porque.
    """
    reloj = RelojDelSistema()
    ids = GeneradorIdsUuid()
    bitacora = BitacoraJsonl(config.bitacora_path, reloj)
    verificador = VerificadorEd25519()

    mandatos: RepositorioMandatos
    medios: RepositorioMedios
    consumo: LibroDeConsumo
    if config.persistencia == "sqlite":
        mandatos = RepositorioMandatosSQLite(config.sqlite_path)
        medios = RepositorioMediosSQLite(config.sqlite_path, reloj)
        consumo = LibroDeConsumoSQLite(config.sqlite_path, reloj, ids)
    else:
        mandatos = RepositorioMandatosEnMemoria()
        medios = RepositorioMediosEnMemoria()
        consumo = LibroDeConsumoEnMemoria(reloj, ids)
    topes = TopesDuros()

    pasarela: PasarelaDePagos
    if config.pasarela == "wompi":
        assert config.wompi is not None  # ConfiguracionAgora.__post_init__ ya lo exige
        pasarela = AdaptadorWompi(config.wompi)
    else:
        pasarela = AdaptadorSimulado(ids, config.ambiente, guion_simulado)

    ejecutar_intencion = EjecutarIntencion(
        mandatos=mandatos,
        consumo=consumo,
        pasarela=pasarela,
        topes=topes,
        reloj=reloj,
        bitacora=bitacora,
        verificador=verificador,
        ambiente=config.ambiente,
        correo_pagador=config.correo_pagador,
        datos_pagador=config.datos_pagador,
    )

    return Contenedor(
        config=config,
        ejecutar_intencion=ejecutar_intencion,
        mandatos=mandatos,
        medios=medios,
        consumo=consumo,
        pasarela=pasarela,
        reloj=reloj,
        ids=ids,
        bitacora=bitacora,
        verificador=verificador,
    )
