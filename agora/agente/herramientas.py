"""Lo que el agente puede hacer. Y, sobre todo, lo que no.

Este archivo es la frontera. Todo lo que no este aqui, el modelo no lo puede
llamar -- no porque se lo pidamos en el prompt, sino porque no existe en su
espacio de herramientas.

LO QUE EL AGENTE NO TIENE, Y POR QUE
------------------------------------
  firmar()            la llave del titular no esta en este proceso
  ver_medio_de_pago() maneja mandato_id opacos; nunca un payment_source_id
  enrolar/revocar()   son actos del titular, no del agente
  crear_mandato()     puede PROPONER uno. Firmarlo es del humano.

`pagar()` SI esta, y es deliberado. Quitarla haria que la PoC dejara de medir
lo que quiere medir: el punto no es que el agente no actue, es que actue solo
dentro de un limite que otro firmo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    esquema: dict[str, Any]
    ejecutar: Callable[..., Any]


CATALOGO_DE_HERRAMIENTAS = (
    "buscar_comercios",
    "buscar_productos",
    "ver_producto",
    "armar_carrito",     # devuelve una PropuestaDeMandato SIN FIRMAR
    "pagar",             # exige un mandato_id que firmo un humano
    "consultar_estado",
)

# Nombres que jamas deben aparecer como herramienta. La prueba de fronteras
# verifica que ninguna funcion expuesta los contenga.
PROHIBIDAS = (
    "firmar",
    "enrolar",
    "revocar",
    "medio_de_pago",
    "payment_source",
    "llave",
    "secreto",
    "credencial",
    # Multi-usuario (4 de septiembre de 2026): el agente tampoco puede
    # tocar nada de autenticacion -- ni la contrasena de nadie, ni la
    # sesion de login de nadie. Mismo espiritu que el resto de la lista:
    # una credencial de identidad es tan intocable para el agente como una
    # credencial de pago.
    "contrasena",
    "password",
    "sesion",
)


# --------------------------------------------------------------------------- #
# Lista blanca POR NODO (migracion a agentes, etapa 1 -- docs/arquitectura-
# agentes-langgraph.md, decision 3). La tabla de los siete agentes, dicha en
# codigo: cada nodo es dueño de un subconjunto del catalogo autorizado, y
# ninguna herramienta tiene dos dueños. Asi un nodo nuevo nunca "hereda" una
# herramienta de otro dominio por accidente: tiene que aparecer aca, en el
# mismo archivo que `PROHIBIDAS`, y pasar `validar_asignacion_por_nodo`.
#
# `orquestador`, `medios_de_pago`, `soporte` y `riesgo` NO tienen
# herramientas, a proposito:
#   - orquestador     decide a donde va el turno; no ejecuta nada.
#   - medios_de_pago  explica enrolar/revocar -- actos del titular, nunca del
#                     agente (por eso tampoco podria tener una herramienta con
#                     esos nombres: `PROHIBIDAS` ya los niega).
#   - soporte         prosa sobre como funciona el sistema. Sin acceso FISICO a
#                     nada que mueva dinero, aunque el modelo alucine una
#                     llamada (`agente/conversacion.py` la rechaza al ejecutar).
#   - riesgo          explicador del dictamen (opcional en el documento); lee
#                     el `Dictamen`, no llama herramientas. Ninguna ruta de la
#                     etapa 1 lo usa todavia -- esta en la tabla para que la
#                     tabla sea la decision 3 completa, no la mitad.
# --------------------------------------------------------------------------- #

HERRAMIENTAS_POR_NODO: dict[str, tuple[str, ...]] = {
    "orquestador": (),
    "catalogo": ("buscar_comercios", "buscar_productos", "ver_producto"),
    # Juntas a proposito (decision 5 del documento): separarlas reabre el
    # riesgo de `carrito_id` desincronizado que ya se vivio en la etapa 6
    # (`docs/etapa-6-conectar-chat-y-firma.md`).
    "carrito_pago": ("armar_carrito", "pagar"),
    "medios_de_pago": (),
    "estado": ("consultar_estado",),
    "soporte": (),
    "riesgo": (),
}

# Las herramientas que estan en el camino del dinero: `armar_carrito` produce
# la propuesta que despues se firma, `pagar` cobra. Solo el nodo de carrito y
# pago puede tenerlas -- `validar_asignacion_por_nodo` lo verifica, y
# `tests/test_agente_nodos.py` falla si algun dia soporte (o cualquier otro
# nodo) las recibe.
HERRAMIENTAS_DEL_FLUJO_DE_DINERO = ("armar_carrito", "pagar")
NODO_DUENO_DEL_FLUJO_DE_DINERO = "carrito_pago"


def _validar_nodo(nodo: str) -> None:
    if nodo not in HERRAMIENTAS_POR_NODO:
        raise RuntimeError(
            f"nodo desconocido: '{nodo}'. Un nodo nuevo se declara en "
            "HERRAMIENTAS_POR_NODO, con su lista blanca explicita."
        )


def _validar_nombre(nombre: str) -> None:
    for prohibida in PROHIBIDAS:
        if prohibida in nombre.lower():
            raise RuntimeError(
                f"la herramienta '{nombre}' contiene '{prohibida}'. "
                "El agente no puede tener acceso a credenciales ni a la firma."
            )
    if nombre not in CATALOGO_DE_HERRAMIENTAS:
        raise RuntimeError(
            f"'{nombre}' no esta en el catalogo autorizado. "
            "Agregarla es una decision de diseno, no un detalle."
        )


def validar_catalogo(herramientas: list[Herramienta], nodo: str | None = None) -> None:
    """Se corre al armar el agente, no en un test lejano.

    Un `assert` en el arranque vale mas que una convencion documentada: si
    alguien agrega una herramienta que revela credenciales, la app no levanta.

    Sin `nodo` valida el catalogo global (`PROHIBIDAS` + catalogo
    autorizado), exactamente como antes de la migracion a agentes. Con
    `nodo`, ademas exige que cada herramienta pertenezca a la lista blanca de
    ESE nodo (`HERRAMIENTAS_POR_NODO`) -- una herramienta valida en general
    pero de otro dominio se rechaza igual de fuerte que una prohibida.
    """
    if nodo is not None:
        _validar_nodo(nodo)
    for h in herramientas:
        _validar_nombre(h.nombre)
        if nodo is not None and h.nombre not in HERRAMIENTAS_POR_NODO[nodo]:
            raise RuntimeError(
                f"la herramienta '{h.nombre}' no pertenece al dominio del nodo "
                f"'{nodo}' (su lista blanca: {HERRAMIENTAS_POR_NODO[nodo] or 'ninguna'})."
            )


def validar_asignacion_por_nodo(
    tabla: dict[str, tuple[str, ...]] | None = None,
) -> None:
    """Valida la TABLA, no una lista de herramientas concreta: que cada
    herramienta asignada exista en el catalogo y no este prohibida, que
    ninguna tenga dos nodos dueños, y que el flujo de dinero viva solo en su
    nodo. `tabla` se puede pasar para probar tablas malas sin tocar la real.
    """
    tabla = HERRAMIENTAS_POR_NODO if tabla is None else tabla
    dueno: dict[str, str] = {}
    for nodo, nombres in tabla.items():
        for nombre in nombres:
            _validar_nombre(nombre)
            if nombre in dueno:
                raise RuntimeError(
                    f"'{nombre}' esta asignada a dos nodos ('{dueno[nombre]}' y "
                    f"'{nodo}'). Cada herramienta tiene un solo dominio dueño."
                )
            dueno[nombre] = nodo
            if (
                nombre in HERRAMIENTAS_DEL_FLUJO_DE_DINERO
                and nodo != NODO_DUENO_DEL_FLUJO_DE_DINERO
            ):
                raise RuntimeError(
                    f"'{nombre}' esta en el camino del dinero y solo puede ser del "
                    f"nodo '{NODO_DUENO_DEL_FLUJO_DE_DINERO}', no de '{nodo}'."
                )


def validar_nodos_con_contexto(nodos: Iterable[str]) -> None:
    """Migracion a agentes, etapa 2: que nodos pueden recibir contexto
    inyectado (`agente/contexto.py`), por ejemplo documentacion recuperada.
    Cualquier nodo declarado -- menos el dueño del flujo de dinero: prosa
    recuperada al lado de `armar_carrito`/`pagar` es la mezcla que la regla
    "ninguna cifra sale de una recuperacion" quiere evitar."""
    for nodo in nodos:
        _validar_nodo(nodo)
        if nodo == NODO_DUENO_DEL_FLUJO_DE_DINERO:
            raise RuntimeError(
                f"el nodo '{nodo}' es dueño del flujo de dinero: no puede recibir "
                "contexto recuperado. Los montos y topes salen del dominio, nunca "
                "de una busqueda."
            )


def herramientas_para_nodo(herramientas: list[Herramienta], nodo: str) -> list[Herramienta]:
    """Las herramientas de `herramientas` que le tocan a `nodo`, ya validadas
    contra su lista blanca. Filtra primero y valida despues a proposito: la
    validacion no es redundante con el filtro, es la red por si alguien
    cambia el filtro."""
    _validar_nodo(nodo)
    propias = [h for h in herramientas if h.nombre in HERRAMIENTAS_POR_NODO[nodo]]
    validar_catalogo(propias, nodo=nodo)
    return propias


# --------------------------------------------------------------------------- #
# Los esquemas que ve el modelo. JSON Schema, la forma que entiende cualquier
# proveedor con tool-calling compatible con OpenAI (DeepSeek incluido).
# --------------------------------------------------------------------------- #

_ESQUEMA_BUSCAR_COMERCIOS = {
    "type": "object",
    "properties": {
        "consulta": {
            "type": "string",
            "description": "Texto libre para filtrar por nombre, categoria o "
            "descripcion. Vacio o ausente devuelve todos los comercios.",
        }
    },
}

_ESQUEMA_BUSCAR_PRODUCTOS = {
    "type": "object",
    "properties": {
        "comercio_id": {
            "type": "string",
            "description": "El id de un comercio obtenido de buscar_comercios.",
        },
        "consulta": {
            "type": "string",
            "description": "Texto libre para filtrar. Vacio devuelve todo el "
            "catalogo de ese comercio.",
        },
    },
    "required": ["comercio_id"],
}

_ESQUEMA_VER_PRODUCTO = {
    "type": "object",
    "properties": {
        "producto_id": {
            "type": "string",
            "description": "El id de un producto obtenido de buscar_productos.",
        }
    },
    "required": ["producto_id"],
}

_ESQUEMA_ARMAR_CARRITO = {
    "type": "object",
    "properties": {
        "comercio_id": {
            "type": "string",
            "description": "El comercio al que pertenecen todos los items. Un "
            "carrito es de un solo comercio.",
        },
        "items": {
            "type": "array",
            "description": "Los productos a agregar.",
            "items": {
                "type": "object",
                "properties": {
                    "producto_id": {"type": "string"},
                    "cantidad": {"type": "integer", "minimum": 1},
                },
                "required": ["producto_id"],
            },
        },
        "justificacion": {
            "type": "string",
            "description": "Por que se arma este carrito -- lo va a ver el "
            "humano cuando decida si autoriza la compra.",
        },
    },
    "required": ["comercio_id", "items"],
}

_ESQUEMA_PAGAR = {
    "type": "object",
    "properties": {
        "mandato_id": {
            "type": "string",
            "description": "El id de un mandato YA AUTORIZADO por el humano. "
            "Nunca lo inventes: te lo entrega la app despues de que la persona "
            "firme la propuesta de armar_carrito.",
        },
        "carrito_id": {
            "type": "string",
            "description": "El carrito que devolvio armar_carrito.",
        },
    },
    "required": ["mandato_id", "carrito_id"],
}

_ESQUEMA_CONSULTAR_ESTADO = {
    "type": "object",
    "properties": {
        "intencion_id": {
            "type": "string",
            "description": "El id de intencion que devolvio pagar.",
        }
    },
    "required": ["intencion_id"],
}


def construir_herramientas(
    *,
    buscar_comercios: Callable[..., Any],
    buscar_productos: Callable[..., Any],
    ver_producto: Callable[..., Any],
    armar_carrito: Callable[..., Any],
    pagar: Callable[..., Any],
    consultar_estado: Callable[..., Any],
) -> list[Herramienta]:
    """Arma las seis `Herramienta` del catalogo autorizado, atadas a
    funciones ya cerradas sobre sus dependencias reales (closures armadas por
    `composicion/agente.py`, el unico lugar que conoce tanto `aplicacion/`
    como `agente/`).

    Este modulo nunca importa `aplicacion/` para construirlas: recibe seis
    funciones con nombre y forma, nada mas -- ni siquiera sabe que del otro
    lado de `pagar` hay un `EjecutarIntencion`. Eso es lo que hace que la
    frontera sea estructural y no una convencion: no hace falta disciplina
    para que `agente/` no vea un `EjecutarIntencion`, porque no puede
    importarlo (`test_fronteras.py:test_el_agente_no_alcanza_ninguna_pasarela`
    y la regla de dependencia general).
    """
    herramientas = [
        Herramienta(
            nombre="buscar_comercios",
            descripcion="Busca comercios simulados por nombre, categoria o "
            "descripcion. Sin argumentos, devuelve todos.",
            esquema=_ESQUEMA_BUSCAR_COMERCIOS,
            ejecutar=buscar_comercios,
        ),
        Herramienta(
            nombre="buscar_productos",
            descripcion="Busca productos dentro de un comercio ya elegido.",
            esquema=_ESQUEMA_BUSCAR_PRODUCTOS,
            ejecutar=buscar_productos,
        ),
        Herramienta(
            nombre="ver_producto",
            descripcion="El detalle y precio de un producto puntual.",
            esquema=_ESQUEMA_VER_PRODUCTO,
            ejecutar=ver_producto,
        ),
        Herramienta(
            nombre="armar_carrito",
            descripcion="Arma un carrito con los productos elegidos y devuelve "
            "una propuesta de compra SIN AUTORIZAR -- falta que el humano la "
            "revise y firme fuera de esta charla.",
            esquema=_ESQUEMA_ARMAR_CARRITO,
            ejecutar=armar_carrito,
        ),
        Herramienta(
            nombre="pagar",
            descripcion="Ejecuta el cobro de un carrito contra un mandato que "
            "el humano ya autorizo. El resultado puede quedar 'pendiente' -- "
            "usa consultar_estado despues para saber el desenlace.",
            esquema=_ESQUEMA_PAGAR,
            ejecutar=pagar,
        ),
        Herramienta(
            nombre="consultar_estado",
            descripcion="El estado actual de una intencion de pago: pendiente, "
            "aprobado, rechazado, o esperando confirmacion humana.",
            esquema=_ESQUEMA_CONSULTAR_ESTADO,
            ejecutar=consultar_estado,
        ),
    ]
    validar_catalogo(herramientas)
    return herramientas
