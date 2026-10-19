"""`RechazarPropuestaUseCase`: el contrapunto de `EmitirMandatoUseCase` cuando el humano
NO firma. Decir que no tambien es una decision humana, asi que este caso de
uso vive del mismo lado que `EmitirMandatoUseCase` (`usecase/agente/` nunca lo llama -- no
esta en `usecase/agente/herramientas.py:CATALOGO_DE_HERRAMIENTAS`).

POR QUE ESTO NO TOCA `Mandato` NI `Consumo`
--------------------------------------------
Rechazar no emite nada: no hay mandato que guardar, no hay reserva que
liberar (`EmitirMandatoUseCase` todavia no corrio contra esta propuesta, asi que
`LibroDeConsumo` nunca se entero de ella). Lo unico que hace falta es dejar
constancia en la bitacora -- que quien pidio el rechazo pueda avisarle a la
conversacion es trabajo de `entry_points/api_rest/app.py`, igual que ya hace con el
aviso de `firmar`/`retomar`.

POR QUE NO HAY ESTADO NUEVO EN `PropuestaDeMandato`
------------------------------------------------------
A diferencia de firmar/confirmar, rechazar una propuesta se resuelve
siempre en el mismo proceso que la armo -- el popup y el chat viven en la
misma sesion HTTP (`entry_points/api_rest/sesiones.py`). No hace falta que la
decision sobreviva a un reinicio ni que otro proceso la vea, asi que no hay
motivo para una tabla nueva (`RegistroDeEstados` es para el otro caso:
`retomar` corre SIEMPRE en otro proceso -- ver su docstring en
`model/<agregado>/gateways/repositorios.py`)."""

from __future__ import annotations

from ...model.mandato.gateways.repositorios import RepositorioPropuestas
from ...model.commons.gateways.sistema import Bitacora


class RechazarPropuestaUseCase:
    def __init__(self, propuestas: RepositorioPropuestas, bitacora: Bitacora) -> None:
        self._propuestas = propuestas
        self._bitacora = bitacora

    def __call__(self, propuesta_id: str, titular_id: str) -> None:
        # Se busca por id, nunca se acepta un objeto por parametro -- mismo
        # argumento que `EmitirMandatoUseCase` (ver el docstring de
        # `RepositorioPropuestas`). De paso, levanta `PropuestaDesconocida`
        # si alguien manda un id inventado.
        propuesta = self._propuestas.obtener(propuesta_id)
        self._bitacora.anotar(
            "propuesta_rechazada",
            {
                "propuesta_id": propuesta.propuesta_id,
                "carrito_id": propuesta.carrito_id,
                "comercio_id": propuesta.comercio_id,
                "titular_id": titular_id,
            },
        )
