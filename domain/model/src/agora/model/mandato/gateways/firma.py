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


class SelectorDeFirmante(Protocol):
    """Resuelve que `Firmante` usar para un titular dado. Multi-usuario (4
    de septiembre de 2026): mismo argumento que `SelectorDePasarela`
    (`puertos/pasarela.py`) un escalon mas adentro -- antes se armaba UN
    solo `Firmante` por proceso (`cargar_o_generar_firmante`, `adaptadores/
    sistema/firma_ed25519.py`) y `EmitirMandato` lo recibia fijo por
    constructor, sin importar que titular firmara. Con cada usuario
    registrado teniendo su propia llave (`RepositorioLlaves`), hace falta
    resolver el `Firmante` correcto en el momento de cada firma, no una
    sola vez al armar el contenedor.

    A DIFERENCIA de `SelectorDePasarela`, esta interfaz NUNCA tiene un
    "por defecto": no existe una llave compartida de respaldo para un
    titular sin la suya propia -- eso reproduciria exactamente el problema
    que este cambio existe para cerrar. Un `titular_id` sin llave levanta
    `SinLlaveDeFirma` (`dominio/comun/errores.py`), nunca cae de vuelta en
    la llave de otro."""

    def para(self, titular_id: str) -> Firmante: ...


class GeneradorDeLlaves(Protocol):
    """Genera un par de llaves ed25519 nuevo, crudo. Lo usa `aplicacion/
    autenticacion.py:RegistrarUsuario` para darle a cada usuario nuevo su
    propia llave de firma en el momento de crearlo -- separado de
    `Firmante` porque generar una llave y firmar con una llave ya existente
    son operaciones distintas (la primera no necesita ninguna llave
    todavia)."""

    def generar(self) -> tuple[bytes, bytes]:
        """`(llave_privada, llave_publica)`, los dos crudos."""
        ...


class Verificador(Protocol):
    """Verifica una firma ed25519 sobre la carga canonica de un mandato. Vivia
    dentro de `dominio/mandato/modelo.py`: es un puerto, no parte de la
    entidad (Fase 2 del refactor)."""

    def verifica(self, firma: bytes, carga: bytes, llave_publica: bytes) -> bool: ...
