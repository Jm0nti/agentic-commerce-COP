"""Boveda de mandatos de pago.

Unico componente autorizado a tocar credenciales de Wompi. El agente le pide
que ejecute un mandato; nunca cobra por su cuenta.

    enrolamiento.py  Fase A: el titular autoriza una vez (push de Nequi)
    mandato.py       el documento firmado y su evaluacion
    nucleo.py        Fase B: ejecucion contra Wompi, topes duros
    eventos.py       receptor de webhooks con validacion de checksum
    cli.py           las dos fases desde la terminal
"""

from .enrolamiento import Fuente, RegistroFuentes, enrolar_nequi, preflight, revocar
from .mandato import Consumo, Intencion, Mandato, Violacion, emitir, evaluar
from .nucleo import Boveda, BovedaError, ClienteWompi, Recibo, perfil_pagador

__all__ = [
    "Boveda",
    "BovedaError",
    "ClienteWompi",
    "Consumo",
    "Fuente",
    "Intencion",
    "Mandato",
    "Recibo",
    "RegistroFuentes",
    "Violacion",
    "emitir",
    "enrolar_nequi",
    "evaluar",
    "perfil_pagador",
    "preflight",
    "revocar",
]
