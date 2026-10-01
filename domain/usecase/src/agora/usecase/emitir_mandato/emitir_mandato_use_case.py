"""`EmitirMandatoUseCase`: donde el humano firma. `docs/arquitectura-v2.md`, seccion
5 -- "El paso que no puede automatizarse".

    agente -> armar_carrito(...) -> PropuestaDeMandato (sin firmar)
                                            |
                                  EL HUMANO FIRMA  <- este caso de uso
                                            |
                                       Mandato (ed25519)

`agente/` nunca llama a este caso de uso: no tiene un `SelectorDeFirmante`
(la llave del titular no esta en su proceso -- `test_fronteras.py` lo
verifica) y no esta en `agente/herramientas.py:CATALOGO_DE_HERRAMIENTAS`.
Lo llama `entradas/cli/`, del lado del titular, resolviendo el `Firmante`
de ESE titular en el momento de firmar (multi-usuario, 4 de septiembre de
2026: `puertos/firma.py:SelectorDeFirmante`, ya no una llave unica de
proceso). Puede ser `entradas/cli/emitir` (arma y firma en un solo comando,
para cuando el que opera la CLI YA es el humano) o `entradas/cli/firmar`
(etapa 6: firma una propuesta que ya armo OTRO proceso -- tipicamente el
agente, en una charla de `chat`).

RECIBE `propuesta_id`, NO `PropuestaDeMandato`
------------------------------------------------
Igual que el carrito (parrafo de abajo), la propuesta se vuelve a buscar por
id contra `RepositorioPropuestas` en vez de aceptarse por parametro. Antes
de la etapa 6 este caso de uso recibia el objeto `PropuestaDeMandato`
directo, lo cual era seguro solo mientras "armar" y "firmar" corrian en el
mismo proceso -- en cuanto pueden ser dos procesos distintos, aceptar el
objeto por parametro significaria confiar en cualquier
monto_max/usos_max/categorias que el segundo proceso diga tener.

POR QUE VUELVE A BUSCAR EL CARRITO EN VEZ DE RECIBIRLO
--------------------------------------------------------
`propuesta.carrito_id` es solo un id. Este caso de uso lo resuelve contra
`RepositorioCarritos` -- la misma copia que `NavegarCatalogoUseCase.armar_carrito`
guardo -- y calcula `carrito_hash` desde ahi, nunca desde algo que la
propuesta traiga por su cuenta. Si `EmitirMandatoUseCase` confiara en un carrito
que le llega de otro lado, un agente manipulado podria hacer firmar un
carrito y presentar otro distinto: el Cart Mandate de AP2 (`dominio/catalogo/
modelo.py`, docstring de `Carrito.hash_canonico`) protege contra eso solo si
el hash sale de una fuente que el agente no controla.

VINCULACION POR COMERCIO (1 de septiembre de 2026)
-----------------------------------------------------
Antes de multi-comercio, "el medio de pago del titular" era ambiguo pero
inofensivo: solo existia un comercio real por proceso, asi que cualquier
medio vivo servia. Con N comercios reales de Wompi eso deja de ser cierto --
un `payment_source_id` esta atado al comercio que lo creo, asi que "tomar el
ultimo medio vivo" (el criterio viejo) podia firmar un mandato con un medio
que Wompi va a rechazar en el momento de cobrar, contra las credenciales
del comercio EQUIVOCADO, y el titular se entera recien ahi -- tarde, y con
un mensaje de error que no explica nada.

Ahora se pide especificamente el medio que el titular ya VINCULO con
`propuesta.comercio_id` (`RepositorioMedios.vinculado_con`). Si no hay
ninguno, se distingue explicitamente entre dos situaciones que un agente (o
la CLI) necesitan tratar distinto:

    SinMedioDePagoVivo          nunca enrolo nada. Hay que enrolar por
                                 primera vez (dirigido a este comercio: todo
                                 enrolamiento, con o sin historial previo,
                                 es siempre "vincular con un comercio").

    SinMedioVinculadoAlComercio ya enrolo con OTRO comercio, pero nunca con
                                 este. Hay que vincular este comercio
                                 puntual -- un enrolamiento mas, un push
                                 mas, pero solo la primera vez que se compra
                                 en el: `RepositorioMedios.vinculado_con` es
                                 lo que hace que la proxima compra en el
                                 MISMO comercio no vuelva a pedirlo.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from ...model.commons.errores import (
    PropuestaInvalida,
    SinMedioDePagoVivo,
    SinMedioVinculadoAlComercio,
)
from ...model.mandato.modelo import Mandato
from ...model.pago.modelo import Ambiente
from ...model.mandato.gateways.firma import SelectorDeFirmante
from ...model.catalogo.gateways.repositorios import RepositorioCarritos
from ...model.mandato.gateways.repositorios import RepositorioMandatos, RepositorioPropuestas
from ...model.pago.gateways.repositorios import RepositorioMedios
from ...model.commons.gateways.sistema import Bitacora, GeneradorIds, Reloj


class EmitirMandatoUseCase:
    def __init__(
        self,
        carritos: RepositorioCarritos,
        propuestas: RepositorioPropuestas,
        medios: RepositorioMedios,
        mandatos: RepositorioMandatos,
        selector_firmante: SelectorDeFirmante,
        ids: GeneradorIds,
        reloj: Reloj,
        bitacora: Bitacora,
        ambiente: Ambiente,
    ) -> None:
        self._carritos = carritos
        self._propuestas = propuestas
        self._medios = medios
        self._mandatos = mandatos
        self._selector_firmante = selector_firmante
        self._ids = ids
        self._reloj = reloj
        self._bitacora = bitacora
        self._ambiente = ambiente

    def __call__(self, propuesta_id: str, titular_id: str) -> Mandato:
        # La propuesta se busca por id, nunca se acepta como objeto por
        # parametro -- mismo argumento que el carrito, dos parrafos abajo:
        # confiar en una `PropuestaDeMandato` que le llega de afuera
        # permitiria firmar cualquier monto_max/usos_max/categorias que
        # quien llama diga tener. Ver el docstring de `RepositorioPropuestas`
        # (`puertos/repositorios.py`).
        propuesta = self._propuestas.obtener(propuesta_id)
        carrito = self._carritos.obtener(propuesta.carrito_id)
        if carrito.comercio_id != propuesta.comercio_id:
            raise PropuestaInvalida(
                f"la propuesta dice comercio '{propuesta.comercio_id}' pero el "
                f"carrito '{carrito.carrito_id}' es de '{carrito.comercio_id}'"
            )

        # Multi-comercio: no "el ultimo medio vivo" (podria ser de otro
        # comercio) sino "el medio que este titular ya vinculo con ESTE
        # comercio" -- ver el docstring del modulo.
        medio = self._medios.vinculado_con(titular_id, propuesta.comercio_id, self._ambiente)
        if medio is None:
            if not self._medios.vivos(titular_id, self._ambiente):
                raise SinMedioDePagoVivo(
                    f"'{titular_id}' no tiene un medio de pago vivo en "
                    f"'{self._ambiente.value}' -- hay que enrolar uno primero"
                )
            raise SinMedioVinculadoAlComercio(
                f"'{titular_id}' tiene medio(s) de pago vivos, pero ninguno "
                f"vinculado con el comercio '{propuesta.comercio_id}' -- hay "
                "que enrolar uno dirigido a ese comercio antes de firmar "
                "(aplicacion/enrolar_medio.py)"
            )

        # Multi-usuario: se resuelve el `Firmante` de ESTE titular recien
        # aca, al momento de firmar -- nunca uno fijo por constructor (ver
        # el docstring de `puertos.firma.SelectorDeFirmante`). Si el
        # titular nunca tuvo un usuario creado con `scripts/
        # crear_usuario.py`, esto levanta `SinLlaveDeFirma` antes de que se
        # arme ningun `Mandato`.
        firmante = self._selector_firmante.para(titular_id)

        ahora = self._reloj.ahora()
        mandato = Mandato(
            mandato_id=self._ids.nuevo("mnd"),
            titular_id=titular_id,
            medio=medio,
            comercio_id=propuesta.comercio_id,
            monto_max=propuesta.monto_max,
            # Igual que el default de la v1 (`boveda/mandato.py:emitir`): sin
            # un tope total propio, el tope total es el monto de una sola
            # transaccion. Un carrito ya es una sola compra.
            tope_total=propuesta.monto_max,
            usos_max=propuesta.usos_max,
            expira_en=ahora + timedelta(minutes=propuesta.vigencia_minutos),
            creado_en=ahora,
            llave_publica=firmante.llave_publica(),
            categorias=propuesta.categorias,
            carrito_hash=carrito.hash_canonico,
        )
        firmado = replace(mandato, firma=firmante.firma(mandato.canonico()))

        self._mandatos.guardar(firmado, self._ambiente)
        self._bitacora.anotar(
            "mandato_emitido",
            {
                "mandato_id": firmado.mandato_id,
                "titular_id": titular_id,
                "carrito_id": carrito.carrito_id,
                "propuesta_id": propuesta.propuesta_id,
                "monto_max": firmado.monto_max.to_json(),
                "ambiente": self._ambiente.value,
            },
        )
        return firmado
