# Línea base del refactor (Fase 0)

Tomada el 30 sep 2026 sobre `dev@5b7f30b` más los cambios de la Fase 0. Python 3.10, Linux.

- **1.140 pruebas en verde**: las 1.117 originales, 19 nuevas en `test_fronteras.py` y 4 en `test_invariantes_del_refactor.py`.
- Módulos por capa (`agora/`): dominio 10, puertos 11, aplicacion 11, agente 16, adaptadores 61, entradas 10, composicion 4. Son los mínimos de `MINIMO_DE_MODULOS_POR_CAPA`.
- Criterio de cada fase: **ningún archivo de esta tabla baja su número**. Si una prueba se mueve de archivo, se suma en el destino. El total nunca baja.

| Archivo | Pruebas |
|---|---:|
| `tests/test_adaptador_deepseek.py` | 11 |
| `tests/test_adaptador_embeddings_openai.py` | 9 |
| `tests/test_adaptador_orquestacion_langgraph.py` | 7 |
| `tests/test_adaptador_wompi.py` | 22 |
| `tests/test_agente_conversacion.py` | 5 |
| `tests/test_agente_enrutado.py` | 10 |
| `tests/test_agente_grafo_equivalencia.py` | 18 |
| `tests/test_agente_herramientas.py` | 4 |
| `tests/test_agente_nodos.py` | 53 |
| `tests/test_agente_soporte_contexto.py` | 10 |
| `tests/test_agentes_especializados.py` | 23 |
| `tests/test_api_app.py` | 15 |
| `tests/test_autenticacion.py` | 24 |
| `tests/test_buscador_documental_langchain.py` | 8 |
| `tests/test_busqueda_productos.py` | 22 |
| `tests/test_catalogo_modelo.py` | 3 |
| `tests/test_clasificador_cadena.py` | 5 |
| `tests/test_clasificador_modelo.py` | 20 |
| `tests/test_clasificador_reglas.py` | 30 |
| `tests/test_cli.py` | 3 |
| `tests/test_cli_chat_intencion.py` | 2 |
| `tests/test_composicion.py` | 13 |
| `tests/test_composicion_agente.py` | 3 |
| `tests/test_composicion_catalogo_semantico.py` | 10 |
| `tests/test_composicion_clasificador.py` | 10 |
| `tests/test_composicion_orquestacion.py` | 14 |
| `tests/test_composicion_soporte.py` | 8 |
| `tests/test_composicion_trazas.py` | 10 |
| `tests/test_conciliar_evento.py` | 7 |
| `tests/test_consultar_estado.py` | 2 |
| `tests/test_contexto_documental.py` | 16 |
| `tests/test_corpus_soporte.py` | 21 |
| `tests/test_dominio.py` | 19 |
| `tests/test_ejecutar_intencion.py` | 17 |
| `tests/test_emitir_mandato.py` | 6 |
| `tests/test_enrolar_medio.py` | 10 |
| `tests/test_firma_ed25519.py` | 3 |
| `tests/test_fronteras.py` | 464 |
| `tests/test_generar_catalogo_semilla.py` | 11 |
| `tests/test_invariantes_del_refactor.py` | 4 |
| `tests/test_libro_consumo_memoria.py` | 10 |
| `tests/test_libro_consumo_sqlite.py` | 15 |
| `tests/test_navegar_catalogo.py` | 7 |
| `tests/test_navegar_catalogo_hibrido.py` | 11 |
| `tests/test_pasarela_simulada.py` | 15 |
| `tests/test_pausa_humana.py` | 25 |
| `tests/test_puerto_orquestacion.py` | 16 |
| `tests/test_rechazar_propuesta.py` | 2 |
| `tests/test_registro_estados_memoria.py` | 2 |
| `tests/test_registro_estados_sqlite.py` | 4 |
| `tests/test_repositorio_carritos_memoria.py` | 2 |
| `tests/test_repositorio_catalogo_semilla.py` | 9 |
| `tests/test_repositorio_mandatos_memoria.py` | 4 |
| `tests/test_repositorio_mandatos_sqlite.py` | 6 |
| `tests/test_repositorio_medios_sqlite.py` | 12 |
| `tests/test_repositorio_propuestas_memoria.py` | 2 |
| `tests/test_repositorio_propuestas_sqlite.py` | 4 |
| `tests/test_revocar_medio.py` | 3 |
| `tests/test_sesiones.py` | 5 |
| `tests/test_sondeo_pagos.py` | 5 |
| `tests/test_traza_del_turno.py` | 25 |
| `tests/test_webhook_wompi.py` | 4 |
