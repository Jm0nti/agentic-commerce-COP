"""Identificadores con tipo.

Todos son `str` en tiempo de ejecucion; la diferencia la hace el verificador de
tipos. Suena a ceremonia hasta que se recuerda el bug que obligo a agregar la
guarda de ambiente en los repositorios: pasar un identificador de un ambiente
donde iba el del otro.

`MedioDePagoId` no esta aqui a proposito: un medio de pago no se referencia por
un `str` suelto sino por `MedioDePagoRef`, que lleva proveedor y ambiente
consigo. Ver `model/pago/modelo.py`.
"""

from __future__ import annotations

from typing import NewType

TitularId = NewType("TitularId", str)
MandatoId = NewType("MandatoId", str)
PropuestaId = NewType("PropuestaId", str)
IntencionId = NewType("IntencionId", str)
CobroId = NewType("CobroId", str)
ReservaId = NewType("ReservaId", str)

ComercioId = NewType("ComercioId", str)
ProductoId = NewType("ProductoId", str)
CarritoId = NewType("CarritoId", str)

ConversacionId = NewType("ConversacionId", str)
TurnoId = NewType("TurnoId", str)

PREFIJOS = {
    "TitularId": "tit",
    "MandatoId": "mnd",
    "PropuestaId": "prp",
    "IntencionId": "int",
    "CobroId": "cbr",
    "ReservaId": "rsv",
    "ComercioId": "com",
    "ProductoId": "prd",
    "CarritoId": "car",
    "ConversacionId": "cnv",
    "TurnoId": "trn",
}
