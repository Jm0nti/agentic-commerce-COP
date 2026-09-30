"""Fabrica comercios y productos simulados con un `ModeloDeLenguaje`, para
alimentar `adaptadores/catalogo/semilla/` (etapa 5).

POR QUE UN CASO DE USO Y NO SOLO UN SCRIPT
--------------------------------------------
`scripts/generar_catalogo_semilla.py` lee `os.environ`, arma el adaptador de
DeepSeek y escribe el archivo -- es el composition root de este comando, igual
que los demas scripts de una sola corrida en `scripts/`. Pero la parte que
decide que pedirle al
modelo y como validar lo que contesta no es ceremonia de arranque: es una
regla de negocio ("un comercio simulado necesita nombre, categoria y al menos
un producto disponible") que tiene sentido probar sola, sin tocar red, y sin
un CLI de por medio. Por eso vive aqui, en `aplicacion/`, detras del puerto
`ModeloDeLenguaje` -- exactamente como `EjecutarIntencion` vive detras de
`PasarelaDePagos`.

NUNCA SE ACEPTA UNA RESPUESTA A MEDIAS
-----------------------------------------
Si DeepSeek devuelve JSON invalido, o JSON valido con la forma equivocada, o
un precio negativo, `RespuestaModeloInvalida` se levanta con el motivo exacto
y el crudo de la respuesta adjunto -- nunca se rellena un campo faltante con
un default silencioso ni se descarta solo el producto problematico. Es el
mismo principio que `dominio/mandato/modelo.py` aplica a una firma que no
valida: categorico, no probabilistico. Datos fabricados a medias son peores
que ningun dato, porque parecen confiables.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..model.catalogo.modelo import Comercio, Disponibilidad, Producto
from ..model.commons.dinero import Dinero
from ..model.commons.errores import RespuestaModeloInvalida
from ..model.agente.gateways.modelo_lenguaje import ModeloDeLenguaje
from ..model.commons.gateways.sistema import GeneradorIds

SISTEMA = """Sos un generador de datos de prueba para una demo de comercio \
electronico agentico en Colombia. Inventas UN comercio ficticio y sus \
productos, con nombres, descripciones y precios en pesos colombianos (COP) \
realistas para el mercado colombiano de 2026. Los comercios y productos son \
simulados -- no existen de verdad, no uses marcas reales. Respondes \
UNICAMENTE con un objeto JSON, sin texto antes ni despues, con esta forma \
exacta:

{
  "comercio": {"nombre": "...", "descripcion": "..."},
  "productos": [
    {
      "nombre": "...",
      "descripcion": "...",
      "precio_cop": 12345,
      "disponibilidad": "en_stock" | "agotado" | "pedido_anticipado"
    }
  ]
}

"precio_cop" es un entero en pesos colombianos, sin puntos ni separadores. \
No agregues campos que no esten en el ejemplo."""

_DISPONIBILIDADES_VALIDAS = {d.value for d in Disponibilidad}


@dataclass(frozen=True)
class ComercioGenerado:
    comercio: Comercio
    productos: tuple[Producto, ...]


class GenerarCatalogoSemilla:
    def __init__(self, modelo: ModeloDeLenguaje, ids: GeneradorIds) -> None:
        self._modelo = modelo
        self._ids = ids

    def __call__(self, categoria: str, cantidad_productos: int = 4) -> ComercioGenerado:
        if cantidad_productos < 1:
            raise ValueError("cantidad_productos tiene que ser al menos 1")

        crudo = self._modelo.generar(SISTEMA, self._instruccion(categoria, cantidad_productos))
        return self._parsear(crudo, categoria)

    # -- privados ------------------------------------------------------- #

    def _instruccion(self, categoria: str, cantidad_productos: int) -> str:
        return (
            f"Inventa un comercio colombiano de la categoria '{categoria}' "
            f"con exactamente {cantidad_productos} productos."
        )

    def _parsear(self, crudo: str, categoria: str) -> ComercioGenerado:
        try:
            datos = json.loads(crudo)
        except json.JSONDecodeError as exc:
            raise RespuestaModeloInvalida(
                f"DeepSeek no devolvio JSON valido: {exc}",
                detalle_proveedor={"crudo": crudo[:500]},
            ) from exc

        comercio_bruto = self._campo(datos, "comercio", dict, crudo)
        nombre_comercio = self._campo(comercio_bruto, "nombre", str, crudo)
        descripcion_comercio = comercio_bruto.get("descripcion", "")

        productos_brutos = self._campo(datos, "productos", list, crudo)
        if not productos_brutos:
            raise RespuestaModeloInvalida(
                "DeepSeek devolvio un comercio sin productos",
                detalle_proveedor={"crudo": crudo[:500]},
            )

        comercio_id = self._ids.nuevo("com")
        comercio = Comercio(
            comercio_id=comercio_id,
            nombre=nombre_comercio,
            categoria=categoria,
            descripcion=descripcion_comercio,
        )
        productos = tuple(
            self._producto(comercio_id, categoria, p, crudo) for p in productos_brutos
        )
        return ComercioGenerado(comercio, productos)

    def _producto(
        self, comercio_id: str, categoria: str, bruto: Any, crudo: str
    ) -> Producto:
        if not isinstance(bruto, dict):
            raise RespuestaModeloInvalida(
                f"un producto no es un objeto JSON: {bruto!r}",
                detalle_proveedor={"crudo": crudo[:500]},
            )
        nombre = self._campo(bruto, "nombre", str, crudo)
        descripcion = bruto.get("descripcion", "")
        precio_cop = self._campo(bruto, "precio_cop", int, crudo)
        if precio_cop <= 0:
            raise RespuestaModeloInvalida(
                f"'{nombre}' tiene precio_cop={precio_cop} -- tiene que ser positivo",
                detalle_proveedor={"crudo": crudo[:500]},
            )

        disponibilidad_bruta = bruto.get("disponibilidad", Disponibilidad.EN_STOCK.value)
        if disponibilidad_bruta not in _DISPONIBILIDADES_VALIDAS:
            raise RespuestaModeloInvalida(
                f"'{nombre}' trae disponibilidad='{disponibilidad_bruta}', "
                f"esperaba una de {sorted(_DISPONIBILIDADES_VALIDAS)}",
                detalle_proveedor={"crudo": crudo[:500]},
            )

        return Producto(
            producto_id=self._ids.nuevo("prd"),
            comercio_id=comercio_id,
            nombre=nombre,
            descripcion=descripcion,
            precio=Dinero.de_pesos(precio_cop),
            categoria=categoria,
            disponibilidad=Disponibilidad(disponibilidad_bruta),
        )

    def _campo(self, contenedor: dict, clave: str, tipo: type, crudo: str) -> Any:
        if not isinstance(contenedor, dict) or clave not in contenedor:
            raise RespuestaModeloInvalida(
                f"falta el campo '{clave}' en la respuesta de DeepSeek",
                detalle_proveedor={"crudo": crudo[:500]},
            )
        valor = contenedor[clave]
        # `bool` es subclase de `int` en Python: sin esta guarda, un
        # "precio_cop": true pasaria la validacion de tipo.
        tipo_equivocado = not isinstance(valor, tipo) or (
            tipo is int and isinstance(valor, bool)
        )
        if tipo_equivocado or (tipo is str and not valor.strip()):
            raise RespuestaModeloInvalida(
                f"'{clave}' tiene el tipo o valor equivocado: {valor!r}",
                detalle_proveedor={"crudo": crudo[:500]},
            )
        return valor
