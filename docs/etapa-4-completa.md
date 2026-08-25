# Etapa 4: ConciliarEvento, receptor HTTP vivo, y CONFIRMAR ya no bloquea

**25 de agosto de 2026.** `docs/arquitectura-v2.md`, plan de migración, fila
4: "ConciliarEvento, quitar el long-polling del camino principal" (el
long-polling ya se había quitado en la etapa 2). El resto de esta etapa
— el receptor HTTP y el mecanismo de pausa/retomo — no estaba en esa fila
con ese nivel de detalle; se le preguntó a Juan directamente antes de
construir (ver más abajo). `boveda/` sigue sin tocarse.

## Qué se construyó

| Paquete | Qué hace |
|---|---|
| `puertos/repositorios.py`, `adaptadores/persistencia/{memoria,sqlite}/libro_consumo.py` | `reserva_pendiente_de(intencion_id)`: busca una reserva viva por la intención que la originó. La usan tanto `ConciliarEvento` (la resuelve el webhook) como `EjecutarIntencion.retomar` (la resuelve un humano) — el mismo mecanismo para las dos formas de cerrar un cobro que quedó pendiente |
| `puertos/pasarela.py`, `adaptadores/pasarelas/{wompi,simulada}/adaptador.py` | `resultado_desde_evento(evento)`: traduce un evento ya verificado a `(intencion_id, ResultadoCobro)`, o `None` si no es un cobro de esta app. La convención de referencia es de cada adaptador — Wompi le puso el prefijo `agora-` a la suya en `cobrar()` (para no confundirse con tráfico viejo de `boveda/` en el mismo webhook) y aquí le quita el mismo prefijo; la simulada nunca usó prefijo y no lo espera |
| `aplicacion/conciliar_evento.py` (nuevo) | `ConciliarEvento`: valida el evento, lo traduce, busca la reserva pendiente y confirma o libera según el estado final. Nunca levanta — cada desenlace sin nada que hacer (checksum inválido, evento ajeno, reserva ya resuelta, cobro que sigue pendiente) es un `ResultadoConciliacion(procesado=False, motivo=...)`, no una excepción, para que quien reciba el HTTP siempre pueda responder 200 |
| `entradas/webhooks/wompi.py` (nuevo) | `crear_app(conciliar_evento) -> FastAPI`: factoría pura, sin `os.environ` ni construcción del `Contenedor`, para poder probarla con `TestClient` sin variables de entorno. Dos rutas: `GET /salud` y `POST /pagos/wompi/transacciones` (mismo path que `boveda/eventos.py`, porque es el que ya está configurado en el dashboard de Wompi) |
| `scripts/servir_webhook_wompi.py` (nuevo) | El composition root de este punto de entrada: lee `os.environ`, arma el `Contenedor`, llama a `crear_app` y corre `uvicorn.run`. Puerto por defecto `8001` (`boveda/eventos.py` usa `8000`, por si ambos conviven durante la migración) |
| `composicion/contenedor.py` | `Contenedor.conciliar_evento`, armado en `construir()` con la misma `pasarela`/`consumo`/`bitacora` que ya arma `ejecutar_intencion` |
| `aplicacion/ejecutar_intencion.py` | El paso 3 (política del mandato) ahora tiene tres desenlaces, no dos — ver la sección siguiente |

289 pruebas en verde (281 de antes + 8 nuevas: 6 de `ConciliarEvento`, 4 de
`entradas/webhooks/wompi.py`, más las que se sumaron a los archivos de
prueba existentes de los puertos), incluida `test_fronteras.py` contra el
árbol completo — `entradas/webhooks/` puede importar `aplicacion/` y
`composicion/`, pero no `adaptadores/`, y así quedó. Verificado corriendo la
suite completa (pytest + pyflakes + fronteras) en un entorno espejo, y
además con un arranque real de `scripts/servir_webhook_wompi.py` contra un
puerto de prueba, confirmado con `curl` contra `/salud`, antes de escribir
nada al disco de Juan.

## `CONFIRMAR` ya no se comporta como `BLOQUEAR`

Hasta la etapa 3, el paso 3 de `EjecutarIntencion` solo tenía dos caminos:
`PERMITIR` sigue a cobro, cualquier otra cosa (`BLOQUEAR` o `CONFIRMAR`)
liberaba la reserva y se detenía — porque no existía ningún mecanismo para
retomar una `CONFIRMAR` más tarde. Ahora sí:

- **`BLOQUEAR`** se sigue comportando igual: libera la reserva, se detiene.
  No cabe, punto.
- **`CONFIRMAR`** (`dominio/mandato/politica.py`: "cabe, pero huele raro")
  ya **no libera**. La reserva se queda viva — el cupo diario la sigue
  contando mientras se espera una decisión humana — y `EjecutarIntencion.
  retomar(intencion, aprueba)` la resuelve después, desde donde sea que se
  le pregunte al humano. Ningún punto de entrada de esta sesión llama a
  `retomar` todavía (eso es la UI de la etapa 5), pero la reserva ya no se
  pierde esperando.

`retomar` no confía ciegamente en el dictamen original — ni siquiera se
guarda — porque el tiempo pasó: el mandato pudo vencerse, o agotarse por
otro cobro, entre que se pidió confirmar y que el humano contestó. Por eso
vuelve a correr el paso 3 completo (`evaluar`) antes de cobrar, con el mismo
orden de controles que `__call__`. La única diferencia: si `evaluar` vuelve
a dar `CONFIRMAR` (lo más probable — nada de `consumo` cambió entre las dos
llamadas, así que la misma señal blanda vuelve a dispararse), eso ya no es
una pregunta nueva, porque un humano ya la contestó que sí. Solo un
`BLOQUEAR` — una violación real que apareció mientras se esperaba — detiene
el retomo.

Tres bugs salieron de las pruebas mientras se escribía esto, los tres
arreglados antes de entregar:

1. **`retomar` nunca lograba cobrar en el caso feliz** — la primera versión
   solo seguía a cobro si `evaluar` volvía a dar `PERMITIR`, y como se
   explicó arriba eso casi nunca pasa: la misma señal blanda que disparó
   `CONFIRMAR` la primera vez sigue ahí. Arreglado: solo `BLOQUEAR` detiene.
2. **`Recibo.esperando_confirmacion` daba `True` para un recibo ya resuelto**
   — la propiedad miraba `dictamen.decision is Decision.CONFIRMAR`, pero el
   camino de rechazo humano (`retomar(aprueba=False)`) deja el dictamen
   original en `CONFIRMAR` a propósito, por claridad de auditoría. Arreglado:
   ahora mira `motivo == "esperando_confirmacion_humana"`, una cadena que
   solo pone `_esperando()` y nada más.
3. **La revalidación no veía un mandato vencido mientras esperaba** —
   `EjecutarIntencion` nunca pasaba `ahora=self._reloj.ahora()` al llamar a
   `evaluar()`, ni en `__call__` ni en `retomar`, así que `Mandato.
   violaciones_contra` caía en su default (`datetime.now()` real) en vez de
   usar el reloj inyectado. Esto no era solo un problema de `retomar`: ya
   estaba en `__call__` desde antes de esta etapa, sin que ninguna prueba lo
   hubiera notado porque ahí `ahora` casi siempre coincide con la hora real
   de la prueba. Arreglado en los dos sitios — `evaluar()` ahora siempre
   recibe el reloj inyectado, no el del sistema.

## Decisiones que se le preguntaron a Juan antes de construir

`arquitectura-v2.md` no contestaba dos preguntas necesarias para arrancar
esta etapa:

1. **¿Construir también el receptor HTTP vivo, o solo `aplicacion/
   conciliar_evento.py` probado contra fixtures?** Respuesta: **también el
   receptor HTTP vivo**. Por eso existen `entradas/webhooks/wompi.py` y
   `scripts/servir_webhook_wompi.py`, no solo el caso de uso.
2. **¿Construir el mecanismo de pausa/retomo de `CONFIRMAR` ahora, aunque
   nada lo llame todavía esta sesión?** Respuesta: **construirlo ahora**. Por
   eso `retomar()` existe desde esta etapa y no desde la 5, aunque ningún
   punto de entrada lo invoque hasta que exista la UI de decisión humana.

## Qué no se tocó a propósito

- **Ningún punto de entrada llama a `retomar` todavía** — eso es la UI de la
  etapa 5 (el lugar donde un humano ve la `CONFIRMAR` pendiente y decide).
- **El receptor HTTP no se dejó corriendo** — se arrancó una sola vez,
  contra un puerto de prueba, para confirmar que responde, y se apagó.
  Arrancarlo de verdad y exponerlo con ngrok/cloudflared es decisión de
  Juan.
- **La URL configurada en el dashboard de Wompi no se cambió** —
  `entradas/webhooks/wompi.py` sirve la misma ruta que `boveda/eventos.py`
  a propósito, para que reemplazarlo no exija tocar el dashboard, pero el
  dashboard sigue apuntando a donde apuntaba.

## Pendiente inmediato

1. Confirmar que los archivos nuevos están en disco (llegaron por el puente
   de archivos, no por `git`).
2. `git add` + commit desde tu terminal — el puente no puede correr `git`.
3. Cuando quieras probar el receptor de verdad: `AGORA_PASARELA=wompi`
   (con las credenciales de siempre) + `python
   scripts/servir_webhook_wompi.py`, expuesto con ngrok/cloudflared igual
   que `boveda/eventos.py`. Con `AGORA_PASARELA=simulada` (el default)
   también levanta, pero sin verificar checksum de verdad — sirve para
   demo, no para producción.
4. **Etapa 5:** lo que queda en `docs/arquitectura-v2.md` — la interfaz de
   agente/humano, incluido el primer punto que de verdad llame a
   `retomar()`.
