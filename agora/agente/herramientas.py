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
from typing import Any, Callable


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
)


def validar_catalogo(herramientas: list[Herramienta]) -> None:
    """Se corre al armar el agente, no en un test lejano.

    Un `assert` en el arranque vale mas que una convencion documentada: si
    alguien agrega una herramienta que revela credenciales, la app no levanta.
    """
    for h in herramientas:
        for prohibida in PROHIBIDAS:
            if prohibida in h.nombre.lower():
                raise RuntimeError(
                    f"la herramienta '{h.nombre}' contiene '{prohibida}'. "
                    "El agente no puede tener acceso a credenciales ni a la firma."
                )
        if h.nombre not in CATALOGO_DE_HERRAMIENTAS:
            raise RuntimeError(
                f"'{h.nombre}' no esta en el catalogo autorizado. "
                "Agregarla es una decision de diseno, no un detalle."
            )
