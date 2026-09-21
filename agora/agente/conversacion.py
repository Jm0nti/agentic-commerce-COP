"""El loop de turnos. `docs/arquitectura-v2.md`, seccion 4: `responder(mensajes,
herramientas) -> RespuestaModelo`, corrido hasta que el modelo conteste con
texto y sin mas llamadas pendientes -- o hasta `MAX_TURNOS_POR_CONVERSACION`
(`politica.py`).

    usuario -> Conversacion.mensajes += Mensaje(user)
                        |
              modelo.responder(...)  -----------------.
                        |                              |
              ¿trae llamadas a herramientas?           |
                 si -> ejecutarlas, agregar            |
                       Mensaje(tool) por cada una,      |
                       volver a llamar a responder -----'
                 no -> devolver el contenido de texto

No hay async ni streaming aqui a proposito (`arquitectura-v2.md`, seccion 9:
"no hagas el agente asincrono todavia" -- un turno de chat es secuencial por
naturaleza). `entradas/cli/` llama a `Agente.turno` una vez por linea que
escribe la persona.

DECIDIR, DESPUES EJECUTAR (migracion a agentes, etapa 1)
----------------------------------------------------------
Con un `ClasificadorDeIntencion`, cada turno tiene dos pasos explicitos:

    1. decidir   clasificador -> `ClasificacionDeIntencion` -> `Ruta`
                 (`agente/nodos.py`): que nodos actuan este turno y, por lo
                 tanto, que herramientas ve el modelo.
    2. ejecutar  el mismo loop de siempre, pero anunciando SOLO las
                 herramientas de la ruta, con una instruccion corta del
                 orquestador para este turno, y rechazando al ejecutar
                 cualquier llamada a una herramienta fuera de la ruta --
                 aunque exista en el agente. Anunciar menos no alcanza: un
                 modelo puede pedir una herramienta que no se le anuncio.

La instruccion del orquestador NO se guarda en `Conversacion.mensajes`: se
agrega al mensaje de sistema de la vista que recibe el modelo, y se descarta
al terminar el turno. Si se guardara, cada turno viejo arrastraria la
instruccion de una ruta que ya no aplica. Va pegada al mensaje de sistema
inicial -- y no como un mensaje de sistema suelto a mitad del historial --
porque no todo proveedor compatible con Chat Completions acepta un "system"
en cualquier posicion, y un 400 del proveedor tumbaria el turno entero. Lo
que SI queda registrado es la decision: `Conversacion.clasificaciones`.

Sin clasificador (`AGORA_CLASIFICADOR=apagado`, o quien construya un
`Agente` sin pasarle uno) el turno es exactamente el de antes: las
herramientas completas, sin instruccion extra, sin clasificaciones.

CONTEXTO POR NODO (migracion a agentes, etapa 2)
--------------------------------------------------
Ademas de herramientas, un nodo puede inyectar contexto en su turno
(`agente/contexto.py`): hoy, soporte agrega documentacion recuperada. Se
pide una sola vez por turno -- despues de decidir la ruta y antes del loop --
solo para los nodos de esa ruta, y se pega a la instruccion del orquestador
(misma vista, mismo "no se guarda en `mensajes`"). Lo que se inyecto queda
registrado en `Conversacion.contextos`. En la ruta de respaldo no hay
contexto: respaldo sigue siendo el agente de antes, sin nada extra.

EL TURNO, EN CUATRO PASOS PUBLICOS (migracion a agentes, etapa 3)
------------------------------------------------------------------
`turno()` es la suma de cuatro metodos publicos:

    abrir_turno              agrega el mensaje de la persona, devuelve el
                             historial previo
    decidir                  -> Ruta
    instrucciones_del_turno  -> instruccion del orquestador + contexto
    ejecutar_turno           -> el loop de herramientas, texto final

Eran privados hasta la etapa 3. Se volvieron publicos porque
`agente/grafo.py` los reparte entre los nodos de un grafo (`AgenteEnGrafo`),
y la alternativa -- duplicar la logica alla, o llamar metodos privados desde
afuera -- deja dos caminos que pueden divergir en silencio. Asi hay un solo
comportamiento y dos formas de recorrerlo: en fila (este `turno()`) o por el
grafo. `tests/test_agente_grafo_equivalencia.py` verifica que dan lo mismo.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Mapping

from ..dominio.comun.errores import ErrorDeDominio
from ..puertos.modelo_lenguaje import (
    DefinicionHerramienta,
    LlamadaHerramienta,
    Mensaje,
    ModeloDeLenguaje,
)
from ..puertos.sistema import Bitacora
from .contexto import ContextoInyectado, ProveedorDeContexto
from .herramientas import (
    HERRAMIENTAS_POR_NODO,
    NODO_DUENO_DEL_FLUJO_DE_DINERO,
    Herramienta,
    herramientas_para_nodo,
    validar_asignacion_por_nodo,
    validar_catalogo,
    validar_nodos_con_contexto,
)
from .intencion import ClasificacionDeIntencion, ClasificadorDeIntencion
from .nodos import Ruta, ruta_para
from .pausa import DecisionHumana, PausaDelTurno, detectar_pausa
from .politica import MAX_TURNOS_POR_CONVERSACION, SYSTEM_PROMPT
from .traza import EVENTO as EVENTO_DE_TRAZA
from .traza import InicioDelTurno, armar_traza
from .traza import comenzar as comenzar_traza


class LimiteDeTurnosExcedido(Exception):
    """El modelo encadeno mas de `MAX_TURNOS_POR_CONVERSACION` llamadas a
    herramientas seguidas sin llegar a una respuesta de texto."""


@dataclass
class Conversacion:
    """El historial de una charla. Vive en memoria del proceso mientras dura
    -- no hay persistencia entre reinicios en esta etapa, igual que el
    `Carrito` en `RepositorioCarritosEnMemoria`."""

    # Para correlacionar los turnos de UNA charla en la bitacora de trazas:
    # sin esto, dos personas chateando a la vez dejan lineas intercaladas que
    # no se pueden separar despues. No identifica a nadie -- es un id de
    # proceso, no del titular (el `titular_id` vive en `entradas/api/
    # sesiones.py`, que es quien sabe de identidades).
    conversacion_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    mensajes: list[Mensaje] = field(default_factory=list)
    # Una por turno, en orden, cuando el `Agente` tiene clasificador. Es el
    # registro auditable de "que decidio el orquestador" -- separado de
    # `mensajes`, que es lo que ve el modelo.
    clasificaciones: list[ClasificacionDeIntencion] = field(default_factory=list)
    # (nodo, contexto) en el orden en que se inyectaron, un turno tras otro.
    # Registro auditable de "que documentacion vio el modelo" -- el texto
    # inyectado nunca entra a `mensajes`.
    contextos: list[tuple[str, ContextoInyectado]] = field(default_factory=list)
    # Etapa 5: que quedo esperando a una persona al terminar el ultimo
    # turno, o `None`. Lo pone el grafo al detenerse en `espera_humana` y lo
    # lee `entradas/api/sesiones.py` para armar el popup -- antes eso se
    # deducia volviendo a parsear el JSON de los resultados de herramientas.
    pausa: PausaDelTurno | None = None


class Agente:
    def __init__(
        self,
        modelo: ModeloDeLenguaje,
        herramientas: list[Herramienta],
        clasificador: ClasificadorDeIntencion | None = None,
        contextos: Mapping[str, ProveedorDeContexto] | None = None,
        bitacora: Bitacora | None = None,
    ) -> None:
        # Se corre al armar el agente, no en un test lejano (mismo
        # argumento que el docstring de `validar_catalogo`): si alguien le
        # agrega una herramienta prohibida, este proceso ni siquiera levanta.
        validar_catalogo(herramientas)
        # Y lo mismo por nodo: la tabla de listas blancas tiene que ser
        # coherente, y cada herramienta que le llega al agente tiene que
        # pasar la validacion del nodo que es su dueño.
        validar_asignacion_por_nodo()
        for nodo in HERRAMIENTAS_POR_NODO:
            herramientas_para_nodo(herramientas, nodo)
        contextos = dict(contextos or {})
        validar_nodos_con_contexto(contextos)

        self._modelo = modelo
        self._clasificador = clasificador
        self._contextos = contextos
        # `None` = sin trazabilidad (pruebas que arman un `Agente` a mano).
        # `composicion/agente.py` siempre la provee.
        self._bitacora = bitacora
        self._herramientas = {h.nombre: h for h in herramientas}
        self._definiciones = [
            DefinicionHerramienta(nombre=h.nombre, descripcion=h.descripcion, esquema=h.esquema)
            for h in herramientas
        ]

    @property
    def herramientas(self) -> list[Herramienta]:
        """Las herramientas con las que se armo, para quien necesite
        validarlas por nodo (`agente/agentes.py`, etapa 4). Una copia de la
        lista: nadie de afuera le agrega una al agente ya construido, que es
        lo que `validar_catalogo` verifica al arrancar y no podria volver a
        verificar despues."""
        return list(self._herramientas.values())

    def iniciar(self) -> Conversacion:
        return Conversacion(mensajes=[Mensaje(rol="system", contenido=SYSTEM_PROMPT)])

    def turno(self, conversacion: Conversacion, mensaje_usuario: str) -> str:
        """Un turno completo: agrega lo que escribio la persona, decide la
        ruta, deja correr el loop de herramientas dentro de esa ruta, y
        devuelve el texto final. Muta `conversacion` in place -- llamar de
        nuevo sigue la misma charla.

        Los cuatro pasos son publicos desde la etapa 3 de la migracion a
        agentes: `agente/grafo.py` los reparte entre los nodos del grafo, y
        este metodo los corre en fila. La logica esta una sola vez -- la
        version con grafo no reimplementa nada, y nadie de afuera tiene que
        tocar un metodo privado para armar un turno."""
        inicio = comenzar_traza(conversacion)
        historial_previo = self.abrir_turno(conversacion, mensaje_usuario)
        conversacion.pausa = None
        ruta = self.decidir(conversacion, mensaje_usuario, historial_previo)
        instrucciones = self.instrucciones_del_turno(
            conversacion, ruta, mensaje_usuario, historial_previo,
        )
        desde = len(conversacion.mensajes)
        respuesta = self.ejecutar_turno(conversacion, ruta, instrucciones)
        # Etapa 5: sin grafo no hay nodo `espera_humana`, pero la pausa se
        # detecta igual -- si no, `AGORA_ORQUESTACION=directo` se quedaria
        # sin los popups de firma y confirmacion, y los dos modos dejarian
        # de ser equivalentes (que es justo lo que la etapa 3 prometio).
        conversacion.pausa = detectar_pausa(conversacion.mensajes[desde:])
        self.anotar_traza(
            conversacion, inicio, mensaje_usuario, respuesta, ruta,
            pausa=conversacion.pausa,
        )
        return respuesta

    def reanudar(self, conversacion: Conversacion, decision: DecisionHumana) -> str:
        """La persona resolvio lo que el turno estaba esperando (etapa 5).

        Un turno mas -- el aviso entra como un mensaje y el modelo decide
        que hacer -- pero el texto lo arma UNA sola funcion
        (`DecisionHumana.como_aviso`) a partir de datos tipados, en vez de
        cuatro sitios de `entradas/` armandolo a mano. Esa era la queja
        concreta de la decision 6.

        No verifica nada de dinero, y no podria: cuando esto corre, el
        mandato ya se emitio (o no) en `aplicacion/`, por pedido de la
        persona. Aca solo se entera el modelo."""
        conversacion.pausa = None
        return self.turno(conversacion, decision.como_aviso())

    # -- paso 5: dejar la evidencia --------------------------------------- #

    def anotar_traza(
        self,
        conversacion: Conversacion,
        inicio: InicioDelTurno,
        mensaje_usuario: str,
        respuesta: str,
        ruta: Ruta | None,
        agente: str | None = None,
        pausa: PausaDelTurno | None = None,
    ) -> None:
        """La cadena de decisiones de ESTE turno, a la bitacora de trazas.

        Publico como los otros cuatro pasos, y por la misma razon:
        `agente/grafo.py` corre el turno por el grafo y tiene que poder
        dejar la misma evidencia sin duplicar como se arma.

        Nunca tumba un turno. Una charla que ya se contesto no se puede
        perder porque el disco este lleno o el archivo no se pueda abrir:
        la evidencia importa, pero menos que la respuesta que la persona ya
        tiene en pantalla."""
        if self._bitacora is None:
            return
        try:
            self._bitacora.anotar(
                EVENTO_DE_TRAZA,
                armar_traza(
                    conversacion, inicio, mensaje_usuario, respuesta, ruta, agente, pausa,
                ),
            )
        except Exception:  # noqa: BLE001 -- ver el docstring
            pass

    # -- paso 0: abrir el turno ------------------------------------------ #

    def abrir_turno(self, conversacion: Conversacion, mensaje_usuario: str) -> tuple[Mensaje, ...]:
        """Agrega el mensaje de la persona y devuelve el historial de ANTES
        de agregarlo -- que es lo que recibe el clasificador (y el proveedor
        de contexto): lo que ya se habia dicho, sin el mensaje que se esta
        clasificando. Se toma la copia antes de mutar; `conversacion.mensajes`
        es una lista que el loop sigue creciendo."""
        historial_previo = tuple(conversacion.mensajes)
        conversacion.mensajes.append(Mensaje(rol="user", contenido=mensaje_usuario))
        return historial_previo

    # -- paso 1: decidir ------------------------------------------------- #

    def decidir(
        self, conversacion: Conversacion, mensaje_usuario: str, historial: tuple[Mensaje, ...]
    ) -> Ruta:
        if self._clasificador is None:
            return ruta_para(None)
        clasificacion = self._clasificador.clasificar(mensaje_usuario, historial)
        conversacion.clasificaciones.append(clasificacion)
        return ruta_para(clasificacion)

    def instrucciones_del_turno(
        self,
        conversacion: Conversacion,
        ruta: Ruta,
        mensaje_usuario: str,
        historial: tuple[Mensaje, ...],
    ) -> str | None:
        """La instruccion del orquestador, mas el contexto de cada nodo de
        la ruta que tenga uno. Respaldo no tiene ninguna de las dos.

        Una ruta que incluye al dueño del flujo de dinero no recibe contexto
        de NINGUN nodo, aunque otro nodo de la misma ruta tenga uno (hoy la
        ruta de compra junta catalogo + carrito_pago): `validar_nodos_con_
        contexto` impide colgarlo del nodo de dinero, y esto impide que
        llegue por la puerta de al lado."""
        instrucciones = ruta.instrucciones()
        if instrucciones is None:
            return None
        if NODO_DUENO_DEL_FLUJO_DE_DINERO in ruta.nodos:
            return instrucciones
        partes = [instrucciones]
        for nodo in ruta.nodos:
            proveedor = self._contextos.get(nodo)
            if proveedor is None:
                continue
            contexto = proveedor.contexto_para(mensaje_usuario, historial)
            if contexto is None:
                continue
            conversacion.contextos.append((nodo, contexto))
            partes.append(contexto.texto)
        return "\n\n".join(partes)

    # -- paso 2: ejecutar ------------------------------------------------ #

    def ejecutar_turno(
        self, conversacion: Conversacion, ruta: Ruta, instrucciones: str | None
    ) -> str:
        habilitadas = ruta.herramientas & frozenset(self._herramientas)
        definiciones = [d for d in self._definiciones if d.nombre in habilitadas]

        for _ in range(MAX_TURNOS_POR_CONVERSACION):
            vista = _vista_para_el_modelo(conversacion.mensajes, instrucciones)
            respuesta = self._modelo.responder(vista, definiciones)
            conversacion.mensajes.append(
                Mensaje(rol="assistant", contenido=respuesta.contenido, llamadas=respuesta.llamadas)
            )
            if not respuesta.llamadas:
                return respuesta.contenido or ""

            for llamada in respuesta.llamadas:
                conversacion.mensajes.append(
                    Mensaje(
                        rol="tool",
                        contenido=self._ejecutar(llamada, habilitadas, ruta),
                        id_llamada=llamada.id,
                        nombre_herramienta=llamada.nombre,
                    )
                )

        raise LimiteDeTurnosExcedido(
            f"el agente supero {MAX_TURNOS_POR_CONVERSACION} rondas de "
            "herramientas en un mismo turno sin llegar a una respuesta"
        )

    def _ejecutar(
        self, llamada: LlamadaHerramienta, habilitadas: frozenset[str], ruta: Ruta
    ) -> str:
        """Nunca deja que una excepcion de una herramienta tumbe el turno:
        se traduce a un mensaje de rol "tool" que el modelo puede leer y
        decidir que hacer -- pedir de nuevo con otros argumentos, o
        contarle a la persona que no se pudo. Un `ErrorDeDominio` ya trae
        `to_json()` pensado para esto (`dominio/comun/errores.py`).

        Una herramienta que existe pero no esta en la ruta de este turno se
        rechaza ANTES de tocar su funcion: es la diferencia entre "no se la
        anunciamos al modelo" y "no la puede ejecutar"."""
        herramienta = self._herramientas.get(llamada.nombre)
        if herramienta is None:
            return json.dumps({"error": f"herramienta desconocida: '{llamada.nombre}'"})
        if llamada.nombre not in habilitadas:
            intencion = (
                ruta.clasificacion.intencion.value
                if ruta.clasificacion is not None and ruta.clasificacion.intencion is not None
                else "respaldo"
            )
            return json.dumps(
                {
                    "error": f"la herramienta '{llamada.nombre}' no esta habilitada en este "
                    f"turno (intencion: {intencion}; nodos: {', '.join(ruta.nodos)})",
                },
                ensure_ascii=False,
            )
        try:
            resultado = herramienta.ejecutar(**llamada.argumentos)
        except ErrorDeDominio as exc:
            return json.dumps(exc.to_json(), ensure_ascii=False)
        except TypeError as exc:
            return json.dumps(
                {"error": f"argumentos invalidos para '{llamada.nombre}': {exc}"},
                ensure_ascii=False,
            )
        return json.dumps(resultado, ensure_ascii=False, default=str)


def _vista_para_el_modelo(mensajes: list[Mensaje], instrucciones: str | None) -> list[Mensaje]:
    """Lo que recibe `ModeloDeLenguaje.responder`: el historial tal cual,
    con la instruccion del orquestador (si la hay) agregada al final del
    mensaje de sistema inicial. Una copia, siempre -- nunca la lista de la
    conversacion, que el loop sigue mutando."""
    if instrucciones is None:
        return list(mensajes)
    if mensajes and mensajes[0].rol == "system":
        base = mensajes[0].contenido or ""
        return [Mensaje(rol="system", contenido=f"{base}\n\n{instrucciones}"), *mensajes[1:]]
    return [Mensaje(rol="system", contenido=instrucciones), *mensajes]
