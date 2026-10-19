"""El composition root: el unico sitio que arma `EjecutarIntencionUseCase` con
adaptadores de verdad.

Todo lo demas de `agora/` recibe sus dependencias por constructor y no sabe
como se construyeron -- ese es el punto de que existan los puertos. Aqui es
donde se decide, entre otras cosas, la pregunta que le faltaba a la etapa 2
para estar completa: que pasarela usar.

`docs/arquitectura.md`, tabla de la seccion 2: `app_service/config/` puede
importar todo; nadie puede importar a `app_service/config/`.

MULTI-COMERCIO (1 de septiembre de 2026)
-----------------------------------------
Antes se armaba UNA `PasarelaDePagos` por proceso. Ahora se arma un
`SelectorDePasarela` (`RegistroDePasarelas`): con `AGORA_PASARELA=wompi`,
UN `AdaptadorWompi` por cada comercio de `config.wompi` (cada uno con sus
propias credenciales -- HTTP y verificacion de checksum de eventos
completamente separados entre comercios, ni un secreto se mezcla con el de
otro); con `AGORA_PASARELA=simulada` (el default), un unico `AdaptadorSimulado`
que resuelve para cualquier `comercio_id` -- no hace falta credenciales por
comercio para una demo sin dinero real. Ver
`docs/utils/viabilidad-multi-comercio-wompi.md`.

MULTI-USUARIO (4 de septiembre de 2026)
------------------------------------------
Antes se armaba UNA sola llave de firma por proceso (`cargar_o_generar_
firmante`, sobre un archivo en disco) y `EmitirMandatoUseCase` la recibia fija por
constructor -- cualquier titular firmaba con esa misma llave. Ahora se arma
un `SelectorDeFirmante` (`RegistroDeFirmantes`) que resuelve la llave de
CADA titular contra `RepositorioLlaves`, guardada junto con su `Usuario`
(`RepositorioUsuarios`) en el momento en que `app_service/crear_usuario.py` lo
crea (`usecase/registrar_usuario/registrar_usuario_use_case.py:RegistrarUsuarioUseCase`). No hay ruta HTTP de
auto-registro: `entry_points/api_rest/app.py` solo expone `/auth/iniciar-sesion` y
`/auth/cerrar-sesion` sobre usuarios que ya existen. La CLI (`entry_points/
cli/`) sigue sin pedir login -- alcanza con pasar un `titular_id` que ya
tenga usuario creado; si no lo tiene, `SinLlaveDeFirma` lo dice claro en
vez de fallar en silencio o generar una llave nueva sobre la marcha.
"""

from __future__ import annotations

from pathlib import Path

from dataclasses import dataclass

from ...driven_adapters.catalogo_semilla import RepositorioCatalogoSemilla
from ...driven_adapters.llm_deepseek import AdaptadorDeepSeek, ConfiguracionDeepSeek
from ...driven_adapters.selector_pasarelas.registro import RegistroDePasarelas
from ...driven_adapters.pasarela_simulada import AdaptadorSimulado, GuionSimulado
from ...driven_adapters.pasarela_wompi import AdaptadorWompi
from ...driven_adapters.persistencia_memoria import (
    LibroDeConsumoEnMemoria,
    RegistroDeEstadosEnMemoria,
    RepositorioCarritosEnMemoria,
    RepositorioLlavesEnMemoria,
    RepositorioMandatosEnMemoria,
    RepositorioMediosEnMemoria,
    RepositorioPropuestasEnMemoria,
    RepositorioUsuariosEnMemoria,
)
from ...driven_adapters.persistencia_sqlite import (
    LibroDeConsumoSQLite,
    RegistroDeEstadosSQLite,
    RepositorioCarritosSQLite,
    RepositorioLlavesSQLite,
    RepositorioMandatosSQLite,
    RepositorioMediosSQLite,
    RepositorioPropuestasSQLite,
    RepositorioUsuariosSQLite,
)
from ...driven_adapters.bitacora_jsonl.bitacora_jsonl import BitacoraJsonl
from ...driven_adapters.firma_ed25519.firma_ed25519 import (
    GeneradorDeLlavesEd25519,
    VerificadorEd25519,
)
from ...driven_adapters.sistema import GeneradorIdsUuid, RelojDelSistema
from ...driven_adapters.hasher_pbkdf2.hasher_pbkdf2 import HasherPBKDF2
from ...driven_adapters.firma_ed25519.registro_firmantes import RegistroDeFirmantes
from ...usecase.iniciar_sesion.iniciar_sesion_use_case import IniciarSesionUseCase
from ...usecase.registrar_usuario.registrar_usuario_use_case import RegistrarUsuarioUseCase
from ...usecase.conciliar_evento.conciliar_evento_use_case import ConciliarEventoUseCase
from ...usecase.consultar_estado.consultar_estado_use_case import ConsultarEstadoUseCase
from ...usecase.ejecutar_intencion.ejecutar_intencion_use_case import EjecutarIntencionUseCase
from ...usecase.emitir_mandato.emitir_mandato_use_case import EmitirMandatoUseCase
from ...usecase.confirmar_enrolamiento.confirmar_enrolamiento_use_case import (
    ConfirmarEnrolamientoUseCase,
)
from ...usecase.consultar_enrolamiento.consultar_enrolamiento_use_case import (
    ConsultarEnrolamientoUseCase,
)
from ...usecase.enrolar_medio.enrolar_medio_use_case import EnrolarMedioUseCase
from ...usecase.iniciar_enrolamiento.iniciar_enrolamiento_use_case import IniciarEnrolamientoUseCase
from ...usecase.listar_mandatos.listar_mandatos_use_case import ListarMandatosUseCase
from ...usecase.listar_medios_vivos.listar_medios_vivos_use_case import ListarMediosVivosUseCase
from ...usecase.navegar_catalogo.navegar_catalogo_use_case import NavegarCatalogoUseCase
from ...usecase.pagar_carrito.pagar_carrito_use_case import PagarCarritoUseCase
from ...usecase.rechazar_propuesta.rechazar_propuesta_use_case import RechazarPropuestaUseCase
from ...usecase.revocar_medio.revocar_medio_use_case import RevocarMedioUseCase
from ...model.mandato.gateways.firma import Verificador
from ...model.pago.modelo import Ambiente
from ...model.pago.topes import TopesDuros
from ...model.catalogo.modelo import Producto
from ...model.usuario.gateways.autenticacion import HasherDeContrasenas
from ...model.catalogo.gateways.busqueda_productos import BuscadorSemanticoDeProductos
from ...model.catalogo.gateways.catalogo import RepositorioCatalogo
from ...model.mandato.gateways.firma import SelectorDeFirmante
from ...model.agente.gateways.modelo_lenguaje import ModeloDeLenguaje
from ...model.pago.gateways.pasarela import SelectorDePasarela
from ...model.agente.gateways.recuperacion import BuscadorDocumental
from ...model.mandato.gateways.repositorios import (
    LibroDeConsumo,
    RepositorioMandatos,
    RepositorioPropuestas,
)
from ...model.pago.gateways.repositorios import RegistroDeEstados, RepositorioMedios
from ...model.catalogo.gateways.repositorios import RepositorioCarritos
from ...model.usuario.gateways.repositorios import RepositorioLlaves, RepositorioUsuarios
from ...model.commons.gateways.sistema import Bitacora, GeneradorIds, Reloj
from .configuracion import RAIZ_REPO, ConfiguracionAgora


@dataclass(frozen=True)
class Contenedor:
    """Todo lo que un punto de entrada (`entry_points/`, etapa 4 en adelante) va
    a necesitar -- `entry_points/webhook_wompi/wompi.py` solo usa `conciliar_evento`.

    Se expone como un solo objeto, no como variables sueltas, para que
    agregar una dependencia nueva no obligue a tocar la firma de cada punto
    de entrada que llama a `construir`.

    `catalogo` sigue el mismo precedente que `RepositorioMediosSQLite` en la
    etapa 3: el adaptador esta listo y probado antes de que exista el caso de
    uso que lo llame (`usecase/navegar_catalogo/navegar_catalogo_use_case.py`, etapa 5) -- no hay
    ninguna dependencia entre construir el catalogo y construir el resto del
    contenedor, asi que no hay motivo para esperar.
    """

    config: ConfiguracionAgora
    ejecutar_intencion: EjecutarIntencionUseCase
    conciliar_evento: ConciliarEventoUseCase
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
    # Trazabilidad del agente: la cadena de decisiones de cada turno de chat,
    # en su propio .jsonl. Misma interfaz, otro archivo -- `recibos.jsonl` es
    # la evidencia del experimento de dinero y no se diluye.
    bitacora_trazas: Bitacora
    verificador: Verificador
    # -- etapa 5 -------------------------------------------------------- #
    carritos: RepositorioCarritos
    # -- etapa 6 -------------------------------------------------------- #
    propuestas: RepositorioPropuestas
    estados: RegistroDeEstados
    # Multi-usuario: ya no una llave fija -- ver el docstring del modulo.
    # `usuarios`/`llaves` son los repositorios crudos (los usa `scripts/
    # crear_usuario.py` indirecto, a traves de `registrar_usuario`);
    # `registrar_usuario`/`iniciar_sesion` son los casos de uso completos.
    usuarios: RepositorioUsuarios
    llaves: RepositorioLlaves
    selector_firmante: SelectorDeFirmante
    registrar_usuario: RegistrarUsuarioUseCase
    iniciar_sesion: IniciarSesionUseCase
    navegar_catalogo: NavegarCatalogoUseCase
    emitir_mandato: EmitirMandatoUseCase
    # Etapa 10: el contrapunto de `emitir_mandato` cuando el humano rechaza
    # la propuesta en vez de firmarla -- ver el docstring de
    # `usecase/rechazar_propuesta/rechazar_propuesta_use_case.py`.
    rechazar_propuesta: RechazarPropuestaUseCase
    enrolar_medio: EnrolarMedioUseCase
    # -- etapa 8 (web): los mismos tres pasos que EnrolarMedioUseCase compone,
    # sueltos para que entry_points/api_rest/ pueda sondear el push de Nequi sin
    # bloquear una peticion HTTP hasta 5 minutos (ver el docstring de
    # usecase/enrolar_medio/enrolar_medio_use_case.py).
    iniciar_enrolamiento: IniciarEnrolamientoUseCase
    consultar_enrolamiento: ConsultarEnrolamientoUseCase
    confirmar_enrolamiento: ConfirmarEnrolamientoUseCase
    revocar_medio: RevocarMedioUseCase
    consultar_estado: ConsultarEstadoUseCase
    # -- Fase 1 del refactor a la Clean Architecture de Bancolombia: lo que
    # `entry_points/` antes leia directo de los repositorios de arriba.
    pagar_carrito: PagarCarritoUseCase
    listar_medios_vivos: ListarMediosVivosUseCase
    listar_mandatos: ListarMandatosUseCase
    # `None` cuando no hay DEEPSEEK_API_KEY -- ver `ConfiguracionAgora.
    # deepseek_llave_api`. El resto del contenedor (mandatos, cobros,
    # catalogo, enrolamiento) no depende de que esto exista.
    modelo_lenguaje: ModeloDeLenguaje | None
    # Migracion a agentes, etapa 2. `None` sin OPENAI_API_KEY -- el nodo de
    # soporte contesta sin documentacion. Con llave, se arma sin tocar la red:
    # el corpus se lee y se fragmenta ya, pero se embebe recien en la primera
    # busqueda (ver `BuscadorDocumentalLangChain`). Con default para que las
    # pruebas que arman un `Contenedor` a mano no tengan que conocerlo.
    buscador_documental: BuscadorDocumental | None = None
    # Migracion a agentes, etapa 4. `None` sin OPENAI_API_KEY -- el catalogo
    # se navega con el match estructurado de siempre. Misma llave y mismo
    # proveedor de embeddings que el buscador documental, pero OTRO indice:
    # la decision 1 pide dos indices que nunca se mezclan.
    buscador_semantico_productos: BuscadorSemanticoDeProductos | None = None

    @property
    def ambiente(self) -> Ambiente:
        """Lo unico de `config` que necesitan los puntos de entrada (armar un
        `MedioDePagoRef`, mostrarlo): se lo pasan como valor, sin recibir la
        configuracion entera."""
        return self.config.ambiente

    @property
    def trazas_path(self) -> Path:
        """Para `cli trazas`, que solo lee ese archivo."""
        return self.config.trazas_path


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
    # Segunda bitacora, mismo adaptador, archivo distinto: las trazas de chat
    # no se mezclan con la evidencia de dinero (ver `configuracion.py`).
    bitacora_trazas = BitacoraJsonl(config.trazas_path, reloj)
    verificador = VerificadorEd25519()

    mandatos: RepositorioMandatos
    medios: RepositorioMedios
    consumo: LibroDeConsumo
    usuarios: RepositorioUsuarios
    llaves: RepositorioLlaves
    if config.persistencia == "sqlite":
        mandatos = RepositorioMandatosSQLite(config.sqlite_path)
        medios = RepositorioMediosSQLite(config.sqlite_path, reloj)
        consumo = LibroDeConsumoSQLite(config.sqlite_path, reloj, ids)
        usuarios = RepositorioUsuariosSQLite(config.sqlite_path)
        llaves = RepositorioLlavesSQLite(config.sqlite_path)
    else:
        mandatos = RepositorioMandatosEnMemoria()
        medios = RepositorioMediosEnMemoria()
        consumo = LibroDeConsumoEnMemoria(reloj, ids)
        usuarios = RepositorioUsuariosEnMemoria()
        llaves = RepositorioLlavesEnMemoria()
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
    # terminal que la del `chat` -- que, con `usecase/agente/herramientas.py`
    # negandole `retomar` al agente a proposito, es SIEMPRE el caso. Ver el
    # comentario de la tabla `estado_intencion` en `esquema.py`.
    estados: RegistroDeEstados
    if config.persistencia == "sqlite":
        estados = RegistroDeEstadosSQLite(config.sqlite_path)
    else:
        estados = RegistroDeEstadosEnMemoria()
    ejecutar_intencion = EjecutarIntencionUseCase(
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
    conciliar_evento = ConciliarEventoUseCase(
        consumo=consumo, selector_pasarela=selector_pasarela, bitacora=bitacora, estados=estados,
    )
    catalogo = RepositorioCatalogoSemilla()

    # -- etapa 5 ------------------------------------------------------------ #
    carritos: RepositorioCarritos
    propuestas: RepositorioPropuestas
    if config.persistencia == "sqlite":
        # Mismo motivo que `mandatos`/`medios`/`consumo`: `entry_points/cli/`
        # trata "armar y firmar" y "pagar" como comandos separados, cada uno
        # su propio proceso -- sin esto, el carrito nunca sobreviviria entre
        # los dos.
        carritos = RepositorioCarritosSQLite(config.sqlite_path)
        # Etapa 6: mismo argumento, un nivel mas adentro -- la propuesta
        # tiene que sobrevivir entre el proceso que arma el carrito (el
        # chat) y el que firma (`entry_points/cli/firmar`, en otra terminal).
        propuestas = RepositorioPropuestasSQLite(config.sqlite_path)
        # `estados` ya se armo mas arriba, antes de `ejecutar_intencion` --
        # por eso no aparece aca, aunque logicamente es la misma decision.
    else:
        carritos = RepositorioCarritosEnMemoria()
        propuestas = RepositorioPropuestasEnMemoria()
    # Multi-usuario: ya no una llave fija cargada de disco -- se resuelve
    # por titular contra `RepositorioLlaves` (`RegistroDeFirmantes`, que
    # levanta `SinLlaveDeFirma` si el titular nunca tuvo un usuario creado
    # con `app_service/crear_usuario.py`). `usecase/agente/` nunca ve nada de esto
    # (test_fronteras.py lo verifica): la firma solo llega a
    # `emitir_mandato`, ya resuelta.
    selector_firmante = RegistroDeFirmantes(llaves)
    hasher = HasherPBKDF2()
    generador_llaves = GeneradorDeLlavesEd25519()
    registrar_usuario = RegistrarUsuarioUseCase(
        usuarios=usuarios, llaves=llaves, hasher=hasher,
        generador_llaves=generador_llaves, ids=ids, reloj=reloj,
    )
    iniciar_sesion = IniciarSesionUseCase(usuarios=usuarios, hasher=hasher)

    buscador_semantico_productos = _construir_buscador_semantico_de_productos(config, catalogo)
    navegar_catalogo = NavegarCatalogoUseCase(
        catalogo=catalogo, carritos=carritos, ids=ids, propuestas=propuestas,
        semantico=buscador_semantico_productos,
    )
    emitir_mandato = EmitirMandatoUseCase(
        carritos=carritos, propuestas=propuestas, medios=medios, mandatos=mandatos,
        selector_firmante=selector_firmante, ids=ids, reloj=reloj, bitacora=bitacora,
        ambiente=config.ambiente,
    )
    rechazar_propuesta = RechazarPropuestaUseCase(propuestas=propuestas, bitacora=bitacora)
    enrolar_medio = EnrolarMedioUseCase(
        selector_pasarela=selector_pasarela, medios=medios, bitacora=bitacora, ambiente=config.ambiente,
    )
    # Mismas dependencias que enrolar_medio, pero sueltas -- entry_points/api_rest/
    # las necesita para sondear el push de Nequi desde el navegador sin
    # bloquear una peticion HTTP (ver el docstring de usecase/
    # enrolar_medio.py).
    iniciar_enrolamiento = IniciarEnrolamientoUseCase(selector_pasarela, config.ambiente)
    consultar_enrolamiento = ConsultarEnrolamientoUseCase(selector_pasarela)
    confirmar_enrolamiento = ConfirmarEnrolamientoUseCase(selector_pasarela, medios, bitacora)
    revocar_medio = RevocarMedioUseCase(selector_pasarela=selector_pasarela, medios=medios, bitacora=bitacora)
    consultar_estado = ConsultarEstadoUseCase(estados=estados)
    pagar_carrito = PagarCarritoUseCase(ejecutar=ejecutar_intencion, carritos=carritos, ids=ids)
    listar_medios_vivos = ListarMediosVivosUseCase(medios=medios, ambiente=config.ambiente)
    listar_mandatos = ListarMandatosUseCase(mandatos=mandatos, consumo=consumo, ambiente=config.ambiente)

    modelo_lenguaje: ModeloDeLenguaje | None = None
    if config.deepseek_llave_api:
        modelo_lenguaje = AdaptadorDeepSeek(
            ConfiguracionDeepSeek(
                llave_api=config.deepseek_llave_api, modelo=config.deepseek_modelo,
            )
        )

    buscador_documental = _construir_buscador_documental(config)

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
        bitacora_trazas=bitacora_trazas,
        verificador=verificador,
        carritos=carritos,
        propuestas=propuestas,
        estados=estados,
        usuarios=usuarios,
        llaves=llaves,
        selector_firmante=selector_firmante,
        registrar_usuario=registrar_usuario,
        iniciar_sesion=iniciar_sesion,
        navegar_catalogo=navegar_catalogo,
        emitir_mandato=emitir_mandato,
        rechazar_propuesta=rechazar_propuesta,
        enrolar_medio=enrolar_medio,
        iniciar_enrolamiento=iniciar_enrolamiento,
        consultar_enrolamiento=consultar_enrolamiento,
        confirmar_enrolamiento=confirmar_enrolamiento,
        revocar_medio=revocar_medio,
        consultar_estado=consultar_estado,
        pagar_carrito=pagar_carrito,
        listar_medios_vivos=listar_medios_vivos,
        listar_mandatos=listar_mandatos,
        modelo_lenguaje=modelo_lenguaje,
        buscador_documental=buscador_documental,
        buscador_semantico_productos=buscador_semantico_productos,
    )


def _todos_los_productos(catalogo: RepositorioCatalogo) -> list[Producto]:
    """Recorre el catalogo por comercio, que es la unica forma que da el
    puerto (`buscar_productos` siempre pide un `comercio_id`). No es un
    rodeo: esa forma es deliberada -- ver "TRES METODOS, NO UNO" en
    `model/catalogo/gateways/catalogo.py` -- y el catalogo simulado entra entero en memoria."""
    return [
        producto
        for comercio in catalogo.buscar_comercios()
        for producto in catalogo.buscar_productos(comercio.comercio_id)
    ]


def _construir_buscador_semantico_de_productos(
    config: ConfiguracionAgora, catalogo: RepositorioCatalogo
) -> BuscadorSemanticoDeProductos | None:
    """Migracion a agentes, etapa 4. Sin OPENAI_API_KEY, `None`.

    Sin variable de entorno propia, a proposito: no hay un caso realista en
    el que alguien quiera embeddings para la documentacion de soporte pero
    no para el catalogo -- son la misma llave, el mismo proveedor y, con un
    catalogo de decenas de productos, un costo que se mide en centavos una
    vez por arranque. Una bandera mas seria configuracion para un valor que
    nadie va a cambiar.

    El import va adentro por la misma razon que el del buscador documental:
    es la unica parte del composition root que necesita numpy y el SDK de
    OpenAI para esto, y el catalogo semantico es opcional.

    Igual que en la etapa 2, construir NO toca la red: se lee el catalogo y
    se guarda la lista, pero se embebe recien en la primera busqueda."""
    if not config.openai_llave_api:
        return None
    from ...driven_adapters.busqueda_semantica_memoria import BuscadorSemanticoEnMemoria
    from ...driven_adapters.embeddings_openai import (
        AdaptadorEmbeddingsOpenAI,
        ConfiguracionEmbeddingsOpenAI,
    )

    return BuscadorSemanticoEnMemoria(
        productos=_todos_los_productos(catalogo),
        embeddings=AdaptadorEmbeddingsOpenAI(
            ConfiguracionEmbeddingsOpenAI(
                llave_api=config.openai_llave_api, modelo=config.embeddings_modelo,
            )
        ),
    )


def _construir_buscador_documental(config: ConfiguracionAgora) -> BuscadorDocumental | None:
    """Migracion a agentes, etapa 2. Sin OPENAI_API_KEY, `None`.

    Los imports van ADENTRO de la funcion, a proposito: son la unica parte
    del composition root que depende de LangChain, y la documentacion de
    soporte es opcional. Asi, un venv que todavia no corrio
    `pip install -r requirements.txt` despues de esta etapa sigue levantando
    la app (y la suite de las etapas anteriores) mientras no configure la
    llave -- en vez de caerse entero con un `ImportError` por una funcion
    que no esta usando."""
    if not config.openai_llave_api:
        return None
    from ...driven_adapters.embeddings_openai import (
        AdaptadorEmbeddingsOpenAI,
        ConfiguracionEmbeddingsOpenAI,
    )
    from ...driven_adapters.recuperacion_langchain import (
        BuscadorDocumentalLangChain,
        cargar_markdown,
    )

    return BuscadorDocumentalLangChain(
        documentos=cargar_markdown(config.soporte_documentos_path, raiz=RAIZ_REPO),
        embeddings=AdaptadorEmbeddingsOpenAI(
            ConfiguracionEmbeddingsOpenAI(
                llave_api=config.openai_llave_api, modelo=config.embeddings_modelo,
            )
        ),
    )
