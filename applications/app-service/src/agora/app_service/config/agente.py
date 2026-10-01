"""El unico lugar que conoce tanto `aplicacion/` como `agente/`: arma las
seis funciones que `agente/herramientas.py:construir_herramientas` convierte
en `Herramienta`, y con eso arma el `Agente` (`agente/conversacion.py`)
contra el `ModeloDeLenguaje` real que trae el `Contenedor` -- y, desde la
etapa 1 de la migracion a agentes, con el clasificador de intencion que pida
`AGORA_CLASIFICADOR` (`construir_clasificador`, al final de este archivo).

Desde la etapa 3, ademas, es el unico lugar que conoce el adaptador de
LangGraph: `envolver_en_grafo` decide, segun `AGORA_ORQUESTACION`, si lo que
sale de aca es el `Agente` de siempre o un `AgenteEnGrafo` que corre el mismo
turno por un grafo. Quien recibe el agente (`entradas/api/`, la CLI) no
distingue uno del otro: los dos tienen `iniciar`/`turno`.

POR QUE ESTAS FUNCIONES DE UNION VIVEN ACA Y NO EN `agente/`
----------------------------------------------------------------
`agente/herramientas.py` no puede importar `aplicacion/` sin arriesgar la
frontera que `test_fronteras.py` verifica (`docs/arquitectura-v2.md`,
seccion 2: `agente/` solo importa `dominio/` -tipos- y `puertos/`).
`composicion/` si puede -- es el unico paquete al que se le permite importar
todo. Cada funcion de aca cierra sobre un caso de uso real (`NavegarCatalogoUseCase`,
`EjecutarIntencionUseCase`, `ConsultarEstadoUseCase`) y devuelve solo dicts/listas de
dicts, para que `agente/conversacion.py` nunca tenga que saber serializar un
`Producto` o una `Intencion` -- eso es trabajo de traduccion, no de
orquestacion de turnos.

`pagar()` no recibe `titular_id`: `mandato_id` y `carrito_id` ya identifican
todo lo que hace falta para cobrar (`EjecutarIntencionUseCase.obtener` resuelve el
mandato por su cuenta), asi que agregar un tercer parametro que nadie usa
seria la abstraccion especulativa que `arquitectura-v2.md` (seccion 9) pide
evitar.
"""

from __future__ import annotations

from typing import Any

from ...usecase.agente.clasificacion import (
    ClasificadorConModelo,
    ClasificadorEnCadena,
    ClasificadorPorReglas,
)
from ...model.agente.contexto import ProveedorDeContexto
from ...usecase.agente.contexto_documental import ContextoDocumental
from ...usecase.agente.conversacion import Agente
from ...usecase.agente.grafo import AgenteEnGrafo
from ...usecase.agente.herramientas import construir_herramientas
from ...model.agente.intencion import ClasificadorDeIntencion
from ...usecase.navegar_catalogo.navegar_catalogo_use_case import ItemPedido
from ...model.catalogo.modelo import Comercio, Producto
from ...model.catalogo.gateways.busqueda_productos import FiltrosDeProducto
from ...model.agente.gateways.modelo_lenguaje import ModeloDeLenguaje
from ...model.agente.gateways.orquestacion import CompiladorDeGrafos
from .configuracion import MODOS_ORQUESTACION, ConfiguracionInvalida
from .contenedor import Contenedor


def construir_agente(contenedor: Contenedor) -> Agente | AgenteEnGrafo | None:
    """`None` si `contenedor.modelo_lenguaje` no se armo (falta
    `DEEPSEEK_API_KEY`) -- `entradas/cli/` decide que hacer con eso: avisar
    y seguir sirviendo los comandos que no dependen de un modelo de
    lenguaje (enrolar, emitir, pagar/revocar a mano)."""
    if contenedor.modelo_lenguaje is None:
        return None

    def buscar_comercios(consulta: str = "") -> list[dict[str, Any]]:
        return [
            _comercio_a_dict(c)
            for c in contenedor.navegar_catalogo.buscar_comercios(consulta)
        ]

    def buscar_productos(
        comercio_id: str,
        consulta: str = "",
        solo_disponibles: bool = False,
        precio_min_cop: int | None = None,
        precio_max_cop: int | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        # Etapa 4: los filtros duros llegan como argumentos del modelo y se
        # arman aca, que es la frontera de traduccion. `FiltrosDeProducto`
        # los valida con `ValueError` -- y `Agente._ejecutar` solo traduce
        # `ErrorDeDominio` y `TypeError`, asi que un rango invertido que
        # invente el modelo tumbaria el turno entero. Se atrapa aca y vuelve
        # como resultado leible: el modelo corrige y el turno sigue.
        try:
            filtros = FiltrosDeProducto(
                solo_disponibles=bool(solo_disponibles),
                precio_min_cop=None if precio_min_cop is None else int(precio_min_cop),
                precio_max_cop=None if precio_max_cop is None else int(precio_max_cop),
            )
        except (ValueError, TypeError) as exc:
            return {"error": f"filtros invalidos para buscar_productos: {exc}"}
        return [
            _producto_a_dict(p)
            for p in contenedor.navegar_catalogo.buscar_productos(
                comercio_id, consulta, filtros=filtros,
            )
        ]

    def ver_producto(producto_id: str) -> dict[str, Any]:
        return _producto_a_dict(contenedor.navegar_catalogo.ver_producto(producto_id))

    def armar_carrito(
        comercio_id: str, items: list[dict[str, Any]], justificacion: str = ""
    ) -> dict[str, Any]:
        pedidos = [
            ItemPedido(producto_id=i["producto_id"], cantidad=int(i.get("cantidad", 1)))
            for i in items
        ]
        carrito, propuesta = contenedor.navegar_catalogo.armar_carrito(
            comercio_id, pedidos, justificacion=justificacion,
        )
        return {
            "carrito_id": carrito.carrito_id,
            "total_cop": carrito.total.pesos,
            "propuesta": {
                "propuesta_id": propuesta.propuesta_id,
                "carrito_id": propuesta.carrito_id,
                "comercio_id": propuesta.comercio_id,
                "monto_max_cop": propuesta.monto_max.pesos,
                "usos_max": propuesta.usos_max,
                "vigencia_minutos": propuesta.vigencia_minutos,
                "justificacion": propuesta.justificacion,
            },
            "nota": "Propuesta SIN AUTORIZAR. La persona la autoriza ella misma, "
            "fuera de esta charla, corriendo en su propia terminal: "
            f"'python -m agora cli firmar {propuesta.propuesta_id} "
            "<su_titular_id>' (su titular_id es el que uso al enrolar su medio "
            "de pago). Ese comando le muestra el mandato_id ya firmado -- recien "
            "con ese mandato_id se puede llamar a pagar().",
        }

    def pagar(mandato_id: str, carrito_id: str) -> dict[str, Any]:
        # Comercio, monto y `carrito_hash` salen del carrito guardado, nunca
        # de un argumento del modelo (ver `aplicacion/pagar_carrito.py`).
        recibo = contenedor.pagar_carrito(mandato_id, carrito_id)
        intencion = recibo.intencion
        resultado: dict[str, Any] = {
            "intencion_id": intencion.intencion_id,
            # `mandato_id`/`carrito_id` de vuelta en el resultado (no solo
            # dentro de la "nota"): etapa 7 (`entradas/api/sesiones.py`) los
            # necesita para armar el evento `confirmacion_pendiente` sin
            # tener que parsear texto libre -- lo mismo que ya vale para
            # "propuesta" en `armar_carrito`, un poco mas arriba.
            "mandato_id": mandato_id,
            "carrito_id": carrito_id,
            "ejecutado": recibo.ejecutado,
            "motivo": recibo.motivo,
            "esperando_confirmacion": recibo.esperando_confirmacion,
        }
        if recibo.esperando_confirmacion:
            # Igual que `armar_carrito` con `firmar` (etapa 6): el comando
            # EXACTO, no una descripcion. `retomar` nunca es herramienta del
            # agente -- resolver un CONFIRMAR es decision humana, igual que
            # firmar (`agente/herramientas.py`) -- asi que quien lo corre es
            # siempre la persona, en otra terminal.
            resultado["nota"] = (
                "Pago SIN CONFIRMAR: quedo esperando confirmacion humana. La "
                "persona la resuelve ELLA MISMA, en su propia terminal, corriendo: "
                f"'python -m agora cli retomar {intencion.intencion_id} "
                f"{mandato_id} {carrito_id}'. Con AGORA_PERSISTENCIA=sqlite, en "
                "cuanto lo corra podes volver a llamar a consultar_estado y ya "
                "va a reflejar el resultado -- no hace falta que ella misma te "
                "avise, pero si te dice que ya confirmo, consulta el estado antes "
                "de responder."
            )
        return resultado

    def consultar_estado(intencion_id: str) -> dict[str, Any]:
        estado = contenedor.consultar_estado(intencion_id)
        return {
            "intencion_id": estado.intencion_id,
            "estado": estado.estado,
            "detalle": estado.detalle,
        }

    herramientas = construir_herramientas(
        buscar_comercios=buscar_comercios,
        buscar_productos=buscar_productos,
        ver_producto=ver_producto,
        armar_carrito=armar_carrito,
        pagar=pagar,
        consultar_estado=consultar_estado,
    )
    agente = Agente(
        modelo=contenedor.modelo_lenguaje,
        herramientas=herramientas,
        clasificador=construir_clasificador(
            contenedor.config.clasificador_intencion, contenedor.modelo_lenguaje,
        ),
        contextos=construir_contextos(contenedor),
        bitacora=contenedor.bitacora_trazas,
    )
    return envolver_en_grafo(agente, contenedor.config.orquestacion)


def envolver_en_grafo(agente: Agente, modo: str) -> Agente | AgenteEnGrafo:
    """Migracion a agentes, etapa 3. `modo` sale de `AGORA_ORQUESTACION`
    (`composicion/configuracion.py`, que ya lo valido).

    El agente de las etapas 1-2 sigue siendo el mismo objeto en los dos
    modos: `grafo` lo envuelve, no lo reemplaza."""
    if modo == "directo":
        return agente
    if modo == "grafo":
        return AgenteEnGrafo(agente, _compilador_de_grafos())
    # `ConfiguracionAgora.__post_init__` ya lo impide; esto es por si alguien
    # llama directo sin pasar por la configuracion (mismo criterio que
    # `construir_clasificador`).
    raise ValueError(
        f"modo de orquestacion desconocido: '{modo}' (use "
        + " | ".join(f"'{m}'" for m in MODOS_ORQUESTACION)
        + ")"
    )


def _importar_compilador_langgraph() -> type[CompiladorDeGrafos]:
    """El import del adaptador, aislado en una funcion a proposito -- mismo
    patron que `contenedor.py:_construir_buscador_documental` con LangChain.

    Dos razones: `AGORA_ORQUESTACION=directo` no tiene por que exigir
    `langgraph` instalado (un venv que todavia no corrio
    `pip install -r requirements.txt` levanta igual), y una prueba puede
    simular "langgraph no esta" sin desinstalar nada."""
    from ...driven_adapters.orquestacion_langgraph import CompiladorLangGraph

    return CompiladorLangGraph


def _compilador_de_grafos() -> CompiladorDeGrafos:
    try:
        compilador = _importar_compilador_langgraph()
    except ImportError as exc:
        raise ConfiguracionInvalida(
            "AGORA_ORQUESTACION=grafo necesita el paquete 'langgraph', que no "
            "esta instalado en este entorno. Instalalo con "
            "'pip install -r requirements.txt' (o 'pip install langgraph'), o "
            "corre el agente sin grafo con AGORA_ORQUESTACION=directo."
        ) from exc
    return compilador()


def construir_contextos(contenedor: Contenedor) -> dict[str, ProveedorDeContexto]:
    """Migracion a agentes, etapa 2: el contexto que inyecta cada nodo. Hoy
    solo soporte, y solo si hay buscador documental (OPENAI_API_KEY). Sin
    buscador, soporte contesta como en la etapa 1: con su instruccion y sin
    documentacion."""
    if contenedor.buscador_documental is None:
        return {}
    return {"soporte": ContextoDocumental(contenedor.buscador_documental)}


def construir_clasificador(
    modo: str, modelo: ModeloDeLenguaje
) -> ClasificadorDeIntencion | None:
    """Migracion a agentes, etapa 1. `modo` sale de `AGORA_CLASIFICADOR`
    (`composicion/configuracion.py`, que ya lo valido). El orden de la
    cadena es la decision de costo del documento: reglas gratis primero, el
    modelo solo cuando las reglas se abstienen."""
    if modo == "apagado":
        return None
    if modo == "reglas":
        return ClasificadorPorReglas()
    if modo == "hibrido":
        return ClasificadorEnCadena(ClasificadorPorReglas(), ClasificadorConModelo(modelo))
    # `ConfiguracionAgora.__post_init__` ya lo impide; esto es por si alguien
    # llama directo sin pasar por la configuracion.
    raise ValueError(f"modo de clasificador desconocido: '{modo}'")


def _comercio_a_dict(c: Comercio) -> dict[str, Any]:
    return {
        "comercio_id": c.comercio_id,
        "nombre": c.nombre,
        "categoria": c.categoria,
        "descripcion": c.descripcion,
    }


def _producto_a_dict(p: Producto) -> dict[str, Any]:
    return {
        "producto_id": p.producto_id,
        "comercio_id": p.comercio_id,
        "nombre": p.nombre,
        "descripcion": p.descripcion,
        "precio_cop": p.precio.pesos,
        "disponibilidad": p.disponibilidad.value,
    }
