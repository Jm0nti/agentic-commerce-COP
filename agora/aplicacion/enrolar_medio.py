"""Fase A: autorizar un medio de pago. Tres pasos reutilizables, mas
`EnrolarMedio`, que los compone con un sondeo bloqueante -- igual que
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
llama `entradas/cli/` (bloqueando la terminal, via `EnrolarMedio`) y
`entradas/api/` (sondeando desde el navegador, via los tres pasos sueltos
de mas abajo) -- ambos del lado del titular.

POR QUE TRES CLASES Y NO SOLO `EnrolarMedio`
-----------------------------------------------
Una terminal puede bloquearse hasta 5 minutos esperando el push de Nequi
(`ESPERA_PUSH_SEG`); una peticion HTTP no deberia -- una conexion abierta
tanto tiempo choca con temporizadores del navegador y de cualquier proxy de
por medio, y es exactamente el problema que `puertos/pasarela.py` ya
resuelve para el cobro (nunca bloquea esperando un estado final). Por eso
cada paso de la Fase A se separa en su propia clase de una sola
responsabilidad -- `IniciarEnrolamiento`, `ConsultarEnrolamiento`,
`ConfirmarEnrolamiento` -- para que `entradas/api/` pueda sondear a su
propio ritmo (una consulta por cada vez que el navegador pregunta) sin
tener que reimplementar la logica de "que hacer con la respuesta de la
pasarela", que sigue viviendo en un solo lugar.

`EnrolarMedio` no desaparece: sigue siendo exactamente la misma clase (mismo
constructor, mismo comportamiento, mismas pruebas en `tests/
test_enrolar_medio.py`) que usa `entradas/cli/`, solo que por dentro ahora
compone los mismos tres pasos en vez de llamar a la pasarela directo -- cero
duplicacion de la logica de negocio entre el camino bloqueante (CLI) y el
camino asincrono (web).
"""

from __future__ import annotations

import time

from ..dominio.comun.errores import MedioNoAprobado
from ..dominio.pago.modelo import Ambiente, MedioDePagoRef
from ..puertos.pasarela import EstadoMedio, MedioEnProceso, PasarelaDePagos, SolicitudEnrolamiento
from ..puertos.repositorios import RepositorioMedios
from ..puertos.sistema import Bitacora

ESTADOS_FINALES_TOKEN = frozenset({"APPROVED", "DECLINED", "ERROR", "VOIDED"})
ESPERA_PUSH_SEG = 300
PAUSA_SONDEO_SEG = 3.0


class IniciarEnrolamiento:
    """Paso 1: crea el token con la pasarela y le dispara el push al
    titular. No guarda nada todavia -- no hay fuente de pago hasta que el
    titular acepte, asi que no hay nada que persistir en este paso."""

    def __init__(self, pasarela: PasarelaDePagos, ambiente: Ambiente) -> None:
        self._pasarela = pasarela
        self._ambiente = ambiente

    def __call__(self, telefono: str, correo: str) -> MedioEnProceso:
        solicitud = SolicitudEnrolamiento(
            telefono=telefono, correo=correo, ambiente=self._ambiente
        )
        return self._pasarela.preparar_medio(solicitud)


class ConsultarEnrolamiento:
    """Paso 2: un sondeo, una sola vez. Quien orqueste el ritmo (el bucle
    bloqueante de `EnrolarMedio`, o un `GET` que el navegador repite cada
    pocos segundos en `entradas/api/`) decide cuando volver a llamar --
    esta clase no sabe ni le importa si es la primera consulta o la
    numero cien."""

    def __init__(self, pasarela: PasarelaDePagos) -> None:
        self._pasarela = pasarela

    def __call__(self, token: str) -> EstadoMedio:
        return self._pasarela.estado_medio_por_token(token)


class ConfirmarEnrolamiento:
    """Paso 3: el cierre. Exige que quien llama YA sepa que el token esta
    en `APPROVED` (`estado_token`, el resultado de la ultima
    `ConsultarEnrolamiento`) -- no vuelve a sondear por su cuenta, porque
    eso agregaria una consulta que `EnrolarMedio` (mas abajo) no necesita y
    que un doble de pruebas escrito contra su secuencia exacta de llamadas
    no esperaria. Si el token esta en `APPROVED`, confirma la fuente de
    pago contra la pasarela, la guarda, y deja constancia en la bitacora.
    """

    def __init__(
        self, pasarela: PasarelaDePagos, medios: RepositorioMedios, bitacora: Bitacora
    ) -> None:
        self._pasarela = pasarela
        self._medios = medios
        self._bitacora = bitacora

    def __call__(
        self, token: str, correo: str, titular_id: str, estado_token: str
    ) -> MedioDePagoRef:
        if estado_token != "APPROVED":
            raise MedioNoAprobado(
                f"el token quedo en '{estado_token}' y no en APPROVED -- sin "
                "aceptacion del titular no hay fuente de pago"
            )

        confirmado = self._pasarela.confirmar_medio(token, correo)
        if not confirmado.disponible or confirmado.ref is None:
            raise MedioNoAprobado(
                f"la fuente de pago quedo en '{confirmado.estado}', no disponible"
            )

        self._medios.guardar(confirmado.ref, titular_id)
        self._bitacora.anotar(
            "medio_enrolado",
            {
                "titular_id": titular_id,
                "medio": confirmado.ref.to_json(),
                "estado": confirmado.estado,
            },
        )
        return confirmado.ref


class EnrolarMedio:
    """Compone los tres pasos de arriba con un sondeo bloqueante -- para la
    CLI, donde bloquear la terminal esta bien (`docs/arquitectura-v2.md`,
    seccion 9: no hay que inventar asincronia donde nadie la necesita
    todavia). Mismo constructor y mismo comportamiento observable que
    antes de separar los pasos: las pruebas de `tests/test_enrolar_medio.py`
    no cambian.
    """

    def __init__(
        self,
        pasarela: PasarelaDePagos,
        medios: RepositorioMedios,
        bitacora: Bitacora,
        ambiente: Ambiente,
        espera_seg: float = ESPERA_PUSH_SEG,
        pausa_seg: float = PAUSA_SONDEO_SEG,
    ) -> None:
        self._iniciar = IniciarEnrolamiento(pasarela, ambiente)
        self._consultar = ConsultarEnrolamiento(pasarela)
        self._confirmar = ConfirmarEnrolamiento(pasarela, medios, bitacora)
        self._espera_seg = espera_seg
        self._pausa_seg = pausa_seg

    def __call__(
        self, telefono: str, correo: str, titular_id: str, al_avanzar=None
    ) -> MedioDePagoRef:
        """`al_avanzar` recibe `(etapa, detalle)` para que quien llame (la
        CLI) narre el sondeo sin que este caso de uso sepa nada de como se
        imprime -- mismo patron que `boveda/enrolamiento.py:enrolar_nequi`.
        """
        aviso = al_avanzar or (lambda *_: None)

        proceso = self._iniciar(telefono, correo)
        aviso("token", proceso.token)

        estado = proceso.estado
        limite = time.monotonic() + self._espera_seg
        while estado not in ESTADOS_FINALES_TOKEN and time.monotonic() < limite:
            time.sleep(self._pausa_seg)
            estado = self._consultar(proceso.token).estado
            aviso("sondeo", estado)

        ref = self._confirmar(proceso.token, correo, titular_id, estado)
        aviso("lista", "AVAILABLE")
        return ref
