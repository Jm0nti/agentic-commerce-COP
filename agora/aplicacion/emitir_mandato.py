"""`EmitirMandato`: donde el humano firma. `docs/arquitectura-v2.md`, seccion
5 -- "El paso que no puede automatizarse".

    agente -> armar_carrito(...) -> PropuestaDeMandato (sin firmar)
                                            |
                                  EL HUMANO FIRMA  <- este caso de uso
                                            |
                                       Mandato (ed25519)

`agente/` nunca llama a este caso de uso: no tiene un `Firmante` (la llave
del titular no esta en su proceso -- `test_fronteras.py` lo verifica) y no
esta en `agente/herramientas.py:CATALOGO_DE_HERRAMIENTAS`. Lo llama
`entradas/cli/`, del lado del titular, con el mismo `Firmante` que
`composicion/contenedor.py` arma a partir de la llave en disco (etapa 5,
"igual que v1"). Puede ser `entradas/cli/emitir` (arma y firma en un solo
comando, para cuando el que opera la CLI YA es el humano) o
`entradas/cli/firmar` (etapa 6: firma una propuesta que ya armo OTRO
proceso -- tipicamente el agente, en una charla de `chat`).

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
`RepositorioCarritos` -- la misma copia que `NavegarCatalogo.armar_carrito`
guardo -- y calcula `carrito_hash` desde ahi, nunca desde algo que la
propuesta traiga por su cuenta. Si `EmitirMandato` confiara en un carrito
que le llega de otro lado, un agente manipulado podria hacer firmar un
carrito y presentar otro distinto: el Cart Mandate de AP2 (`dominio/catalogo/
modelo.py`, docstring de `Carrito.hash_canonico`) protege contra eso solo si
el hash sale de una fuente que el agente no controla.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from ..dominio.comun.errores import PropuestaInvalida, SinMedioDePagoVivo
from ..dominio.mandato.modelo import Mandato
from ..dominio.pago.modelo import Ambiente
from ..puertos.firma import Firmante
from ..puertos.repositorios import (
    RepositorioCarritos,
    RepositorioMandatos,
    RepositorioMedios,
    RepositorioPropuestas,
)
from ..puertos.sistema import Bitacora, GeneradorIds, Reloj


class EmitirMandato:
    def __init__(
        self,
        carritos: RepositorioCarritos,
        propuestas: RepositorioPropuestas,
        medios: RepositorioMedios,
        mandatos: RepositorioMandatos,
        firmante: Firmante,
        ids: GeneradorIds,
        reloj: Reloj,
        bitacora: Bitacora,
        ambiente: Ambiente,
    ) -> None:
        self._carritos = carritos
        self._propuestas = propuestas
        self._medios = medios
        self._mandatos = mandatos
        self._firmante = firmante
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

        vivos = self._medios.vivos(titular_id, self._ambiente)
        if not vivos:
            raise SinMedioDePagoVivo(
                f"'{titular_id}' no tiene un medio de pago vivo en "
                f"'{self._ambiente.value}' -- hay que enrolar uno primero"
            )
        # El mas reciente: `RepositorioMedios.guardar` agrega al final, asi
        # que el ultimo de la lista es el ultimo enrolado. Mismo criterio que
        # `boveda/cli.py:_fuente_por_defecto`.
        medio = vivos[-1]

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
            llave_publica=self._firmante.llave_publica(),
            categorias=propuesta.categorias,
            carrito_hash=carrito.hash_canonico,
        )
        firmado = replace(mandato, firma=self._firmante.firma(mandato.canonico()))

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
