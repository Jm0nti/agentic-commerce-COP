# Línea base del refactor

Tomada el 30 sep 2026 sobre `dev@5b7f30b` más los cambios de la Fase 0. Python 3.10, Linux.

- **Fase 0: 1.140 pruebas en verde**: las 1.117 originales, 19 nuevas en `test_fronteras.py` y 4 en `test_invariantes_del_refactor.py`.
- **Fase 1: 1.156 pruebas en verde.** Suman 13 en `test_fronteras.py` (las reglas nuevas, más las parametrizadas sobre los 3 casos de uso nuevos) y 3 en `test_pagar_carrito.py`. `aplicacion` pasa a tener 14 módulos.
- **Fase 2: 1.189 pruebas en verde.** Todas las nuevas están en `test_fronteras.py`: la regla "el modelo solo conoce la biblioteca estándar" corre sobre los 24 módulos de `domain/model`, y las reglas parametrizadas pasan de 21 archivos de `dominio/` + `puertos/` a 24 de `model/`. Módulos por capa: model 24, aplicacion 14, agente 16, adaptadores 61, entradas 10, composicion 4.
- **Fase 3: 1.205 pruebas en verde.** Las 16 nuevas están en `test_fronteras.py`: la convención de carpetas de casos de uso, el detector de un caso de uso que importa al agente y las reglas parametrizadas sobre los archivos nuevos. Módulos por capa: model 26, usecase 18, agente 14 (en `usecase/agente`), adaptadores 61, entradas 10, composicion 4.
- **Fase 4: 1.353 pruebas en verde.** Las nuevas están en `test_fronteras.py`: "cada librería vive en su adaptador" corre sobre todos los módulos y "un adaptador no conoce a otro" sobre los 52 de `driven_adapters`. Salen 4 casos de la lista de módulos de la migración a agentes, que eran `__init__.py` vacíos de familias que ya no existen. Módulos por capa: model 26, usecase 18, agente 14, driven_adapters 52 (15 módulos), entradas 10, composicion 4.
- **Fase 5: 1.386 pruebas en verde.** Las nuevas están en `test_fronteras.py`, donde las reglas de módulos ahora cubren también los entry points y el app-service. Sale 1 caso, la prueba de `EXCEPCIONES_PROVISORIAS`, porque la excepción de la CLI ya no existe. Módulos por capa: model 26, usecase 18, agente 14, driven_adapters 52, entry_points 9, app_service 11.
- **Fase 6: 1.387 pruebas en verde.** La única nueva es el detector de un adaptador que importa al agente. Las pruebas se reorganizaron en carpetas espejo (`tests/{arquitectura, model, usecase, usecase/agente, driven_adapters, entry_points, app_service}`): cada archivo conserva su número, solo cambia la ruta.
- **Fase 7: 1.387 pruebas en verde.** Solo documentación, docstrings y comentarios; cuatro cadenas de datos de prueba cambiaron de texto (un correo, una referencia y un fragmento del corpus de prueba), sin cambiar lo que prueban.
- Módulos por capa (Fase 0) (`agora/`): dominio 10, puertos 11, aplicacion 11, agente 16, adaptadores 61, entradas 10, composicion 4. Son los mínimos de `MINIMO_DE_MODULOS_POR_CAPA`.
- Criterio de cada fase: **ningún archivo de esta tabla baja su número**. Si una prueba se mueve de archivo, se suma en el destino. El total nunca baja.

Conteo vigente (Fase 6):

| Archivo | Pruebas |
|---|---:|
| `tests/app_service/test_composicion.py` | 13 |
| `tests/app_service/test_composicion_agente.py` | 3 |
| `tests/app_service/test_composicion_catalogo_semantico.py` | 10 |
| `tests/app_service/test_composicion_clasificador.py` | 10 |
| `tests/app_service/test_composicion_orquestacion.py` | 14 |
| `tests/app_service/test_composicion_soporte.py` | 8 |
| `tests/app_service/test_composicion_trazas.py` | 10 |
| `tests/arquitectura/test_fronteras.py` | 708 |
| `tests/arquitectura/test_invariantes_del_refactor.py` | 4 |
| `tests/driven_adapters/test_adaptador_deepseek.py` | 11 |
| `tests/driven_adapters/test_adaptador_embeddings_openai.py` | 9 |
| `tests/driven_adapters/test_adaptador_orquestacion_langgraph.py` | 7 |
| `tests/driven_adapters/test_adaptador_wompi.py` | 22 |
| `tests/driven_adapters/test_buscador_documental_langchain.py` | 8 |
| `tests/driven_adapters/test_busqueda_productos.py` | 22 |
| `tests/driven_adapters/test_corpus_soporte.py` | 21 |
| `tests/driven_adapters/test_firma_ed25519.py` | 3 |
| `tests/driven_adapters/test_libro_consumo_memoria.py` | 10 |
| `tests/driven_adapters/test_libro_consumo_sqlite.py` | 15 |
| `tests/driven_adapters/test_pasarela_simulada.py` | 15 |
| `tests/driven_adapters/test_registro_estados_memoria.py` | 2 |
| `tests/driven_adapters/test_registro_estados_sqlite.py` | 4 |
| `tests/driven_adapters/test_repositorio_carritos_memoria.py` | 2 |
| `tests/driven_adapters/test_repositorio_catalogo_semilla.py` | 9 |
| `tests/driven_adapters/test_repositorio_mandatos_memoria.py` | 4 |
| `tests/driven_adapters/test_repositorio_mandatos_sqlite.py` | 6 |
| `tests/driven_adapters/test_repositorio_medios_sqlite.py` | 12 |
| `tests/driven_adapters/test_repositorio_propuestas_memoria.py` | 2 |
| `tests/driven_adapters/test_repositorio_propuestas_sqlite.py` | 4 |
| `tests/entry_points/test_api_app.py` | 15 |
| `tests/entry_points/test_autenticacion.py` | 24 |
| `tests/entry_points/test_cli.py` | 3 |
| `tests/entry_points/test_cli_chat_intencion.py` | 2 |
| `tests/entry_points/test_sesiones.py` | 5 |
| `tests/entry_points/test_sondeo_pagos.py` | 5 |
| `tests/entry_points/test_webhook_wompi.py` | 4 |
| `tests/model/test_catalogo_modelo.py` | 3 |
| `tests/model/test_dominio.py` | 19 |
| `tests/model/test_puerto_orquestacion.py` | 16 |
| `tests/usecase/agente/test_agente_conversacion.py` | 5 |
| `tests/usecase/agente/test_agente_enrutado.py` | 10 |
| `tests/usecase/agente/test_agente_grafo_equivalencia.py` | 18 |
| `tests/usecase/agente/test_agente_herramientas.py` | 4 |
| `tests/usecase/agente/test_agente_nodos.py` | 53 |
| `tests/usecase/agente/test_agente_soporte_contexto.py` | 10 |
| `tests/usecase/agente/test_agentes_especializados.py` | 23 |
| `tests/usecase/agente/test_clasificador_cadena.py` | 5 |
| `tests/usecase/agente/test_clasificador_modelo.py` | 20 |
| `tests/usecase/agente/test_clasificador_reglas.py` | 30 |
| `tests/usecase/agente/test_contexto_documental.py` | 16 |
| `tests/usecase/agente/test_pausa_humana.py` | 25 |
| `tests/usecase/agente/test_traza_del_turno.py` | 25 |
| `tests/usecase/test_conciliar_evento.py` | 7 |
| `tests/usecase/test_consultar_estado.py` | 2 |
| `tests/usecase/test_ejecutar_intencion.py` | 17 |
| `tests/usecase/test_emitir_mandato.py` | 6 |
| `tests/usecase/test_enrolar_medio.py` | 10 |
| `tests/usecase/test_generar_catalogo_semilla.py` | 11 |
| `tests/usecase/test_navegar_catalogo.py` | 7 |
| `tests/usecase/test_navegar_catalogo_hibrido.py` | 11 |
| `tests/usecase/test_pagar_carrito.py` | 3 |
| `tests/usecase/test_rechazar_propuesta.py` | 2 |
| `tests/usecase/test_revocar_medio.py` | 3 |
