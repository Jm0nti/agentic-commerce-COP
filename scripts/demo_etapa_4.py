#!/usr/bin/env python3
"""Demo de consola para la etapa 4 -- sin `boveda/`, sin un servidor de
Wompi real, usando el `Contenedor` de verdad (`composicion/contenedor.py`,
`AGORA_PASARELA=simulada`).

Corre dos escenas de punta a punta:

    ESCENA 1 (PERMITIR)             intencion dentro de lo normal del mandato.
      ejecutar_intencion -> PENDIENTE -> conciliar_evento -> APROBADO

    ESCENA 2 (CONFIRMAR + retomar)  intencion que agota el mandato de una sola vez.
      ejecutar_intencion -> esperando_confirmacion_humana
      retomar(aprueba=True) -> PENDIENTE -> conciliar_evento -> APROBADO

En las dos escenas, "conciliar_evento" llama a `contenedor.conciliar_evento`
directamente en el mismo proceso, con el mismo cuerpo de evento
(`AdaptadorSimulado.evento_de(...)`) que produciria Wompi real -- es
exactamente lo que hace `entradas/webhooks/wompi.py` al recibir el POST,
solo que aqui no hace falta un servidor HTTP para verlo funcionar. Al final
el script imprime como repetir la escena 2 de verdad contra
`scripts/servir_webhook_wompi.py`.

`agora/` todavia no tiene su propio flujo de enrolamiento/firma (es etapa 5
-- ver `agora/agente/herramientas.py`, `crear_mandato()` no esta
implementada), asi que este script firma su propio mandato con un par de
llaves ed25519 generado al vuelo. Es la unica forma de ejercitar los
controles reales (`VerificadorEd25519`, `exigir_mandato=True`, el default)
sin pasar por `boveda/` -- y es deliberadamente lo mismo que hacen las
pruebas de `tests/test_ejecutar_intencion.py`, solo que impreso en vez de
verificado con `assert` silenciosos.

    python scripts/demo_etapa_4.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent
if str(RAIZ_REPO) not in sys.path:
    # Para poder correr `python scripts/demo_etapa_4.py` directo, sin
    # depender de que el paquete este instalado (mismo patron que los
    # demas scripts/).
    sys.path.insert(0, str(RAIZ_REPO))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from agora.adaptadores.pasarelas.simulada.guion import APROBADO  # noqa: E402
from agora.composicion.configuracion import ConfiguracionAgora  # noqa: E402
from agora.composicion.contenedor import construir  # noqa: E402
from agora.dominio.comun.dinero import Dinero  # noqa: E402
from agora.dominio.mandato.modelo import Intencion, Mandato  # noqa: E402
from agora.dominio.pago.modelo import Ambiente, MedioDePagoRef, Proveedor  # noqa: E402

AHORA = datetime.now(timezone.utc)


def _mandato_firmado(mandato_id: str, monto_max: int, tope_total: int, usos_max: int) -> Mandato:
    """Genera su propio par de llaves y firma de verdad -- lo que en
    produccion hace el titular al aceptar un mandato que el agente propuso
    (`agora/agente/herramientas.py:crear_mandato`, todavia sin construir)."""
    sk = Ed25519PrivateKey.generate()
    publica = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    m = Mandato(
        mandato_id=mandato_id,
        titular_id="tit_demo",
        medio=MedioDePagoRef(Proveedor.SIMULADA, Ambiente.SANDBOX, "src_demo"),
        comercio_id="com_demo",
        monto_max=Dinero.de_pesos(monto_max),
        tope_total=Dinero.de_pesos(tope_total),
        usos_max=usos_max,
        expira_en=AHORA + timedelta(hours=1),
        creado_en=AHORA,
        llave_publica=publica,
    )
    return replace(m, firma=sk.sign(m.canonico()))


def _titulo(txt: str) -> None:
    print()
    print(f"== {txt} ==")


def _resolver_y_conciliar(contenedor, recibo):
    """Cierra un cobro PENDIENTE: resuelve el desenlace del lado de la
    pasarela (lo que en Wompi real pasa solo, o cuando el titular aprueba el
    push en su banco) y lo concilia. Esto es, literalmente, lo que hace
    `entradas/webhooks/wompi.py` al recibir el POST -- aqui se llama en el
    mismo proceso en vez de por HTTP, para no necesitar un servidor."""
    pasarela = contenedor.pasarela
    pasarela.resolver_pendiente(recibo.resultado.id_externo, APROBADO)
    evento = pasarela.evento_de(recibo.resultado.id_externo)
    print(f"  evento del webhook: {json.dumps(evento)}")
    resultado = contenedor.conciliar_evento(json.dumps(evento).encode("utf-8"), {})
    print(f"  conciliar_evento -> procesado={resultado.procesado} motivo={resultado.motivo}")
    return resultado


def escena_permitir(contenedor) -> None:
    _titulo("Escena 1: PERMITIR")
    mandato = _mandato_firmado("mnd_demo_1", monto_max=20_000, tope_total=20_000, usos_max=5)
    contenedor.mandatos.guardar(mandato, Ambiente.SANDBOX)
    intencion = Intencion(
        intencion_id="int_demo_1",
        mandato_id=mandato.mandato_id,
        comercio_id=mandato.comercio_id,
        carrito_id="car_demo_1",
        monto=Dinero.de_pesos(2_000),
        descripcion="compra de prueba, bien dentro del mandato",
    )

    recibo = contenedor.ejecutar_intencion(intencion)
    print(
        f"ejecutar_intencion -> ejecutado={recibo.ejecutado} motivo={recibo.motivo} "
        f"decision={recibo.dictamen.decision.value}"
    )
    assert recibo.motivo == "PENDING", f"se esperaba PENDING, salio {recibo.motivo!r}"

    _resolver_y_conciliar(contenedor, recibo)
    consumo = contenedor.consumo.consumo_de(mandato.mandato_id)
    print(f"consumo_de(mandato) -> usos={consumo.usos} acumulado={consumo.acumulado}")


def escena_confirmar_y_retomar(contenedor) -> None:
    _titulo("Escena 2: CONFIRMAR + retomar")
    # monto == monto_max == tope_total con usos_max=1 dispara las tres
    # senales blandas a la vez: agota el mandato de una sola vez, pega
    # contra el tope por transaccion, y es el ultimo uso disponible.
    mandato = _mandato_firmado("mnd_demo_2", monto_max=8_000, tope_total=8_000, usos_max=1)
    contenedor.mandatos.guardar(mandato, Ambiente.SANDBOX)
    intencion = Intencion(
        intencion_id="int_demo_2",
        mandato_id=mandato.mandato_id,
        comercio_id=mandato.comercio_id,
        carrito_id="car_demo_2",
        monto=Dinero.de_pesos(8_000),
        descripcion="agota el mandato de una sola vez",
    )

    recibo = contenedor.ejecutar_intencion(intencion)
    print(
        f"ejecutar_intencion -> ejecutado={recibo.ejecutado} motivo={recibo.motivo} "
        f"decision={recibo.dictamen.decision.value} senales={recibo.dictamen.senales}"
    )
    assert recibo.esperando_confirmacion, "se esperaba que quedara esperando confirmacion humana"
    print(
        "  reserva_pendiente_de -> "
        f"{contenedor.consumo.reserva_pendiente_de(intencion.intencion_id)}"
    )

    print("  [aqui, en produccion, un humano ve la senal y decide -- se simula que aprueba]")
    recibo = contenedor.ejecutar_intencion.retomar(intencion, aprueba=True)
    print(f"retomar(aprueba=True) -> ejecutado={recibo.ejecutado} motivo={recibo.motivo}")
    assert recibo.motivo == "PENDING", f"se esperaba PENDING, salio {recibo.motivo!r}"

    _resolver_y_conciliar(contenedor, recibo)
    consumo = contenedor.consumo.consumo_de(mandato.mandato_id)
    print(f"consumo_de(mandato) -> usos={consumo.usos} acumulado={consumo.acumulado}")


def main() -> int:
    config = ConfiguracionAgora(
        ambiente=Ambiente.SANDBOX,
        pasarela="simulada",
        # "pendiente" en la parte local del correo es el marcador que
        # `guion.py:heuristica_por_defecto` usa para que la simulada
        # devuelva PENDIENTE en vez de resolver de una -- sin esto no
        # habria nada que conciliar por webhook, que es el punto del demo.
        correo_pagador="cliente.pendiente@correo-real.com",
    )
    contenedor = construir(config)

    escena_permitir(contenedor)
    escena_confirmar_y_retomar(contenedor)

    _titulo("Para probar el receptor HTTP de verdad, no solo conciliar en el mismo proceso")
    print(
        "Este script llama a `contenedor.conciliar_evento(...)` directo porque no necesita\n"
        "un servidor para demostrar la logica. Para verlo cruzar de verdad por\n"
        "`entradas/webhooks/wompi.py`:\n"
        "\n"
        "  1. AGORA_PERSISTENCIA=memoria no sirve para esto -- cada proceso tiene su propio\n"
        "     `LibroDeConsumo` en memoria y el webhook nunca encontraria la reserva. Arranca\n"
        "     el servidor con SQLite compartido:\n"
        "     AGORA_PERSISTENCIA=sqlite AGORA_SQLITE_PATH=agora_datos/demo.db \\\n"
        "       python scripts/servir_webhook_wompi.py\n"
        "  2. En otro proceso (mismo AGORA_SQLITE_PATH), reserva y cobra hasta el punto\n"
        "     PENDIENTE, imprime el JSON de `pasarela.evento_de(...)` como hace este script,\n"
        "     y postealo en vez de llamar a `conciliar_evento` directo:\n"
        "     curl -X POST http://127.0.0.1:8001/pagos/wompi/transacciones -d '<json>'\n"
        "  3. `curl http://127.0.0.1:8001/salud` confirma que el servidor esta arriba."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
