"""Sesiones de LOGIN para `entradas/api/` -- un concepto DISTINTO de
`entradas/api/sesiones.py:AlmacenDeSesiones`, que modela una charla de chat
(una `Conversacion` por pestana). Esta clase modela otra cosa: que
`titular_id` esta detras de la cookie que el navegador manda en cada
peticion, una vez que la persona ya inicio sesion.

POR QUE UN ALMACEN APARTE, Y NO REUTILIZAR `AlmacenDeSesiones`
------------------------------------------------------------------
Iniciar sesion no tiene nada que ver con el agente: una persona puede
iniciar sesion, mirar sus medios de pago (`GET /medios`), y nunca abrir el
chat. Mezclar los dos conceptos en un solo almacen obligaria a que "iniciar
sesion" supiera de `Agente`/`Conversacion`, que es exactamente lo que
`docs/arquitectura-v2.md` (seccion 2) le asigna a `agente/`, no a esta capa
-- y `AlmacenDeSesiones` ya documenta en su propio docstring que vive en
`entradas/` por la misma razon.

POR QUE EN MEMORIA, Y NO EN SQLITE (a diferencia de las llaves de firma)
----------------------------------------------------------------------------
El usuario (4 de septiembre de 2026) decidio explicitamente que las LLAVES
de firma vivieran en SQLite -- pero una sesion de login es un token efimero
de UN proceso de `entradas/api/`, no un dato de negocio que tenga que
sobrevivir un reinicio del servidor: si el proceso se reinicia, es
razonable que todas las sesiones queden invalidadas y cada persona tenga
que iniciar sesion de nuevo, igual que ya pasa con `AlmacenDeSesiones`
(`Conversacion` en memoria, docstring de ese modulo).
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from ...dominio.comun.errores import SesionInvalida
from ...dominio.usuario.modelo import Usuario
from ...puertos.sistema import Reloj

COOKIE_SESION = "agora_sesion"
DURACION_SESION = timedelta(hours=12)


@dataclass
class _SesionWeb:
    titular_id: str
    nombre_usuario: str
    expira_en: datetime


class AlmacenDeSesionesWeb:
    """Token opaco (`secrets.token_urlsafe`) -> `(titular_id,
    nombre_usuario)`, con expiracion. `entradas/api/app.py` lo guarda en una
    cookie httponly (`COOKIE_SESION`) y lo resuelve en cada peticion
    protegida via la dependencia `_requiere_titular`."""

    def __init__(self, reloj: Reloj, duracion: timedelta = DURACION_SESION) -> None:
        self._reloj = reloj
        self._duracion = duracion
        self._lock = threading.Lock()
        self._sesiones: dict[str, _SesionWeb] = {}

    def crear(self, usuario: Usuario) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sesiones[token] = _SesionWeb(
                titular_id=usuario.titular_id,
                nombre_usuario=usuario.nombre_usuario,
                expira_en=self._reloj.ahora() + self._duracion,
            )
        return token

    def titular_de(self, token: str) -> tuple[str, str]:
        """`(titular_id, nombre_usuario)`, o levanta `SesionInvalida` si el
        token no existe o ya expiro."""
        with self._lock:
            sesion = self._sesiones.get(token)
            if sesion is None:
                raise SesionInvalida("no hay una sesion activa -- inicie sesion de nuevo")
            if sesion.expira_en <= self._reloj.ahora():
                del self._sesiones[token]
                raise SesionInvalida("la sesion expiro -- inicie sesion de nuevo")
            return sesion.titular_id, sesion.nombre_usuario

    def cerrar(self, token: str) -> None:
        with self._lock:
            self._sesiones.pop(token, None)
