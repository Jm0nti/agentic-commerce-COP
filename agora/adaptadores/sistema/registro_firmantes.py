"""`RegistroDeFirmantes`: implementa `puertos.firma.SelectorDeFirmante`.

A diferencia de `RegistroDePasarelas` (`adaptadores/pasarelas/registro.py`),
que SI puede resolver cualquier `comercio_id` contra una unica pasarela
simulada, este registro NUNCA tiene un "por defecto": cada titular tiene
que tener su propia llave, sin excepcion -- una llave compartida de
respaldo reproduciria exactamente el problema que esta implementacion
reemplaza (ver el docstring de `puertos.firma.SelectorDeFirmante` y de
`composicion/contenedor.py`, seccion MULTI-USUARIO). Un `titular_id` sin
llave levanta `SinLlaveDeFirma`, nunca genera una al vuelo: las llaves solo
nacen en `aplicacion/autenticacion.py:RegistrarUsuario` (y ese, a su vez,
solo lo llama `scripts/crear_usuario.py`), junto con el usuario que las va
a usar -- una decision explicita, no un accidente de implementacion.
"""

from __future__ import annotations

from ...dominio.comun.errores import SinLlaveDeFirma
from ...puertos.repositorios import RepositorioLlaves
from .firma_ed25519 import FirmanteEd25519, firmante_desde_bytes


class RegistroDeFirmantes:
    """Implementa `puertos.firma.SelectorDeFirmante`."""

    def __init__(self, llaves: RepositorioLlaves) -> None:
        self._llaves = llaves

    def para(self, titular_id: str) -> FirmanteEd25519:
        llave_privada = self._llaves.llave_privada_de(titular_id)
        if llave_privada is None:
            raise SinLlaveDeFirma(
                f"'{titular_id}' no tiene una llave de firma -- creelo con "
                "scripts/crear_usuario.py antes de poder firmar mandatos"
            )
        return firmante_desde_bytes(llave_privada)
