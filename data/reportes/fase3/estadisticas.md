# Fase 3 — Estadísticas

Generado por `python -m src.fase3.run`. Las cifras salen de `candidatos.jsonl`, `generation_log.jsonl` y `coverage_report.json`.

## 1. Resultado por conjunto

| Conjunto | Cuota | Tareas ejecutadas | verificado | revisar | omitido | error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `train` | 232 | 232 | 230 | 0 | 2 | 0 |
| `validation` | 100 | 100 | 98 | 0 | 2 | 0 |
| `test` | 80 | 80 | 79 | 0 | 1 | 0 |

## 2. Candidatos (verificados + revisar) / tareas ejecutadas / cuota, por situación

| Situación | `train` | `validation` | `test` |
| --- | ---: | ---: | ---: |
| version_explicita | 35 / 35 / 35 | 14 / 15 / 15 | 12 / 12 / 12 |
| sin_version | 35 / 35 / 35 | 15 / 15 / 15 | 12 / 12 / 12 |
| software_en_historial | 35 / 35 / 35 | 14 / 15 / 15 | 12 / 12 / 12 |
| en_que_version | 17 / 17 / 17 | 8 / 8 / 8 | 6 / 6 / 6 |
| comparacion_versiones | 16 / 17 / 17 | 7 / 7 / 7 | 6 / 6 / 6 |
| evidencia_parcial | 22 / 23 / 23 | 10 / 10 / 10 | 8 / 8 / 8 |
| sin_evidencia | 23 / 23 / 23 | 10 / 10 / 10 | 8 / 8 / 8 |
| contradiccion | 19 / 19 / 19 | 8 / 8 / 8 | 5 / 6 / 6 |
| falta_software | 14 / 14 / 14 | 6 / 6 / 6 | 5 / 5 / 5 |
| sin_documentos | 14 / 14 / 14 | 6 / 6 / 6 | 5 / 5 / 5 |

## 3. Idioma y tipo de evidencia de los candidatos

| Conjunto | es | en | texto | tabla | código | diagrama | OpenAPI | fórmula |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `train` | 178 | 52 | 153 | 29 | 60 | 30 | 21 | 2 |
| `validation` | 78 | 20 | 54 | 32 | 35 | 6 | 12 | 0 |
| `test` | 66 | 13 | 41 | 17 | 6 | 7 | 17 | 0 |

## 4. Calidad del generador

- Llamadas al generador: **464**; de ellas, correcciones por errores de código: **15**.
- Llamadas al verificador: **56** (por grupos de casos del mismo software), con **445** verificaciones; rechazos: **38** (9%).

Criterios que motivaron rechazos (una verificación puede fallar en varios):

| Criterio | Veces |
| --- | ---: |
| correccion_tecnica | 19 |
| responde_pregunta | 8 |
| respaldo_citas | 20 |
| cobertura_citas | 17 |
| evidencia_insuficiente | 10 |
| sin_abstencion_injustificada | 2 |
| consistencia | 6 |
| answer_checks_validos | 8 |

## 5. Omitidos y errores

- `test-contradiccion-005`: generador: El conflicto de la semilla enfrenta la versión que declara la especificación («version: 1.7.0», swagger.yaml L8) con la versión publicada 1.65.0, que sale de traffic-gate-api/latest/documentationTypes.json#0. Ese documento no aparece en la salida real de la herramienta. Ninguno de los documentos entregados (README.md, coverpage.md, arch.md, database.md, processes.md, waf_config.md, swagger.yaml) menciona 1.65.0 ni otra versión de la API. La respuesta solo podría citar una de las dos fuentes. Para mostrar el conflicto tendría que usar un dato que la herramienta no devolvió, y eso incumple las reglas 8 y 14. No se puede escribir un caso de contradicción válido con esta semilla.
- `train-comparacion_versiones-017`: generador: La semilla es la sección «Importance of Verification» (líneas 16-21) de important.md. Solo se puede citar en 0.0.10-stock-consumer. En 0.0.3-paused-seller, 0.0.6-ep-restock-man y latest, esas mismas líneas 16-21 están marcadas como no citables, así que no hay evidencia citable de las otras versiones con la que comparar. Además, el texto visible de la sección es idéntico en las cuatro versiones, aunque la semilla diga que difiere (igual: false). No se puede afirmar ni una diferencia ni una igualdad con citas válidas sin citar líneas no citables, cosa que está prohibida fuera de la situación contradiccion. Por eso no se puede construir un caso comparacion_versiones válido con esta semilla.
- `train-evidencia_parcial-005`: agotó los intentos; verificador: La respuesta es técnicamente correcta, pero la cita a la línea 147 solo identifica el apartado Cron History; no respalda por sí misma que falten sus campos o estructura.
- `validation-software_en_historial-002`: generador: The seed section (price-engine-api/latest/guide/general.md, lines 1-4) has nothing to ask about. Line 1 is only the heading '# General' and lines 2-4 are blank. Everything else in that document (lines 5-13: Introducción and Responsabilidades) is marked non-citable, and those lines only say 'TO DO.' anyway. No technical question can come from this seed and be answered with citable lines. A question about the swagger would be on-topic for the software but would not come from the given seed.
- `validation-version_explicita-006`: generador: La semilla es la sección «System Overview» (líneas 5-10 de catalog-portfolio-api/0.0.1-test-bench-v2a/guide/architecture/README.md), y en ella no queda nada que se pueda preguntar y citar. El único contenido técnico está en la línea 7 (microservicio REST en Java con el framework Spark, gestión de marcas, alta disponibilidad), y esa línea es no citable. Probablemente lo es porque choca con la línea 67, que dice Javalin y tampoco es citable. Las demás líneas de la sección son el título (L5), líneas vacías y una frase genérica sin datos (L9: «This section provides a comprehensive overview...»). Cualquier pregunta sobre la sección tendría que apoyarse en la línea 7, o bien salir de otra sección y dejar de corresponder a la semilla. Por eso no se puede escribir un caso version_explicita válido.

