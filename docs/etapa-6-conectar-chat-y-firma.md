# Etapa 6: conectar el carrito del chat con la firma del titular

**26 de agosto de 2026.** Cierra un hueco real encontrado probando `chat` de
punta a punta: el agente arma una propuesta (`armar_carrito`), le dice a la
persona que la autorice "fuera de esta charla", pero no existía ningún
comando que pudiera firmar *esa* propuesta desde otro proceso. `emitir`
(etapa 5) armaba su propio carrito nuevo en vez de reusar el del chat, así
que el `carrito_id` que terminaba viendo `pagar()` nunca coincidía con el
que firmó el mandato — la verificación de `carrito_hash` lo habría
rechazado por `carrito_alterado` si alguien hubiera llegado tan lejos.

## Qué cambió

**La propuesta ahora se persiste, igual que el carrito.** Nuevo puerto
`RepositorioPropuestas` (`puertos/repositorios.py`), con el mismo argumento
que ya existía para `RepositorioCarritos`: no confiar en un objeto que
llega por parámetro desde otro proceso. Adaptadores en memoria y SQLite
(`adaptadores/persistencia/{memoria,sqlite}/repositorio_propuestas.py`),
tabla `propuesta` nueva en el esquema SQLite.

**`EmitirMandato` ya no recibe una `PropuestaDeMandato`, recibe un
`propuesta_id`.** La busca por su cuenta contra `RepositorioPropuestas`,
exactamente como ya hacía con el carrito. Antes de esta etapa, aceptar el
objeto por parámetro era seguro solo porque "armar" y "firmar" corrían
siempre en el mismo proceso (`entradas/cli/emitir`); en cuanto pueden ser
dos procesos distintos, aceptarlo por parámetro habría significado confiar
en cualquier `monto_max`/`usos_max`/`categorias` que el segundo proceso
dijera tener.

**`NavegarCatalogo.armar_carrito` guarda la propuesta que devuelve.** Un
`propuestas: RepositorioPropuestas | None = None` opcional en el
constructor (retrocompatible con pruebas que no lo necesitan);
`composicion/contenedor.py` siempre lo provee.

**Nuevo comando `entradas/cli/firmar <propuesta_id> <titular>`.** Firma una
propuesta que ya armó OTRO proceso, sin rearmar ningún carrito. El
`carrito_id` que imprime es el mismo que ya tiene quien armó la propuesta
(el chat, casi siempre) — antes no había forma de llegar a esto.
`entradas/cli/emitir` sigue existiendo tal cual para cuando el humano opera
la CLI de punta a punta (arma y firma en un solo comando); por dentro ahora
pasa por el mismo camino (`propuesta.propuesta_id`, no el objeto).

**El chat le pasa a la persona el comando exacto, no una descripción
vaga.** El resultado de la herramienta `armar_carrito`
(`composicion/agente.py`) trae ahora una `nota` con el `firmar` ya armado
(`propuesta_id` incluido, solo falta el `titular_id` de la persona) en vez
de "la app te va a pedir que la autorices". `agente/politica.py` le indica
al modelo que le pase ese comando tal cual, sin resumirlo.

## Cómo se prueba

`tests/test_cli.py::test_chat_arma_propuesta_y_titular_la_firma_en_otro_proceso`
es la prueba de regresión del bug real: dos `Contenedor` separados (misma
sqlite, cero estado en común), uno arma el carrito+propuesta como lo haría
el chat, el otro firma con `cmd_firmar` y paga con el `carrito_id` que ya
tenía el primero — sin `carrito_alterado`.

`tests/test_emitir_mandato.py`, `tests/test_navegar_catalogo.py`,
`tests/test_repositorio_propuestas_memoria.py` y
`tests/test_repositorio_propuestas_sqlite.py` cubren las piezas nuevas por
separado (incluida la reconexión: una propuesta guardada por un
`RepositorioPropuestasSQLite` sobrevive a que ese objeto se destruya y otro
la vuelva a leer).

## Cómo probarlo a mano

```
python -m agora.entradas.cli enrolar --telefono 3001234567 --titular tit_1
python -m agora.entradas.cli chat
  vos> quiero comprar unos audifonos
  agente> ... armó la propuesta prp_xxxx, decíselo así: ...
```

En OTRA terminal (mismo `AGORA_SQLITE_PATH` si se usa
`AGORA_PERSISTENCIA=sqlite` — con `memoria`, el default, tiene que ser el
MISMO proceso, ver la limitación de abajo):

```
python -m agora.entradas.cli firmar prp_xxxx tit_1
```

Ese comando muestra el `mandato_id`. De vuelta en el chat, pasárselo al
agente para que llame a `pagar`.

## Limitación que queda

Con `AGORA_PERSISTENCIA=memoria` (el default), `firmar` en un proceso
aparte no va a encontrar la propuesta del chat -- `RepositorioPropuestasEnMemoria`
no sobrevive entre procesos, igual que `RepositorioCarritosEnMemoria`
(mismo motivo documentado en la etapa 3 para `carrito`). Para probar el
flujo chat -> otra terminal -> firmar de punta a punta hace falta
`AGORA_PERSISTENCIA=sqlite`.

---

## Segunda parte: `retomar` en otra terminal, y el chat que nunca se entera

**26 de agosto de 2026, mismo día, probando la primera parte de punta a
punta.** El flujo ya conectaba `armar_carrito` (chat) con `firmar` (otra
terminal). Pero en cuanto `pagar()` — casi siempre — devuelve
`esperando_confirmacion_humana` (etapa 5: un mandato cortado exacto al
carrito dispara casi siempre las señales blandas), aparecía el mismo
problema un escalón más adelante: la persona corría `retomar` en la
terminal 2 y lo aprobaba, pero el chat seguía diciendo "esperando
confirmación humana" para siempre, sin importar cuántas veces se le pidiera
`consultar_estado`.

### Por qué

Dos huecos, no uno:

1. **El chat nunca le decía a la persona qué comando de `retomar`
   correr.** `pagar()` sabe el `intencion_id` que generó, pero
   `composicion/agente.py` no se lo pasaba a la persona — el system prompt
   tampoco sabía que tenía que hacerlo. Mismo síntoma que el hueco
   original: instrucción vaga en vez de comando exacto.
2. **Aunque lo hubiera hecho, no habría servido de nada.**
   `RegistroDeEstados` (el registro que `consultar_estado` lee) se pensó en
   la etapa 5 exclusivamente en memoria — "su único consumidor es
   `consultar_estado` dentro de una misma sesión de chat" — pero eso dejó
   de ser cierto en el momento en que `retomar` (que **nunca** es
   herramienta del agente: resolver un `CONFIRMAR` es decisión humana,
   igual que firmar) pasó a correr siempre en un proceso aparte. Sin
   persistencia entre procesos, el `retomar` de la terminal 2 actualizaba
   el registro EN MEMORIA de la terminal 2, invisible para el chat.

### Qué cambió

- Nuevo adaptador `RegistroDeEstadosSQLite`
  (`adaptadores/persistencia/sqlite/registro_estados.py`, tabla
  `estado_intencion`), mismo patrón que `carrito`/`propuesta`.
  `composicion/contenedor.py` lo usa con `AGORA_PERSISTENCIA=sqlite` (el
  valor que ya tenés en tu `.env`).
- `pagar()` (`composicion/agente.py`) ahora trae una `nota` con el comando
  `retomar <intencion_id> <mandato_id> <carrito_id>` YA ARMADO cuando
  `esperando_confirmacion` es `true` — igual que `armar_carrito` con
  `firmar`.
- `agente/politica.py` le dice al modelo que pase ese comando tal cual, y
  que **vuelva a llamar a `consultar_estado`** en vez de confiar en lo que
  ya sabía, cada vez que la persona diga que confirmó o pregunte qué pasó.

### Cómo se prueba

`tests/test_composicion_agente.py::test_estado_confirmado_en_otro_proceso_se_ve_desde_consultar_estado`
es la prueba de regresión: un `Contenedor` arma el carrito y paga (queda
`esperando_confirmacion`), un `Contenedor` SEPARADO (misma sqlite) resuelve
la intención con `retomar`, y el `Contenedor` original ve `"aprobado"` sin
haber tocado nada más. Reproducido también a mano con la CLI real, tres
"terminales" (tres procesos python separados) de punta a punta.
