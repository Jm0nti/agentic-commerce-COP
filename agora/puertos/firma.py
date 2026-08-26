"""El puerto de firma. `Verificador` vive en `dominio/mandato/modelo.py` (el
dominio declara la interfaz que necesita internamente para evaluar un
mandato); `Firmante` vive aca porque quien lo necesita es un caso de uso de
`aplicacion/` (`EmitirMandato`), no el dominio -- y `aplicacion/` nunca
importa `adaptadores/` directo, solo puertos.

DOS INTERFACES SEPARADAS, A PROPOSITO
--------------------------------------
Firmar y verificar no son la misma operacion vista desde dos lados: firmar
exige la llave privada del titular, verificar solo la publica que ya viaja
dentro del propio mandato. Juntarlas en un solo `Protocol` obligaria a
`EjecutarIntencion` (que solo verifica) a depender de una interfaz que
tambien sabe firmar -- una superficie mas ancha de la que ese caso de uso
necesita.

QUIEN CONSTRUYE UN `Firmante` DE VERDAD
-----------------------------------------
`adaptadores/sistema/firma_ed25519.py:FirmanteEd25519`, armado por
`composicion/contenedor.py` a partir de una llave ed25519 en disco -- ver el
docstring de `cargar_o_generar_firmante`. `agente/` nunca lo ve: no importa
`puertos.firma` ni recibe un `Firmante` por constructor. La llave del
titular no esta en su proceso (`agente/herramientas.py`, seccion de arriba).
"""

from __future__ import annotations

from typing import Protocol


class Firmante(Protocol):
    def firma(self, carga: bytes) -> bytes: ...

    def llave_publica(self) -> bytes: ...
