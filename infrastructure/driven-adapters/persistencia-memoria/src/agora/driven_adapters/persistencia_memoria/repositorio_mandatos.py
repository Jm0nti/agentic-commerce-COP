"""`RepositorioMandatos` en memoria.

La guarda de ambiente es la version tipada de `nucleo.py:319-330`: alli un
mandato de sandbox se distinguia de uno de produccion revisando un `dict`
`modos` aparte, a mano, en cada `obtener`. Aqui el ambiente en el que se
guardo el mandato viaja junto con el, y `obtener` no deja construir la
pregunta sin contestarla -- es un parametro obligatorio, no un filtro
opcional que alguien puede olvidar.
"""

from __future__ import annotations

import threading

from ...model.commons.errores import MandatoDesconocido, MandatoDeOtroAmbiente
from ...model.mandato.modelo import Mandato
from ...model.pago.modelo import Ambiente


class RepositorioMandatosEnMemoria:
    """Implementa `puertos.repositorios.RepositorioMandatos`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mandatos: dict[str, tuple[Mandato, Ambiente]] = {}

    def guardar(self, mandato: Mandato, ambiente: Ambiente) -> None:
        with self._lock:
            self._mandatos[mandato.mandato_id] = (mandato, ambiente)

    def obtener(self, mandato_id: str, ambiente: Ambiente) -> Mandato:
        with self._lock:
            entrada = self._mandatos.get(mandato_id)
        if entrada is None:
            raise MandatoDesconocido(f"mandato desconocido: {mandato_id}")

        mandato, guardado_en = entrada
        if guardado_en != ambiente:
            raise MandatoDeOtroAmbiente(
                f"el mandato {mandato_id} se guardo en '{guardado_en.value}' y se "
                f"esta pidiendo desde '{ambiente.value}'. Su medio de pago "
                f"({mandato.medio.id_externo}) pertenece al otro ambiente."
            )
        return mandato

    def listar(self, ambiente: Ambiente) -> list[Mandato]:
        with self._lock:
            return [m for m, amb in self._mandatos.values() if amb == ambiente]
