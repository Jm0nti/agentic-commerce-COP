"""Errores con tipo, no cadenas formateadas.

Hoy todo es `BovedaError` con un mensaje, y algunos casos vuelven dentro de un
recibo como `motivo="error_pasarela: Wompi 422: {...}"` (`nucleo.py:377`). En
`recibos.jsonl` hay una fila exactamente asi.

El problema no es estetico. Un agente que recibe eso no puede decidir que hacer
sin parsear texto, y "fondos insuficientes" (reintentar mas tarde) y "mandato
vencido" (pedir uno nuevo) son respuestas opuestas que hoy son la misma cadena.

Cada error lleva `reintentable` porque esa es la pregunta que el agente hace
primero, y `detalle_proveedor` para no perder el diagnostico crudo -- que fue lo
que se estaba tirando cuando `afe_decision` no llegaba al recibo.
"""

from __future__ import annotations

from typing import Any


class ErrorDeDominio(Exception):
    """Raiz. Nada del dominio levanta algo que no herede de aqui."""

    reintentable: bool = False

    def __init__(self, mensaje: str, detalle_proveedor: dict[str, Any] | None = None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle_proveedor = detalle_proveedor or {}

    def to_json(self) -> dict[str, Any]:
        return {
            "tipo": type(self).__name__,
            "mensaje": self.mensaje,
            "reintentable": self.reintentable,
            "detalle_proveedor": self.detalle_proveedor,
        }


# -- mandato ---------------------------------------------------------------- #


class ErrorDeMandato(ErrorDeDominio):
    pass


class MandatoDesconocido(ErrorDeMandato):
    pass


class MandatoVencido(ErrorDeMandato):
    """Pedir uno nuevo. No es reintentable: el tiempo no vuelve."""


class FirmaInvalida(ErrorDeMandato):
    """Nunca reintentable, y siempre digno de una anotacion en la bitacora."""


class MandatoDeOtroAmbiente(ErrorDeMandato):
    """Un mandato de sandbox presentado en produccion, o al reves."""


class PropuestaInvalida(ErrorDeMandato):
    """`EmitirMandato` (etapa 5) con una `PropuestaDeMandato` que no calza
    con el carrito que dice referenciar -- por ejemplo, `comercio_id`
    distinto del que tiene el `Carrito` guardado. Nunca deberia pasar si la
    propuesta viene de `NavegarCatalogo.armar_carrito`; si pasa, alguien
    arma una propuesta a mano con datos que no coinciden."""


class PropuestaDesconocida(ErrorDeMandato):
    """`RepositorioPropuestas.obtener` (etapa 6) con un `propuesta_id` que no
    existe -- en la practica, un id inventado a mano, o una propuesta que
    `armar_carrito` guardo en un adaptador en memoria que ya se reinicio.
    Es al `propuesta_id` lo que `CarritoDesconocido` es al `carrito_id`: el
    mismo argumento (`RepositorioCarritos`, mas arriba) aplicado a la otra
    mitad de lo que `EmitirMandato` tiene que volver a buscar por su cuenta
    en vez de aceptar por parametro."""


class SinMedioDePagoVivo(ErrorDeMandato):
    """`EmitirMandato` sin un `MedioDePagoRef` vivo para el titular en este
    ambiente. No hay contra que firmar: primero hay que enrolar
    (`aplicacion/enrolar_medio.py`)."""


class SinMedioVinculadoAlComercio(ErrorDeMandato):
    """`EmitirMandato` (multi-comercio) con medios vivos, pero NINGUNO
    vinculado al `comercio_id` de la propuesta -- distinto de
    `SinMedioDePagoVivo`: aca el titular ya enrolo un medio (con OTRO
    comercio, o con ninguno todavia), pero un `payment_source_id` de Wompi
    esta atado al comercio (a la llave publica) que lo creo, no es portable
    entre comercios aunque los tres usen Wompi. Hace falta vincular este
    comercio especifico antes de poder firmar -- un enrolamiento mas,
    dirigido a `comercio_id` (`aplicacion/enrolar_medio.py`).

    Se distingue de `SinMedioDePagoVivo` a proposito: el agente (o quien
    reciba el error) necesita saber si hay que enrolar por primera vez o
    solo vincular un comercio nuevo con un medio que ya existe -- son dos
    situaciones distintas y la UI de cada una es distinta."""


# -- limites ---------------------------------------------------------------- #


class LimiteExcedido(ErrorDeDominio):
    pass


class TopeDuroExcedido(LimiteExcedido):
    """El guardarrail. Nunca se apaga y nunca es reintentable."""


class TopeDiarioAgotado(LimiteExcedido):
    """Manana si. Por eso es el unico limite reintentable."""

    reintentable = True


class MandatoAgotado(LimiteExcedido):
    """Se acabaron los usos o el tope acumulado."""


# -- pasarela --------------------------------------------------------------- #


class ErrorDePasarela(ErrorDeDominio):
    pass


class PasarelaNoDisponible(ErrorDePasarela):
    """Red, timeout, 5xx. Reintentar es correcto -- y seguro, porque la
    referencia se deriva de la intencion y no cambia entre intentos."""

    reintentable = True


class CobroRechazado(ErrorDePasarela):
    """La pasarela dijo que no. El motivo esta en `detalle_proveedor`."""


class RechazadoPorAntifraude(CobroRechazado):
    """`afe_decision: DECLINE`.

    Merece su propia clase porque es el unico control del flujo que el comercio
    no puede ver, configurar ni explicarle al titular. Confundirlo con un
    rechazo por fondos hace que la PoC mida mal: la primera corrida real quedo
    detenida aqui, no en el mandato.
    """


class MedioDePagoRevocado(ErrorDePasarela):
    """La fuente ya no sirve. Hay que volver a enrolar."""


class MedioNoAprobado(ErrorDePasarela):
    """El titular no acepto el push a tiempo, o la pasarela no dejo el token
    en `APPROVED` (etapa 5, `aplicacion/enrolar_medio.py`). Igual que en la
    v1 (`boveda/enrolamiento.py`: "sin aceptacion del titular no hay fuente
    de pago"), no es reintentable con los mismos datos: hay que volver a
    empezar el enrolamiento."""


class MedioNoRegistrado(ErrorDePasarela):
    """`RevocarMedio` con una referencia que `RepositorioMedios.vivos` no
    reconoce para ese titular. Mismo espiritu que la guarda de
    `boveda/enrolamiento.py:revocar` -- revocar a ciegas puede apagar la
    fuente equivocada."""


class ComercioSinCredencialesWompi(ErrorDePasarela):
    """`SelectorDePasarela.para(comercio_id)` (multi-comercio) con
    `AGORA_PASARELA=wompi` y un `comercio_id` que no aparece en el registro
    de credenciales (`agora_datos/secretos/comercios_wompi.json`). Nunca
    reintentable con los mismos datos -- hace falta agregar las credenciales
    de ese comercio antes de volver a intentar."""


# -- consumo ------------------------------------------------------------ #


class ErrorDeConsumo(ErrorDeDominio):
    pass


class ReservaNoEncontrada(ErrorDeConsumo):
    """`EjecutarIntencion.retomar` (etapa 4) sobre una intencion sin una
    reserva pendiente viva -- ya se resolvio (por `ConciliarEvento`, o por un
    `retomar` anterior), o nunca existio. No es reintentable con los mismos
    datos: retomar de nuevo la misma intencion no hace aparecer una reserva
    que ya no esta."""


# -- catalogo ------------------------------------------------------------- #


class ErrorDeCatalogo(ErrorDeDominio):
    pass


class ComercioDesconocido(ErrorDeCatalogo):
    """`buscar_productos`/`ver_producto` con un `comercio_id` que
    `RepositorioCatalogo` no reconoce. En la practica solo pasa si alguien
    inventa un id a mano -- el agente siempre llega a este id a traves de
    `buscar_comercios`."""


class ProductoDesconocido(ErrorDeCatalogo):
    """`ver_producto` con un `producto_id` que no existe en el catalogo."""


class CarritoDesconocido(ErrorDeCatalogo):
    """`RepositorioCarritos.obtener` (etapa 5) con un `carrito_id` que no
    existe -- en la practica, solo si alguien inventa un id a mano o si
    `EmitirMandato` recibe una `PropuestaDeMandato` mas vieja que el proceso
    que la armo (memoria, no sqlite, en esta etapa)."""


class ProductoDeOtroComercio(ErrorDeCatalogo):
    """`NavegarCatalogo.armar_carrito` con un producto cuyo `comercio_id` no
    es el del carrito que se esta armando. Un carrito es de un solo
    comercio -- mezclar dos rompe la premisa de `Mandato.comercio_id`."""


class ProductoNoDisponible(ErrorDeCatalogo):
    """`armar_carrito` con un producto que no esta `EN_STOCK`. Un producto
    `AGOTADO` nunca deberia llegar a `ItemCarrito` (`dominio/catalogo/
    modelo.py`, docstring de `Disponibilidad`)."""


# -- estados de intencion --------------------------------------------------- #


class EstadoDesconocido(ErrorDeDominio):
    """`ConsultarEstado` (etapa 5) sobre un `intencion_id` que
    `RegistroDeEstados` nunca vio -- nunca se ejecuto una intencion con ese
    id, o el registro (en memoria en esta etapa) se reinicio."""


# -- autenticacion ----------------------------------------------------------- #


class ErrorDeAutenticacion(ErrorDeDominio):
    pass


class SinLlaveDeFirma(ErrorDeAutenticacion):
    """El titular no tiene una llave de firma ed25519 asociada.

    Antes de esta version (multi-usuario, 4 de septiembre de 2026),
    `composicion/contenedor.py` armaba UNA sola llave para todo el proceso
    con `cargar_o_generar_firmante`, generandola sola la primera vez que
    hacia falta -- cualquier `titular_id` firmaba con la misma llave. Ahora
    cada titular tiene la suya, guardada en `RepositorioLlaves`, y
    `SelectorDeFirmante.para(titular_id)` (`adaptadores/sistema/
    registro_firmantes.py:RegistroDeFirmantes`) NUNCA genera una al vuelo:
    un `titular_id` que llega hasta aca sin llave es siempre un error de
    operacion -- falta correr `scripts/crear_usuario.py`, no algo que la
    app deba resolver en silencio."""


class CredencialesInvalidas(ErrorDeAutenticacion):
    """El nombre de usuario no existe, o la contrasena no coincide con el
    hash guardado -- deliberadamente el MISMO error para los dos casos:
    distinguirlos permitiria enumerar nombres de usuario validos probando
    contra `POST /auth/iniciar-sesion` (`aplicacion/autenticacion.py:
    IniciarSesion`)."""


class SesionInvalida(ErrorDeAutenticacion):
    """La cookie de sesion de `entradas/api/` no corresponde a ninguna
    sesion viva -- nunca existio, ya expiro, o la persona cerro sesion.
    `entradas/api/app.py` la traduce a 401, nunca a 400: no es un dato mal
    formado en la peticion, es una peticion sin autenticar."""


class NombreDeUsuarioYaExiste(ErrorDeAutenticacion):
    """`aplicacion/autenticacion.py:RegistrarUsuario` (el unico camino es
    `scripts/crear_usuario.py`, no hay registro por HTTP) con un nombre de
    usuario que ya existe. Se verifica ANTES de generar la llave de firma
    nueva, para no dejar una llave huerfana sin usuario dueño si el nombre
    ya estaba tomado."""


# -- modelo de lenguaje ---------------------------------------------------- #


class ErrorDeModeloDeLenguaje(ErrorDeDominio):
    pass


class ModeloNoDisponible(ErrorDeModeloDeLenguaje):
    """Red, timeout, 5xx del proveedor. Reintentar es razonable."""

    reintentable = True


class RespuestaModeloInvalida(ErrorDeModeloDeLenguaje):
    """El modelo respondio, pero no con lo que se le pidio -- no es JSON, o
    es JSON con una forma distinta a la esperada. Nunca se acepta a medias
    ni se rellenan campos faltantes con un valor por defecto: una respuesta
    que no calza con el contrato se descarta entera, no se repara en
    silencio (`GenerarCatalogoSemilla`, etapa 5)."""


# -- recuperacion documental (migracion a agentes, etapa 2) ----------------- #


class ErrorDeRecuperacion(ErrorDeDominio):
    pass


class RecuperacionNoDisponible(ErrorDeRecuperacion):
    """El proveedor de embeddings no respondio (red, timeout, 5xx, llave
    invalida). Igual que `ModeloNoDisponible`: reintentar es razonable, y
    quien la recibe en un turno de chat (`agente/contexto_documental.py`)
    sigue sin documentacion en vez de tumbar el turno."""

    reintentable = True


class RespuestaDeEmbeddingsInvalida(ErrorDeRecuperacion):
    """El proveedor respondio, pero no con lo pedido -- menos vectores que
    textos, o vectores vacios. Mismo criterio que `RespuestaModeloInvalida`:
    se descarta entera, nunca se rellena."""
