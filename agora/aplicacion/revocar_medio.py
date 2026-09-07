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

DEVUELVE `EstadoMedio`, NO UN STRING (7 sept 2026)
-----------------------------------------------------
Antes devolvia `estado.estado` a secas. Cambio porque `AdaptadorWompi.
revocar_medio` (ver su docstring) puede resolver esto en dos desenlaces
bien distintos que quien llama SI necesita distinguir: la pasarela
confirmo la anulacion de verdad (`estado="VOIDED"` u otro que Wompi
devuelva), o Wompi no tiene forma de anular esta fuente por API (Nequi) y
el medio se desactivo solo del lado de esta app -- en ese segundo caso
`estado.detalle["aviso"]` trae el texto que hay que mostrarle al titular
("todavia tenes que cancelarlo desde tu app Nequi"). Devolver solo el
string tiraria ese aviso a la basura. `entradas/cli/__main__.py:cmd_revocar`
y `entradas/api/app.py:revocar_medio` ya se actualizaron para leer
`estado.estado`/`estado.detalle` en vez de tratar el resultado como texto.
"""

from __future__ import annotations

from ..dominio.comun.errores import MedioNoRegistrado
from ..dominio.pago.modelo import MedioDePagoRef
from ..puertos.pasarela import EstadoMedio, SelectorDePasarela
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

    def __call__(self, ref: MedioDePagoRef, titular_id: str) -> EstadoMedio:
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
        # Cualquier estado que no sea "AVAILABLE" saca al medio de
        # `vivos()`/`vinculado_con()` -- "VOIDED_LOCAL" (la pasarela no pudo
        # anularlo mas alla de esta app, ver `AdaptadorWompi.revocar_medio`)
        # desactiva igual de bien que un "VOIDED" confirmado por Wompi.
        self._medios.marcar_estado(ref, estado.estado)
        self._bitacora.anotar(
            "medio_revocado",
            {
                "titular_id": titular_id, "comercio_id": comercio_id, "medio": ref.to_json(),
                "estado": estado.estado, "detalle": estado.detalle,
            },
        )
        return estado
