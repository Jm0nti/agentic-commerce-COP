"""Contexto que un nodo inyecta en su turno (migracion a agentes, etapa 2).

Un nodo puede tener dos cosas: herramientas (que el MODELO decide llamar) y
contexto (que el NODO pone delante del modelo antes de que decida nada).
Esta etapa usa la segunda para soporte: la documentacion recuperada entra
como texto en la instruccion del turno, no como una herramienta nueva.

POR QUE CONTEXTO Y NO HERRAMIENTA
-----------------------------------
- Soporte sigue sin NINGUNA herramienta (`herramientas.py:
  HERRAMIENTAS_POR_NODO["soporte"] == ()`). No hay nada que agregar al
  catalogo autorizado ni a `PROHIBIDAS`, y la prueba de que soporte no
  alcanza el dinero sigue siendo tan simple como "no tiene herramientas".
- El modelo no decide si busca: el nodo busca siempre, una vez por turno.
  Un turno de soporte cuesta una busqueda, nunca un loop de busquedas.
- Lo que se recupero queda registrado en la conversacion
  (`Conversacion.contextos`) aunque el modelo lo ignore.

Un `ProveedorDeContexto` NUNCA puede colgarse del nodo dueño del dinero
(`Agente` lo rechaza al construirse): prosa recuperada al lado de `pagar`
es exactamente la mezcla que la regla "ninguna cifra sale de una
recuperacion" quiere evitar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .gateways.modelo_lenguaje import Mensaje


@dataclass(frozen=True)
class ContextoInyectado:
    """`texto` es lo que se agrega a la instruccion del turno; `fuentes`, de
    donde salio (para auditar y para `chat --mostrar-intencion`)."""

    texto: str
    fuentes: tuple[str, ...] = ()


class ProveedorDeContexto(Protocol):
    def contexto_para(
        self, mensaje: str, historial: Sequence[Mensaje] = ()
    ) -> ContextoInyectado | None:
        """El contexto para ESTE turno, o `None` si no hay nada que agregar.

        Nunca levanta porque su fuente no este disponible: en ese caso
        devuelve un contexto que lo dice, para que el modelo no invente. Un
        turno de chat no se cae porque la documentacion no respondio."""
        ...
