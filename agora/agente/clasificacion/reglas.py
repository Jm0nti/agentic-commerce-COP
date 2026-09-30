"""El camino rapido: reglas deterministicas para intenciones inequivocas.

`docs/arquitectura-agentes-langgraph.md`, "Riesgos a vigilar": router +
agente especializado son dos llamadas al LLM por turno en vez de una. Antes
de pagar la segunda, estas reglas resuelven lo que no necesita un modelo --
entre otras cosas, TODOS los avisos que el propio sistema le manda a la
conversacion (`entradas/api/app.py` despues de firmar o retomar desde un
popup, `entradas/api/sesiones.py:resolver_pendiente` cuando llega un
webhook), que siempre traen marcas como `pagar()` o `consultar_estado`.

LA REGLA DE ORO: ABSTENERSE ANTES QUE ADIVINAR
------------------------------------------------
Si un mensaje activa patrones de mas de una intencion, estas reglas NO
eligen: devuelven respaldo y dejan que decida el clasificador con modelo (o,
sin modelo, la ruta de respaldo). La unica excepcion es explicita y esta en
`_SUBSUME`: una intencion de compra que ademas nombra productos o comercios
es compra, porque la ruta de `carrito_pago` ya incluye las herramientas de
catalogo (`agente/nodos.py:RUTAS`) -- elegirla no le quita nada al turno.

Que un mensaje "active" una intencion por reglas nunca le da al turno MAS
de lo que tenia el agente de antes: toda ruta es un subconjunto del catalogo
autorizado. Escribir "consultar_estado" a proposito en el chat solo angosta
lo que el modelo puede hacer en ese turno.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence

from ...model.agente.gateways.modelo_lenguaje import Mensaje
from ..intencion import ClasificacionDeIntencion, OrigenDeClasificacion, TipoDeIntencion

# Los patrones se aplican sobre el texto normalizado (`normalizar`):
# minusculas, sin tildes, espacios colapsados.
_PATRONES: dict[TipoDeIntencion, tuple[str, ...]] = {
    TipoDeIntencion.ESTADO: (
        r"\bconsultar_estado\b",
        r"\bwebhook\b",
        r"\bint_[0-9a-f]{6,}\b",
        r"\bestado de (mi|la|el|ese|este) (pago|compra|cobro|pedido|intencion)\b",
        r"\bque paso con (mi|el|la|ese|este) (pago|compra|cobro|pedido)\b",
        r"\bya (confirme|aprobe|lo confirme|lo aprobe)\b",
        r"\b(sigue|esta|quedo) pendiente\b",
        r"\b(se aprobo|fue aprobad[oa]|quedo aprobad[oa]|fue rechazad[oa])\b",
    ),
    TipoDeIntencion.CARRITO_PAGO: (
        r"\bpagar\(",
        r"\bmandato_id=",
        r"\bcarrito_id=",
        r"\bmnd_[0-9a-f]{6,}\b",
        r"\b(comprar|comprarlo|comprarla|compralo|comprala|comprame|lo compro|la compro)\b",
        r"\bcarrito\b",
        r"\b(pagar|pagalo|pagala|paga)\b",
    ),
    TipoDeIntencion.CATALOGO: (
        r"\b(que|cuales) (tiendas|comercios|productos) (hay|tienen|venden)\b",
        r"\b(busca|buscar|buscame|muestrame|mostrame|ensename)\b",
        r"\b(catalogo|tiendas?|comercios?|productos?)\b",
        r"\bcuanto (cuesta|vale|sale)\b",
        r"\bprecios?\b",
        r"\b(prd|com)_[0-9a-z]{4,}\b",
    ),
    TipoDeIntencion.MEDIOS_DE_PAGO: (
        r"\b(enrolar|enrole|enrolo|enrolamiento|inscribir|vincular|desvincular|revocar|revoco)\b",
        r"\b(medios?|metodos?) de pago\b",
        r"\bnequi\b",
        r"\btarjetas?\b",
        r"\bcuenta (bancaria|de ahorros)\b",
    ),
    TipoDeIntencion.SOPORTE: (
        r"\bcomo funciona\b",
        r"\bque es (un|una|el|la) (mandato|tope|firma|propuesta|confirmacion)\b",
        r"\bque significa\b",
        r"\bpara que sirve\b",
        r"\b(preguntas frecuentes|faq)\b",
        r"\bpor que (me )?(pide|piden|pedis|tengo que|hay que) (firmar|confirmar)\b",
    ),
}

# Solo si el mensaje ENTERO es social -- "hola, quiero comprar" no entra
# aca, entra a `CARRITO_PAGO`. "si", "dale", "ok" tampoco: son la
# continuacion de algo, y solo el clasificador con historial lo puede leer.
_SOLO_SOCIAL = re.compile(
    r"^(hola|holi|buenas|buenos dias|buenas tardes|buenas noches|hey|"
    r"gracias|muchas gracias|mil gracias|chao|adios|hasta luego)[\s!.?,]*$"
)

# intencion ganadora -> intenciones que puede absorber sin perder
# herramientas. Ver el docstring del modulo.
_SUBSUME: dict[TipoDeIntencion, frozenset[TipoDeIntencion]] = {
    TipoDeIntencion.CARRITO_PAGO: frozenset({TipoDeIntencion.CATALOGO}),
}

_COMPILADOS = {
    intencion: tuple(re.compile(p) for p in patrones) for intencion, patrones in _PATRONES.items()
}


def normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sin_tildes.lower()).strip().lstrip("¿¡")


class ClasificadorPorReglas:
    """Implementa `agente.intencion.ClasificadorDeIntencion`. No mira el
    historial: una regla que dependiera del contexto dejaria de ser
    inequivoca."""

    def clasificar(
        self, mensaje: str, historial: Sequence[Mensaje] = ()
    ) -> ClasificacionDeIntencion:
        texto = normalizar(mensaje)
        activadas = {
            intencion
            for intencion, patrones in _COMPILADOS.items()
            if any(p.search(texto) for p in patrones)
        }

        if not activadas:
            if _SOLO_SOCIAL.match(texto):
                return self._decidida(TipoDeIntencion.FUERA_DE_ALCANCE, "mensaje solo social")
            return ClasificacionDeIntencion.respaldo("reglas: ningun patron inequivoco")

        if len(activadas) == 1:
            (unica,) = activadas
            return self._decidida(unica, f"patron de {unica.value}")

        for ganadora, absorbibles in _SUBSUME.items():
            if ganadora in activadas and activadas - {ganadora} <= absorbibles:
                otras = ", ".join(sorted(i.value for i in activadas - {ganadora}))
                return self._decidida(ganadora, f"patron de {ganadora.value} (absorbe {otras})")

        ambiguas = ", ".join(sorted(i.value for i in activadas))
        return ClasificacionDeIntencion.respaldo(f"reglas: ambiguo entre {ambiguas}")

    @staticmethod
    def _decidida(intencion: TipoDeIntencion, motivo: str) -> ClasificacionDeIntencion:
        return ClasificacionDeIntencion(
            intencion=intencion, origen=OrigenDeClasificacion.REGLAS, confianza=1.0, motivo=motivo,
        )
