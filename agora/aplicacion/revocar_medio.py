"""`RevocarMedio`: el unico boton de panico que existe, igual que
`boveda/enrolamiento.py:revocar`. Apaga una fuente de pago -- no hay
"pausar" ni "bajar el tope" en el puerto, o esta viva o no.

Verifica primero que la referencia pertenezca al titular en este ambiente
(`RepositorioMedios.vivos`) antes de pedirle a la pasarela que revoque:
revocar a ciegas puede apagar la fuente equivocada, mismo argumento que la
guarda de la v1.
"""

from __future__ import annotations

from ..dominio.comun.errores import MedioNoRegistrado
from ..dominio.pago.modelo import MedioDePagoRef
from ..puertos.pasarela import PasarelaDePagos
from ..puertos.repositorios import RepositorioMedios
from ..puertos.sistema import Bitacora


class RevocarMedio:
    def __init__(
        self,
        pasarela: PasarelaDePagos,
        medios: RepositorioMedios,
        bitacora: Bitacora,
    ) -> None:
        self._pasarela = pasarela
        self._medios = medios
        self._bitacora = bitacora

    def __call__(self, ref: MedioDePagoRef, titular_id: str) -> str:
        vivos = self._medios.vivos(titular_id, ref.ambiente)
        if ref not in vivos:
            raise MedioNoRegistrado(
                f"el medio '{ref.id_externo}' no esta registrado como vivo para "
                f"'{titular_id}' en '{ref.ambiente.value}' -- revocar a ciegas "
                "puede apagar la fuente equivocada"
            )

        estado = self._pasarela.revocar_medio(ref)
        self._medios.marcar_estado(ref, estado.estado)
        self._bitacora.anotar(
            "medio_revocado",
            {"titular_id": titular_id, "medio": ref.to_json(), "estado": estado.estado},
        )
        return estado.estado
