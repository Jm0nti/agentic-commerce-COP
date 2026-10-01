"""Fase A: autorizar un medio de pago. Tres pasos reutilizables, mas
`EnrolarMedioUseCase`, que los compone con un sondeo bloqueante -- igual que
`boveda/enrolamiento.py:enrolar_nequi`, pero orquestada contra
`PasarelaDePagos` (puerto) en vez de contra `ClienteWompi` (HTTP directo) --
por eso funciona igual con la simulada (aprueba de inmediato) que con Wompi
real (token -> push -> sondeo).

    preparar_medio()          nace el token, el titular recibe el push
        |
    estado_medio_por_token()  se sondea hasta un estado final
        |
    confirmar_medio()         nace la fuente de pago (el MedioDePagoRef)
        |
    RepositorioMedios.guardar()

No cobra nada -- eso es `aplicacion/ejecutar_intencion.py`. Igual que en la
v1 (`boveda/enrolamiento.py`, docstring del modulo): enrolar es un acto del
titular, cobrar es un acto del agente, y mezclarlos en un caso de uso haria
imposible distinguir cual de los dos fallo.

`agente/` no importa este modulo: no esta en `agente/herramientas.py:
CATALOGO_DE_HERRAMIENTAS` (`enrolar` esta en la lista de `PROHIBIDAS`). Lo
llama `entradas/cli/` (bloqueando la terminal, via `EnrolarMedioUseCase`) y
`entradas/api/` (sondeando desde el navegador, via los tres pasos sueltos
de mas abajo) -- ambos del lado del titular.

MULTI-COMERCIO (1 de septiembre de 2026)
-----------------------------------------
Antes, cada paso recibia una `PasarelaDePagos` fija por constructor. Un
`payment_source_id` de Wompi esta atado al comercio (a la llave publica) que
lo creo -- no es portable entre comercios aunque todos usen Wompi -- asi que
enrolar dejo de ser "contra la pasarela del proceso" y paso a ser "contra la
pasarela DE ESTE comercio": cada paso recibe un `SelectorDePasarela` y un
`comercio_id` en el momento de la llamada, no una pasarela ya resuelta.

`IniciarEnrolamientoUseCase`/`ConsultarEnrolamientoUseCase`/`ConfirmarEnrolamientoUseCase`
resuelven `selector.para(comercio_id)` en CADA llamada -- no guardan la
pasarela resuelta entre llamadas, asi que no dependen de que el mismo
`comercio_id` se repita entre `iniciar` y `confirmar` mas alla de lo que ya
exige la logica de negocio (Wompi solo va a reconocer el token si se
consulta contra el comercio que lo creo). Quien orquesta el sondeo
(`EnrolarMedioUseCase` aca abajo, o `entradas/api/sesiones.py` para el camino
asincrono) es quien tiene que seguir mandando el mismo `comercio_id` en
cada paso.

POR QUE TRES CLASES Y NO SOLO `EnrolarMedioUseCase`
-----------------------------------------------
Una terminal puede bloquearse hasta 5 minutos esperando el push de Nequi
(`ESPERA_PUSH_SEG`); una peticion HTTP no deberia -- una conexion abierta
tanto tiempo choca con temporizadores del navegador y de cualquier proxy de
por medio, y es exactamente el problema que `puertos/pasarela.py` ya
resuelve para el cobro (nunca bloquea esperando un estado final). Por eso
cada paso de la Fase A se separa en su propia clase de una sola
responsabilidad -- `IniciarEnrolamientoUseCase`, `ConsultarEnrolamientoUseCase`,
`ConfirmarEnrolamientoUseCase` -- para que `entradas/api/` pueda sondear a su
propio ritmo (una consulta por cada vez que el navegador pregunta) sin
tener que reimplementar la logica de "que hacer con la respuesta de la
pasarela", que sigue viviendo en un solo lugar.

`EnrolarMedioUseCase` no desaparece: sigue siendo exactamente la misma clase (mismo
constructor, mismo comportamiento) que usa `entradas/cli/`, solo que por
dentro ahora compone los mismos tres pasos en vez de llamar a la pasarela
directo -- cero duplicacion de la logica de negocio entre el camino
bloqueante (CLI) y el camino asincrono (web).
"""

from __future__ import annotations

import time

from ...model.pago.modelo import Ambiente, MedioDePagoRef
from ...model.pago.gateways.pasarela import SelectorDePasarela
from ...model.pago.gateways.repositorios import RepositorioMedios
from ...model.commons.gateways.sistema import Bitacora

from ..confirmar_enrolamiento.confirmar_enrolamiento_use_case import ConfirmarEnrolamientoUseCase
from ..consultar_enrolamiento.consultar_enrolamiento_use_case import ConsultarEnrolamientoUseCase
from ..iniciar_enrolamiento.iniciar_enrolamiento_use_case import IniciarEnrolamientoUseCase

ESTADOS_FINALES_TOKEN = frozenset({"APPROVED", "DECLINED", "ERROR", "VOIDED"})
ESPERA_PUSH_SEG = 300
PAUSA_SONDEO_SEG = 3.0


class EnrolarMedioUseCase:
    """Compone los tres pasos de arriba con un sondeo bloqueante -- para la
    CLI, donde bloquear la terminal esta bien (`docs/arquitectura-v2.md`,
    seccion 9: no hay que inventar asincronia donde nadie la necesita
    todavia). Mismo comportamiento observable que antes de separar los
    pasos, salvo que ahora `comercio_id` es obligatorio: multi-comercio
    significa que "enrolar" siempre es "vincular con ESTE comercio", nunca
    un enrolamiento generico sin destino.
    """

    def __init__(
        self,
        selector_pasarela: SelectorDePasarela,
        medios: RepositorioMedios,
        bitacora: Bitacora,
        ambiente: Ambiente,
        espera_seg: float = ESPERA_PUSH_SEG,
        pausa_seg: float = PAUSA_SONDEO_SEG,
    ) -> None:
        self._iniciar = IniciarEnrolamientoUseCase(selector_pasarela, ambiente)
        self._consultar = ConsultarEnrolamientoUseCase(selector_pasarela)
        self._confirmar = ConfirmarEnrolamientoUseCase(selector_pasarela, medios, bitacora)
        self._espera_seg = espera_seg
        self._pausa_seg = pausa_seg

    def __call__(
        self, telefono: str, correo: str, titular_id: str, comercio_id: str, al_avanzar=None,
    ) -> MedioDePagoRef:
        """`al_avanzar` recibe `(etapa, detalle)` para que quien llame (la
        CLI) narre el sondeo sin que este caso de uso sepa nada de como se
        imprime -- mismo patron que `boveda/enrolamiento.py:enrolar_nequi`.
        """
        aviso = al_avanzar or (lambda *_: None)

        proceso = self._iniciar(telefono, correo, comercio_id)
        aviso("token", proceso.token)

        estado = proceso.estado
        limite = time.monotonic() + self._espera_seg
        while estado not in ESTADOS_FINALES_TOKEN and time.monotonic() < limite:
            time.sleep(self._pausa_seg)
            estado = self._consultar(proceso.token, comercio_id).estado
            aviso("sondeo", estado)

        ref = self._confirmar(proceso.token, correo, titular_id, estado, comercio_id)
        aviso("lista", "AVAILABLE")
        return ref
