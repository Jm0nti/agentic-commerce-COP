"""El composition root: el unico sitio que arma `EjecutarIntencion` con
adaptadores de verdad.

Todo lo demas de `agora/` recibe sus dependencias por constructor y no sabe
como se construyeron -- ese es el punto de que existan los puertos. Aqui es
donde se decide, entre otras cosas, la pregunta que le faltaba a la etapa 2
para estar completa: que pasarela usar.

`docs/arquitectura-v2.md`, tabla de la seccion 2: `composicion/` puede
importar todo; nadie puede importar a `composicion/`.

MULTI-COMERCIO (1 de septiembre de 2026)
-----------------------------------------
Antes se armaba UNA `PasarelaDePagos` por proceso. Ahora se arma un
`SelectorDePasarela` (`RegistroDePasarelas`): con `AGORA_PASARELA=wompi`,
UN `AdaptadorWompi` por cada comercio de `config.wompi` (cada uno con sus
propias credenciales -- HTTP y verificacion de checksum de eventos
completamente separados entre comercios, ni un secreto se mezcla con el de
otro); con `AGORA_PASARELA=simulada` (el default), un unico `AdaptadorSimulado`
que resuelve para cualquier `comercio_id` -- no hace falta credenciales por
comercio para una demo sin dinero real. Ver `docs/viabilidad-multi-comercio-
wompi.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..adaptadores.catalogo.semilla import RepositorioCatalogoSemilla
from ..adaptadores.llm.deepseek import AdaptadorDeepSeek, ConfiguracionDeepSeek
from ..adaptadores.pasarelas.registro import RegistroDePasarelas
from ..adaptadores.pasarelas.simulada import AdaptadorSimulado, GuionSimulado
from ..adaptadores.pasarelas.wompi import AdaptadorWompi
from ..adaptadores.persistencia.memoria import (
    LibroDeConsumoEnMemoria,
    RegistroDeEstadosEnMemoria,
    RepositorioCarritosEnMemoria,
    RepositorioMandatosEnMemoria,
    RepositorioMediosEnMemoria,
    RepositorioPropuestasEnMemoria,
)
from ..adaptadores.persistencia.sqlite import (
    LibroDeConsumoSQLite,
    RegistroDeEstadosSQLite,
    RepositorioCarritosSQLite,
    RepositorioMandatosSQLite,
    RepositorioMediosSQLite,
    RepositorioPropuestasSQLite,
)
from ..adaptadores.sistema import (
    BitacoraJsonl,
    GeneradorIdsUuid,
    RelojDelSistema,
    VerificadorEd25519,
    cargar_o_generar_firmante,
)
from ..aplicacion.conciliar_evento import ConciliarEvento
from ..aplicacion.consultar_estado import ConsultarEstado
from ..aplicacion.ejecutar_intencion import EjecutarIntencion
from ..aplicacion.emitir_mandato import EmitirMandato
from ..aplicacion.enrolar_medio import (
    ConfirmarEnrolamiento,
    ConsultarEnrolamiento,
    EnrolarMedio,
    IniciarEnrolamiento,
)
from ..aplicacion.navegar_catalogo import NavegarCatalogo
from ..aplicacion.revocar_medio import RevocarMedio
from ..dominio.mandato.modelo import Verificador
from ..dominio.pago.topes import TopesDuros
from ..puertos.catalogo import RepositorioCatalogo
from ..puertos.firma import Firmante
from ..puertos.modelo_lenguaje import ModeloDeLenguaje
from ..puertos.pasarela import SelectorDePasarela
from ..puertos.repositorios import (
    LibroDeConsumo,
    RegistroDeEstados,
    RepositorioCarritos,
    RepositorioMandatos,
    RepositorioMedios,
    RepositorioPropuestas,
)
from ..puertos.sistema import Bitacora, GeneradorIds, Reloj
from .configuracion import ConfiguracionAgora


@dataclass(frozen=True)
class Contenedor:
    """Todo lo que un punto de entrada (`entradas/`, etapa 4 en adelante) va
    a necesitar -- `entradas/webhooks/wompi.py` solo usa `conciliar_evento`.

    Se expone como un solo objeto, no como variables sueltas, para que
    agregar una dependencia nueva no obligue a tocar la firma de cada punto
    de entrada que llama a `construir`.

    `catalogo` sigue el mismo precedente que `RepositorioMediosSQLite` en la
    etapa 3: el adaptador esta listo y probado antes de que exista el caso de
    uso que lo llame (`aplicacion/navegar_catalogo.py`, etapa 5) -- no hay
    ninguna dependencia entre construir el catalogo y construir el resto del
    contenedor, asi que no hay motivo para esperar.
    """

    config: ConfiguracionAgora
    ejecutar_intencion: EjecutarIntencion
    conciliar_evento: ConciliarEvento
    mandatos: RepositorioMandatos
    medios: RepositorioMedios
    consumo: LibroDeConsumo
    # Multi-comercio: ya no una `PasarelaDePagos` fija -- ver el docstring
    # del modulo. `scripts/demo_etapa_4.py` y cualquier otro punto de
    # entrada que necesite "la pasarela" ahora pide `selector_pasarela.
    # para(comercio_id)`.
    selector_pasarela: SelectorDePasarela
    catalogo: RepositorioCatalogo
    reloj: Reloj
    ids: GeneradorIds
    bitacora: Bitacora
    verificador: Verificador
    # -- etapa 5 -------------------------------------------------------- #
    carritos: RepositorioCarritos
    # -- etapa 6 -------------------------------------------------------- #
    propuestas: RepositorioPropuestas
    estados: RegistroDeEstados
    firmante: Firmante
    navegar_catalogo: NavegarCatalogo
    emitir_mandato: EmitirMandato
    enrolar_medio: EnrolarMedio
    # -- etapa 8 (web): los mismos tres pasos que EnrolarMedio compone,
    # sueltos para que entradas/api/ pueda sondear el push de Nequi sin
    # bloquear una peticion HTTP hasta 5 minutos (ver el docstring de
    # aplicacion/enrolar_medio.py).
    iniciar_enrolamiento: IniciarEnrolamiento
    consultar_enrolamiento: ConsultarEnrolamiento
    confirmar_enrolamiento: ConfirmarEnrolamiento
    revocar_medio: RevocarMedio
    consultar_estado: ConsultarEstado
    # `None` cuando no hay DEEPSEEK_API_KEY -- ver `ConfiguracionAgora.
    # deepseek_llave_api`. El resto del contenedor (mandatos, cobros,
    # catalogo, enrolamiento) no depende de que esto exista.
    modelo_lenguaje: ModeloDeLenguaje | None


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

    # Multi-comercio: un `AdaptadorWompi` por cada entrada del registro de
    # credenciales (`config.wompi`), o un unico `AdaptadorSimulado` que
    # resuelve para cualquier comercio. Nunca las dos cosas a la vez --
    # `ConfiguracionAgora.__post_init__` ya exige `config.wompi` no vacio
    # cuando `pasarela == "wompi"`, y `leer_configuracion` nunca lo llena
    # cuando `pasarela == "simulada"`.
    selector_pasarela: SelectorDePasarela
    if config.pasarela == "wompi":
        pasarelas_por_comercio = {
            comercio_id: AdaptadorWompi(cfg_wompi)
            for comercio_id, cfg_wompi in config.wompi.items()
        }
        selector_pasarela = RegistroDePasarelas(pasarelas_por_comercio)
    else:
        unica = AdaptadorSimulado(ids, config.ambiente, guion_simulado)
        selector_pasarela = RegistroDePasarelas({}, por_defecto=unica)

    # Etapa 6 (segunda parte): sqlite si `retomar` puede correr en otra
    # terminal que la del `chat` -- que, con `agente/herramientas.py`
    # negandole `retomar` al agente a proposito, es SIEMPRE el caso. Ver el
    # comentario de la tabla `estado_intencion` en `esquema.py`.
    estados: RegistroDeEstados
    if config.persistencia == "sqlite":
        estados = RegistroDeEstadosSQLite(config.sqlite_path)
    else:
        estados = RegistroDeEstadosEnMemoria()
    ejecutar_intencion = EjecutarIntencion(
        mandatos=mandatos,
        consumo=consumo,
        selector_pasarela=selector_pasarela,
        topes=topes,
        reloj=reloj,
        bitacora=bitacora,
        verificador=verificador,
        ambiente=config.ambiente,
        correo_pagador=config.correo_pagador,
        datos_pagador=config.datos_pagador,
        estados=estados,
    )
    conciliar_evento = ConciliarEvento(
        consumo=consumo, selector_pasarela=selector_pasarela, bitacora=bitacora, estados=estados,
    )
    catalogo = RepositorioCatalogoSemilla()

    # -- etapa 5 ------------------------------------------------------------ #
    carritos: RepositorioCarritos
    propuestas: RepositorioPropuestas
    if config.persistencia == "sqlite":
        # Mismo motivo que `mandatos`/`medios`/`consumo`: `entradas/cli/`
        # trata "armar y firmar" y "pagar" como comandos separados, cada uno
        # su propio proceso -- sin esto, el carrito nunca sobreviviria entre
        # los dos.
        carritos = RepositorioCarritosSQLite(config.sqlite_path)
        # Etapa 6: mismo argumento, un nivel mas adentro -- la propuesta
        # tiene que sobrevivir entre el proceso que arma el carrito (el
        # chat) y el que firma (`entradas/cli/firmar`, en otra terminal).
        propuestas = RepositorioPropuestasSQLite(config.sqlite_path)
        # `estados` ya se armo mas arriba, antes de `ejecutar_intencion` --
        # por eso no aparece aca, aunque logicamente es la misma decision.
    else:
        carritos = RepositorioCarritosEnMemoria()
        propuestas = RepositorioPropuestasEnMemoria()
    # "Igual que v1: llave en disco" -- si no existe, se genera aca mismo, la
    # primera vez que se arma un Contenedor. `agente/` nunca ve esta llamada
    # (test_fronteras.py lo verifica): la firma solo llega a `emitir_mandato`,
    # ya armada.
    firmante = cargar_o_generar_firmante(config.llave_firma_sk, config.llave_firma_pk)

    navegar_catalogo = NavegarCatalogo(
        catalogo=catalogo, carritos=carritos, ids=ids, propuestas=propuestas,
    )
    emitir_mandato = EmitirMandato(
        carritos=carritos, propuestas=propuestas, medios=medios, mandatos=mandatos,
        firmante=firmante, ids=ids, reloj=reloj, bitacora=bitacora, ambiente=config.ambiente,
    )
    enrolar_medio = EnrolarMedio(
        selector_pasarela=selector_pasarela, medios=medios, bitacora=bitacora, ambiente=config.ambiente,
    )
    # Mismas dependencias que enrolar_medio, pero sueltas -- entradas/api/
    # las necesita para sondear el push de Nequi desde el navegador sin
    # bloquear una peticion HTTP (ver el docstring de aplicacion/
    # enrolar_medio.py).
    iniciar_enrolamiento = IniciarEnrolamiento(selector_pasarela, config.ambiente)
    consultar_enrolamiento = ConsultarEnrolamiento(selector_pasarela)
    confirmar_enrolamiento = ConfirmarEnrolamiento(selector_pasarela, medios, bitacora)
    revocar_medio = RevocarMedio(selector_pasarela=selector_pasarela, medios=medios, bitacora=bitacora)
    consultar_estado = ConsultarEstado(estados=estados)

    modelo_lenguaje: ModeloDeLenguaje | None = None
    if config.deepseek_llave_api:
        modelo_lenguaje = AdaptadorDeepSeek(
            ConfiguracionDeepSeek(
                llave_api=config.deepseek_llave_api, modelo=config.deepseek_modelo,
            )
        )

    return Contenedor(
        config=config,
        ejecutar_intencion=ejecutar_intencion,
        conciliar_evento=conciliar_evento,
        mandatos=mandatos,
        medios=medios,
        consumo=consumo,
        selector_pasarela=selector_pasarela,
        catalogo=catalogo,
        reloj=reloj,
        ids=ids,
        bitacora=bitacora,
        verificador=verificador,
        carritos=carritos,
        propuestas=propuestas,
        estados=estados,
        firmante=firmante,
        navegar_catalogo=navegar_catalogo,
        emitir_mandato=emitir_mandato,
        enrolar_medio=enrolar_medio,
        iniciar_enrolamiento=iniciar_enrolamiento,
        consultar_enrolamiento=consultar_enrolamiento,
        confirmar_enrolamiento=confirmar_enrolamiento,
        revocar_medio=revocar_medio,
        consultar_estado=consultar_estado,
        modelo_lenguaje=modelo_lenguaje,
    )
