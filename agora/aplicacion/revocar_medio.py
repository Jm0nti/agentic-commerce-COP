"""`RevocarMedio`: el unico boton de panico que existe, igual que
`boveda/enrolamiento.py:revocar`. Apaga una fuente de pago -- no hay
"pausar" ni "bajar el tope" en el puerto, o esta viva o no.

Verifica primero que la referencia pertenezca al titular en este ambiente
(`RepositorioMedios.vivos`) antes de pedirle a la pasarela que revoque:
revocar a ciegas puede apagar la fuente equivocada, mismo argumento que la
guarda de la v1.

Multi-comercio: la revocacion tiene que pedirsele a la pasarela DEL COMERCIO
que creo ese medio -- Wompi no reconoce una fuente de pago fuera de la
cuenta que la emitio. En vez de pedirle `comercio_id` a quien llama (una
carga que el titular no deberia tener que cargar: "que comercio era" no es
algo que recuerde a la hora de revocar), se resuelve con
`RepositorioMedios.comercio_de(ref)` -- el mismo repositorio que ya guardo
esa relacion cuando `ConfirmarEnrolamiento` guardo el medio.
"""

from __future__ import annotations

from ..dominio.comun.errores import MedioNoRegistrado
from ..dominio.pago.modelo import MedioDePagoRef
from ..puertos.pasarela import SelectorDePasarela
from ..puertos.repositorios import RepositorioMedios
from ..puertos.sistema import Bitacora


class RevocarMedio:
    def __init__(
        self,
        selector_pasarela: SelectorDePasarela,
        medios: RepositorioMedios,
        bitacora: Bitacora,
    ) -> None:
        self._selector = selector_pasarela
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

        comercio_id = self._medios.comercio_de(ref)
        if comercio_id is None:
            # No deberia pasar: si esta en `vivos()` es porque `guardar` ya
            # lo registro con un comercio. Si pasa, es un medio de antes de
            # la migracion de `comercio_id` (`esquema.py`) -- no hay con que
            # comercio pedirle la revocacion a la pasarela, asi que se marca
            # sin llamarla en vez de arriesgar revocar con las credenciales
            # equivocadas.
            raise MedioNoRegistrado(
                f"el medio '{ref.id_externo}' no tiene un comercio de origen "
                "registrado -- probablemente de antes de multi-comercio; no "
                "se puede saber con que credenciales de Wompi pedir la "
                "revocacion"
            )

        estado = self._selector.para(comercio_id).revocar_medio(ref)
        self._medios.marcar_estado(ref, estado.estado)
        self._bitacora.anotar(
            "medio_revocado",
            {"titular_id": titular_id, "comercio_id": comercio_id, "medio": ref.to_json(), "estado": estado.estado},
        )
        return estado.estado
