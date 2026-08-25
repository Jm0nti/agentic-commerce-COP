"""El corazon. Lo que hoy es `Boveda.ejecutar` (nucleo.py:337-408), partido.

El orden de los controles no es negociable y es el mismo de la v1:

    1. TOPES DUROS     nunca se apagan. Constantes en codigo.
    2. RESERVA         atomica. Si no cabe, no se llama a nadie.
    3. MANDATO         esto SI se puede apagar, y apagarlo es el experimento.
    4. COBRO           devuelve PENDIENTE. No bloquea.

La diferencia frente a la v1 esta en el paso 4: antes se hacian hasta 60
segundos de `time.sleep` esperando el estado final. Ahora se devuelve de
inmediato y el desenlace llega por `ConciliarEvento` desde el webhook -- que ya
recibias y no leias.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..dominio.comun.dinero import Dinero
from ..dominio.mandato.modelo import Intencion
from ..dominio.mandato.politica import Decision, Dictamen, evaluar
from ..dominio.pago.modelo import Ambiente, EstadoCobro, OrdenDeCobro, ResultadoCobro
from ..dominio.pago.topes import TopesDuros
from ..puertos.pasarela import PasarelaDePagos
from ..puertos.repositorios import (
    LibroDeConsumo,
    RepositorioMandatos,
    Reserva,
    TopeAgotado,
)
from ..puertos.sistema import Bitacora, Reloj


@dataclass(frozen=True)
class Recibo:
    """Lo que paso, al lado de lo que el mandato decia.

    Se conserva `aprobado_pese_a_violacion` de la v1 sin cambios: es la metrica
    central de la PoC y ya produjo su primer resultado (un cobro de 15.000
    aprobado contra un mandato que autorizaba 8.000).
    """

    ejecutado: bool
    motivo: str
    intencion: Intencion
    dictamen: Dictamen
    resultado: ResultadoCobro | None = None
    ambiente: Ambiente = Ambiente.SANDBOX

    @property
    def aprobado_pese_a_violacion(self) -> bool:
        return self.ejecutado and bool(self.dictamen.violaciones)

    @property
    def detenido_por_antifraude(self) -> bool:
        return bool(self.resultado and self.resultado.detenido_por_antifraude)


class EjecutarIntencion:
    def __init__(
        self,
        mandatos: RepositorioMandatos,
        consumo: LibroDeConsumo,
        pasarela: PasarelaDePagos,
        topes: TopesDuros,
        reloj: Reloj,
        bitacora: Bitacora,
        verificador,
        ambiente: Ambiente,
        correo_pagador: str,
        datos_pagador: dict[str, str],
    ) -> None:
        self._mandatos = mandatos
        self._consumo = consumo
        self._pasarela = pasarela
        self._topes = topes
        self._reloj = reloj
        self._bitacora = bitacora
        self._verificador = verificador
        self._ambiente = ambiente
        self._correo = correo_pagador
        self._datos = datos_pagador

    def __call__(self, intencion: Intencion, exigir_mandato: bool = True) -> Recibo:
        mandato = self._mandatos.obtener(intencion.mandato_id, self._ambiente)

        # 1. Topes duros. Antes que nada y sin excepcion. Ni siquiera se
        #    consulta el mandato: un monto sobre el tope no llega a evaluarse.
        if excede := self._topes.excede(intencion.monto):
            return self._detenido(intencion, excede, Dictamen(Decision.BLOQUEAR))

        # 2. Reserva atomica del cupo diario. Si no cabe, nadie se entera afuera.
        try:
            reserva = self._consumo.reservar(
                mandato, intencion.monto, self._topes.por_dia
            )
        except TopeAgotado as exc:
            return self._detenido(intencion, str(exc), Dictamen(Decision.BLOQUEAR))

        # 3. El mandato. Este control si se puede apagar.
        consumo = self._consumo.consumo_de(mandato.mandato_id)
        dictamen = evaluar(
            mandato, intencion, consumo, self._verificador, exigir_mandato
        )
        if dictamen.decision is not Decision.PERMITIR:
            self._consumo.liberar(reserva)
            return self._detenido(intencion, dictamen.decision.value.lower(), dictamen)

        # 4. Cobro. Devuelve PENDIENTE; el desenlace llega por webhook.
        return self._cobrar(intencion, mandato, dictamen, reserva)

    # -- privados ----------------------------------------------------------- #

    def _cobrar(self, intencion, mandato, dictamen, reserva: Reserva) -> Recibo:
        orden = OrdenDeCobro(
            intencion_id=intencion.intencion_id,
            medio=mandato.medio,
            monto=intencion.monto,
            glosa=intencion.descripcion or intencion.carrito_id,
            correo_pagador=self._correo,
            datos_pagador=self._datos,
        )
        try:
            resultado = self._pasarela.cobrar(orden)
        except Exception as exc:  # el adaptador traduce; aqui solo se libera
            self._consumo.liberar(reserva)
            return self._detenido(intencion, f"error_pasarela: {exc}", dictamen)

        # PENDIENTE deja la reserva viva: la confirma o la libera el webhook.
        if resultado.estado is EstadoCobro.APROBADO:
            self._consumo.confirmar(reserva)
        elif resultado.estado.es_final:
            self._consumo.liberar(reserva)

        recibo = Recibo(
            ejecutado=resultado.estado is EstadoCobro.APROBADO,
            motivo=resultado.estado.value,
            intencion=intencion,
            dictamen=dictamen,
            resultado=resultado,
            ambiente=self._ambiente,
        )
        self._bitacora.anotar("cobro", recibo)
        return recibo

    def _detenido(self, intencion, motivo: str, dictamen: Dictamen) -> Recibo:
        recibo = Recibo(
            ejecutado=False,
            motivo=motivo,
            intencion=intencion,
            dictamen=dictamen,
            ambiente=self._ambiente,
        )
        self._bitacora.anotar("detenido", recibo)
        return recibo
