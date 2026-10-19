"""El corazon: el motor de pagos.

El orden de los controles no es negociable:

    1. TOPES DUROS     nunca se apagan. Constantes en codigo.
    2. RESERVA         atomica. Si no cabe, no se llama a nadie.
    3. MANDATO         esto SI se puede apagar, y apagarlo es el experimento.
    4. COBRO           devuelve PENDIENTE. No bloquea.

El paso 4 no espera el estado final: devuelve de inmediato y el desenlace
llega por `ConciliarEventoUseCase` desde el webhook.

EL PASO 3 TIENE TRES DESENLACES, NO DOS (etapa 4)
--------------------------------------------------
`Decision.BLOQUEAR` libera la reserva y se detiene: no cabe, punto.
`Decision.CONFIRMAR` (`model/mandato/politica.py`: "cabe, pero huele raro")
YA NO se comporta como un bloqueo -- hasta la etapa 3 no existia el mecanismo
para retomar, asi que el unico desenlace posible era liberar y parar. Ahora
la reserva se queda viva -- el cupo diario la sigue contando mientras se
espera a que un humano decida -- y `retomar()` la resuelve mas tarde, desde
donde sea que se le pregunte al humano (etapas 4-5: hoy nada mas de esta
sesion llama a `retomar`, pero la reserva ya no se pierde esperando).

MULTI-COMERCIO (1 de septiembre de 2026)
-----------------------------------------
Antes, `_cobrar` llamaba a una `PasarelaDePagos` fija, inyectada por
constructor -- valido mientras solo hubiera un comercio real por proceso.
Ahora recibe un `SelectorDePasarela` y resuelve la pasarela correcta en el
momento del cobro, contra `mandato.comercio_id` -- que ya esta disponible
ahi, viaja dentro de la carga firmada del mandato
(`model/mandato/modelo.py:Mandato.canonico`). No hace falta que
`Intencion`/`OrdenDeCobro` carguen el comercio por su cuenta: el mandato ya
es la fuente de verdad de a que comercio esta autorizado este cobro
(`Mandato.violaciones_contra` ya lo valida contra `intencion.comercio_id`
antes de llegar aca).

Deuda tecnica consciente: esto confia en que `mandato.medio` de verdad se
haya enrolado bajo las credenciales de `mandato.comercio_id` -- nada aca
(ni en `model/mandato/modelo.py`) verifica esa correspondencia de forma
criptografica. `EmitirMandatoUseCase` es quien la garantiza en la practica (solo
firma un mandato con un medio que `RepositorioMedios.vinculado_con` ya
asocio a ese comercio), pero un bug en otra parte del sistema que armara un
`Mandato` a mano con un medio de OTRO comercio no lo detectaria aca. Ver
`docs/utils/viabilidad-multi-comercio-wompi.md`, seccion "Amarre medio ->
comercio", por las dos opciones que se evaluaron (esta, mas liviana, y
meter `comercio_id` dentro de `MedioDePagoRef` con un mandato v3) y por que
se eligio la liviana para esta iteracion."""

from __future__ import annotations

from dataclasses import dataclass

from ...model.commons.errores import ReservaNoEncontrada
from ...model.mandato.modelo import Intencion
from ...model.mandato.politica import Decision, Dictamen, evaluar
from ...model.pago.modelo import Ambiente, EstadoCobro, OrdenDeCobro, ResultadoCobro
from ...model.pago.topes import TopesDuros
from ...model.pago.gateways.pasarela import SelectorDePasarela
from ...model.mandato.gateways.repositorios import (
    LibroDeConsumo,
    RepositorioMandatos,
    Reserva,
    TopeAgotado,
)
from ...model.pago.gateways.repositorios import RegistroDeEstados
from ...model.commons.gateways.sistema import Bitacora, Reloj


@dataclass(frozen=True)
class Recibo:
    """Lo que paso, al lado de lo que el mandato decia.

    `aprobado_pese_a_violacion` es la metrica central de la PoC y ya produjo su
    primer resultado (un cobro de 15.000
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

    @property
    def esperando_confirmacion(self) -> bool:
        """`True` mientras la reserva sigue viva a la espera de que un humano
        decida (etapa 4). Distinto de `not ejecutado` a secas: un `BLOQUEAR`
        tambien deja `ejecutado=False`, pero ahi ya no hay nada pendiente --
        la reserva se libero. Quien reciba este recibo usa esta bandera para
        saber si vale la pena ofrecerle a un humano `retomar(...)`."""
        return self.motivo == "esperando_confirmacion_humana"


class EjecutarIntencionUseCase:
    def __init__(
        self,
        mandatos: RepositorioMandatos,
        consumo: LibroDeConsumo,
        selector_pasarela: SelectorDePasarela,
        topes: TopesDuros,
        reloj: Reloj,
        bitacora: Bitacora,
        verificador,
        ambiente: Ambiente,
        correo_pagador: str,
        datos_pagador: dict[str, str],
        estados: RegistroDeEstados | None = None,
    ) -> None:
        self._mandatos = mandatos
        self._consumo = consumo
        self._selector_pasarela = selector_pasarela
        self._topes = topes
        self._reloj = reloj
        self._bitacora = bitacora
        self._verificador = verificador
        self._ambiente = ambiente
        self._correo = correo_pagador
        self._datos = datos_pagador
        # Etapa 5, opcional y con default `None` a proposito: `estados` es lo
        # que `consultar_estado` (herramienta del agente) necesita para
        # distinguir "nunca se ejecuto" de "se resolvio en RECHAZADO" -- ver
        # el docstring de `puertos.repositorios.RegistroDeEstados`. Nadie que
        # ya construya `EjecutarIntencionUseCase` sin este parametro ve cambiar su
        # comportamiento.
        self._estados = estados

    def __call__(
        self, intencion: Intencion, exigir_mandato: bool = True, carrito_hash: str | None = None,
    ) -> Recibo:
        """`carrito_hash` es lo que hace valer el Cart Mandate de AP2 en el
        momento del cobro (`model/catalogo/modelo.py`, docstring de
        `Carrito.hash_canonico`): si el `Mandato` se firmo atado a un
        carrito (`carrito_hash` no vacio, obra de `EmitirMandatoUseCase`), quien
        llame a `EjecutarIntencionUseCase` tiene que volver a calcular el hash del
        carrito que de verdad se esta cobrando -- normalmente
        `RepositorioCarritos.obtener(intencion.carrito_id).hash_canonico` --
        y pasarlo aca. Sin esto, un mandato atado a un carrito nunca podria
        ejecutarse (`Mandato.violaciones_contra` compara contra `None` y
        siempre encuentra `carrito_alterado`). Es opcional y no rompe nada
        para un mandato que nunca se ato a un carrito -- la mayoria de las
        pruebas de este archivo, que arman el `Mandato` a mano."""
        mandato = self._mandatos.obtener(intencion.mandato_id, self._ambiente)

        # 1. Topes duros. Antes que nada y sin excepcion. Ni siquiera se
        #    consulta el mandato: un monto sobre el tope no llega a evaluarse.
        if excede := self._topes.excede(intencion.monto):
            return self._detenido(intencion, excede, Dictamen(Decision.BLOQUEAR))

        # 2. Reserva atomica del cupo diario. Si no cabe, nadie se entera afuera.
        try:
            reserva = self._consumo.reservar(
                mandato, intencion.intencion_id, intencion.monto, self._topes.por_dia
            )
        except TopeAgotado as exc:
            return self._detenido(intencion, str(exc), Dictamen(Decision.BLOQUEAR))

        # 3. El mandato. Este control si se puede apagar.
        consumo = self._consumo.consumo_de(mandato.mandato_id)
        dictamen = evaluar(
            mandato, intencion, consumo, self._verificador, exigir_mandato,
            ahora=self._reloj.ahora(), carrito_hash=carrito_hash,
        )
        if dictamen.decision is Decision.BLOQUEAR:
            self._consumo.liberar(reserva)
            return self._detenido(intencion, dictamen.decision.value.lower(), dictamen)
        if dictamen.decision is Decision.CONFIRMAR:
            # La reserva se queda viva -- no se libera -- mientras se espera
            # una decision humana. La resuelve `retomar()`.
            return self._esperando(intencion, dictamen)

        # 4. Cobro. Devuelve PENDIENTE; el desenlace llega por webhook.
        return self._cobrar(intencion, mandato, dictamen, reserva)

    def retomar(
        self, intencion: Intencion, aprueba: bool, carrito_hash: str | None = None,
    ) -> Recibo:
        """Resuelve una intencion que quedo en `CONFIRMAR`, con la decision
        que un humano tomo mientras tanto.

        No confia ciegamente en el dictamen original -- que ni siquiera se
        guarda -- porque el tiempo paso: el mandato pudo vencerse, o agotarse
        por otro cobro, entre que se pidio confirmar y que el humano
        contesto. Por eso, si `aprueba` es verdadero, se vuelve a correr el
        paso 3 completo (`evaluar`) antes de cobrar, con el mismo orden de
        controles que `__call__`. Un humano que aprueba no puede saltarse un
        `BLOQUEAR` que aparecio despues.

        Pero si `evaluar` vuelve a dar `CONFIRMAR` -- lo mas probable, porque
        nada de `consumo` cambio entre las dos llamadas y la misma senal
        blanda vuelve a dispararse -- eso ya no es una pregunta nueva: un
        humano ya la contesto que si. Solo `BLOQUEAR` detiene el retomo;
        `PERMITIR` y `CONFIRMAR` (reafirmado) ambos siguen a cobro.
        """
        mandato = self._mandatos.obtener(intencion.mandato_id, self._ambiente)
        reserva = self._consumo.reserva_pendiente_de(intencion.intencion_id)
        if reserva is None:
            raise ReservaNoEncontrada(
                f"no hay una reserva pendiente de confirmacion humana para "
                f"'{intencion.intencion_id}' -- ya se resolvio, o nunca existio"
            )

        if not aprueba:
            self._consumo.liberar(reserva)
            return self._detenido(
                intencion, "rechazado_por_humano", Dictamen(Decision.CONFIRMAR)
            )

        consumo = self._consumo.consumo_de(mandato.mandato_id)
        dictamen = evaluar(
            mandato, intencion, consumo, self._verificador, exigir_mandato=True,
            ahora=self._reloj.ahora(), carrito_hash=carrito_hash,
        )
        if dictamen.decision is Decision.BLOQUEAR:
            self._consumo.liberar(reserva)
            return self._detenido(
                intencion, f"{dictamen.decision.value.lower()}_al_retomar", dictamen
            )

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
            pasarela = self._selector_pasarela.para(mandato.comercio_id)
            resultado = pasarela.cobrar(orden)
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
        if resultado.estado is EstadoCobro.APROBADO:
            self._anotar_estado(intencion.intencion_id, "aprobado", resultado.estado.value)
        elif resultado.estado is EstadoCobro.PENDIENTE:
            self._anotar_estado(intencion.intencion_id, "pendiente", resultado.estado.value)
        else:
            self._anotar_estado(intencion.intencion_id, "rechazado", resultado.estado.value)
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
        self._anotar_estado(intencion.intencion_id, "rechazado", motivo)
        return recibo

    def _esperando(self, intencion, dictamen: Dictamen) -> Recibo:
        """A diferencia de `_detenido`: aqui la reserva sigue viva. Se anota
        aparte (`"esperando_confirmacion"`, no `"detenido"`) para que la
        bitacora distinga un alto real de una pausa a la espera de un
        humano."""
        recibo = Recibo(
            ejecutado=False,
            motivo="esperando_confirmacion_humana",
            intencion=intencion,
            dictamen=dictamen,
            ambiente=self._ambiente,
        )
        self._bitacora.anotar("esperando_confirmacion", recibo)
        self._anotar_estado(
            intencion.intencion_id, "esperando_confirmacion", "esperando_confirmacion_humana"
        )
        return recibo

    def _anotar_estado(self, intencion_id: str, estado: str, detalle: str) -> None:
        if self._estados is not None:
            self._estados.fijar(intencion_id, estado, detalle)
