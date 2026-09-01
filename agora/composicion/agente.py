"""El unico lugar que conoce tanto `aplicacion/` como `agente/`: arma las
seis funciones que `agente/herramientas.py:construir_herramientas` convierte
en `Herramienta`, y con eso arma el `Agente` (`agente/conversacion.py`)
contra el `ModeloDeLenguaje` real que trae el `Contenedor`.

POR QUE ESTAS FUNCIONES DE UNION VIVEN ACA Y NO EN `agente/`
----------------------------------------------------------------
`agente/herramientas.py` no puede importar `aplicacion/` sin arriesgar la
frontera que `test_fronteras.py` verifica (`docs/arquitectura-v2.md`,
seccion 2: `agente/` solo importa `dominio/` -tipos- y `puertos/`).
`composicion/` si puede -- es el unico paquete al que se le permite importar
todo. Cada funcion de aca cierra sobre un caso de uso real (`NavegarCatalogo`,
`EjecutarIntencion`, `ConsultarEstado`) y devuelve solo dicts/listas de
dicts, para que `agente/conversacion.py` nunca tenga que saber serializar un
`Producto` o una `Intencion` -- eso es trabajo de traduccion, no de
orquestacion de turnos.

`pagar()` no recibe `titular_id`: `mandato_id` y `carrito_id` ya identifican
todo lo que hace falta para cobrar (`EjecutarIntencion.obtener` resuelve el
mandato por su cuenta), asi que agregar un tercer parametro que nadie usa
seria la abstraccion especulativa que `arquitectura-v2.md` (seccion 9) pide
evitar.
"""

from __future__ import annotations

from typing import Any

from ..agente.conversacion import Agente
from ..agente.herramientas import construir_herramientas
from ..aplicacion.navegar_catalogo import ItemPedido
from ..dominio.catalogo.modelo import Comercio, Producto
from ..dominio.mandato.modelo import Intencion
from .contenedor import Contenedor


def construir_agente(contenedor: Contenedor) -> Agente | None:
    """`None` si `contenedor.modelo_lenguaje` no se armo (falta
    `DEEPSEEK_API_KEY`) -- `entradas/cli/` decide que hacer con eso: avisar
    y seguir sirviendo los comandos que no dependen de un modelo de
    lenguaje (enrolar, emitir, pagar/revocar a mano)."""
    if contenedor.modelo_lenguaje is None:
        return None

    def buscar_comercios(consulta: str = "") -> list[dict[str, Any]]:
        return [
            _comercio_a_dict(c)
            for c in contenedor.navegar_catalogo.buscar_comercios(consulta)
        ]

    def buscar_productos(comercio_id: str, consulta: str = "") -> list[dict[str, Any]]:
        return [
            _producto_a_dict(p)
            for p in contenedor.navegar_catalogo.buscar_productos(comercio_id, consulta)
        ]

    def ver_producto(producto_id: str) -> dict[str, Any]:
        return _producto_a_dict(contenedor.navegar_catalogo.ver_producto(producto_id))

    def armar_carrito(
        comercio_id: str, items: list[dict[str, Any]], justificacion: str = ""
    ) -> dict[str, Any]:
        pedidos = [
            ItemPedido(producto_id=i["producto_id"], cantidad=int(i.get("cantidad", 1)))
            for i in items
        ]
        carrito, propuesta = contenedor.navegar_catalogo.armar_carrito(
            comercio_id, pedidos, justificacion=justificacion,
        )
        return {
            "carrito_id": carrito.carrito_id,
            "total_cop": carrito.total.pesos,
            "propuesta": {
                "propuesta_id": propuesta.propuesta_id,
                "carrito_id": propuesta.carrito_id,
                "comercio_id": propuesta.comercio_id,
                "monto_max_cop": propuesta.monto_max.pesos,
                "usos_max": propuesta.usos_max,
                "vigencia_minutos": propuesta.vigencia_minutos,
                "justificacion": propuesta.justificacion,
            },
            "nota": "Propuesta SIN AUTORIZAR. La persona la autoriza ella misma, "
            "fuera de esta charla, corriendo en su propia terminal: "
            f"'python -m agora.entradas.cli firmar {propuesta.propuesta_id} "
            "<su_titular_id>' (su titular_id es el que uso al enrolar su medio "
            "de pago). Ese comando le muestra el mandato_id ya firmado -- recien "
            "con ese mandato_id se puede llamar a pagar().",
        }

    def pagar(mandato_id: str, carrito_id: str) -> dict[str, Any]:
        carrito = contenedor.carritos.obtener(carrito_id)
        intencion = Intencion(
            intencion_id=contenedor.ids.nuevo("int"),
            mandato_id=mandato_id,
            comercio_id=carrito.comercio_id,
            carrito_id=carrito_id,
            monto=carrito.total,
        )
        # `carrito_hash` viene del carrito recien recuperado, nunca de un
        # argumento del modelo: es lo que hace valer el Cart Mandate cuando
        # el mandato se firmo atado a un carrito (`EmitirMandato`). Ver el
        # docstring de `EjecutarIntencion.__call__`.
        recibo = contenedor.ejecutar_intencion(intencion, carrito_hash=carrito.hash_canonico)
        resultado: dict[str, Any] = {
            "intencion_id": intencion.intencion_id,
            # `mandato_id`/`carrito_id` de vuelta en el resultado (no solo
            # dentro de la "nota"): etapa 7 (`entradas/api/sesiones.py`) los
            # necesita para armar el evento `confirmacion_pendiente` sin
            # tener que parsear texto libre -- lo mismo que ya vale para
            # "propuesta" en `armar_carrito`, un poco mas arriba.
            "mandato_id": mandato_id,
            "carrito_id": carrito_id,
            "ejecutado": recibo.ejecutado,
            "motivo": recibo.motivo,
            "esperando_confirmacion": recibo.esperando_confirmacion,
        }
        if recibo.esperando_confirmacion:
            # Igual que `armar_carrito` con `firmar` (etapa 6): el comando
            # EXACTO, no una descripcion. `retomar` nunca es herramienta del
            # agente -- resolver un CONFIRMAR es decision humana, igual que
            # firmar (`agente/herramientas.py`) -- asi que quien lo corre es
            # siempre la persona, en otra terminal.
            resultado["nota"] = (
                "Pago SIN CONFIRMAR: quedo esperando confirmacion humana. La "
                "persona la resuelve ELLA MISMA, en su propia terminal, corriendo: "
                f"'python -m agora.entradas.cli retomar {intencion.intencion_id} "
                f"{mandato_id} {carrito_id}'. Con AGORA_PERSISTENCIA=sqlite, en "
                "cuanto lo corra podes volver a llamar a consultar_estado y ya "
                "va a reflejar el resultado -- no hace falta que ella misma te "
                "avise, pero si te dice que ya confirmo, consulta el estado antes "
                "de responder."
            )
        return resultado

    def consultar_estado(intencion_id: str) -> dict[str, Any]:
        estado = contenedor.consultar_estado(intencion_id)
        return {
            "intencion_id": estado.intencion_id,
            "estado": estado.estado,
            "detalle": estado.detalle,
        }

    herramientas = construir_herramientas(
        buscar_comercios=buscar_comercios,
        buscar_productos=buscar_productos,
        ver_producto=ver_producto,
        armar_carrito=armar_carrito,
        pagar=pagar,
        consultar_estado=consultar_estado,
    )
    return Agente(modelo=contenedor.modelo_lenguaje, herramientas=herramientas)


def _comercio_a_dict(c: Comercio) -> dict[str, Any]:
    return {
        "comercio_id": c.comercio_id,
        "nombre": c.nombre,
        "categoria": c.categoria,
        "descripcion": c.descripcion,
    }


def _producto_a_dict(p: Producto) -> dict[str, Any]:
    return {
        "producto_id": p.producto_id,
        "comercio_id": p.comercio_id,
        "nombre": p.nombre,
        "descripcion": p.descripcion,
        "precio_cop": p.precio.pesos,
        "disponibilidad": p.disponibilidad.value,
    }
