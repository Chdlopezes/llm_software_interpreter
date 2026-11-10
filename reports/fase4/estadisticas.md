# Fase 4 — Estadísticas

Generado por `python -m src.fase4.run`. Las cifras salen de `dataset_report.json`.

## 1. Contabilidad

- Tareas planificadas en la fase 3: **412**; candidatos: **407**.
- Aceptados: **386**; rechazados: **26**. Cada tarea tiene un solo estado final.

| Etapa del rechazo | Casos |
| --- | ---: |
| duplicado | 21 |
| fase3 | 5 |

## 2. Aceptados por conjunto y situación

| Situación | `train` | `validation` | `test` |
| --- | ---: | ---: | ---: |
| version_explicita | 34 | 14 | 12 |
| sin_version | 29 | 15 | 12 |
| software_en_historial | 30 | 14 | 11 |
| en_que_version | 11 | 8 | 6 |
| comparacion_versiones | 15 | 7 | 6 |
| evidencia_parcial | 22 | 10 | 8 |
| sin_evidencia | 23 | 10 | 8 |
| contradiccion | 19 | 7 | 5 |
| falta_software | 14 | 6 | 5 |
| sin_documentos | 14 | 6 | 5 |
| **Total** | **211** | **97** | **78** |

## 3. Idioma, tipo de evidencia y software

| Conjunto | es | en | texto | tabla | codigo | diagrama | especificacion | formula |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `train` | 162 | 49 | 138 | 28 | 58 | 29 | 21 | 2 |
| `validation` | 77 | 20 | 54 | 31 | 34 | 6 | 12 | 0 |
| `test` | 65 | 13 | 40 | 17 | 5 | 7 | 17 | 0 |

- `train`: demand-forecast-docs (38), order-workflow-api (35), payment-promise-gateway (41), vendor-stockkeeper-api (66), zenith-keeper (31)
- `validation`: catalog-portfolio-api (83), price-engine-api (14)
- `test`: 2p-revenue-optimizer-api (34), traffic-gate-api (36), unified-transaction-configs (8)

## 4. Longitud en tokens (Qwen/Qwen3.5-4B, presupuesto 32768)

| Conjunto | Mediana | p95 | Máximo | Supervisados (mediana) | Tokens totales |
| --- | ---: | ---: | ---: | ---: | ---: |
| `train` | 6649 | 22695 | 23156 | 259 | 1904402 |
| `validation` | 11109 | 21214 | 21323 | 253 | 1150256 |
| `test` | 4642 | 10357 | 10534 | 255 | 454627 |

## 5. Revisión humana

- Validation y test: **175** aprobados, **0** rechazados, **0** pendientes.
- Train no se revisa por completo; `no_aplica` significa que no tiene revisión humana.

## 6. Duplicados eliminados

- `test-software_en_historial-009`: duplicado de test-software_en_historial-004: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.50)
- `train-comparacion_versiones-004`: duplicado de train-comparacion_versiones-003: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.56)
- `train-en_que_version-006`: duplicado de train-en_que_version-001: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.08)
- `train-en_que_version-008`: duplicado de train-en_que_version-003: misma sección y mismo contenido (líneas citadas 0.50, respuesta 0.37)
- `train-en_que_version-009`: duplicado de train-en_que_version-004: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.41)
- `train-en_que_version-010`: duplicado de train-en_que_version-005: misma sección y mismo contenido (líneas citadas 0.50, respuesta 0.37)
- `train-en_que_version-013`: duplicado de train-en_que_version-002: misma sección y mismo contenido (líneas citadas 0.67, respuesta 0.07)
- `train-en_que_version-015`: duplicado de train-en_que_version-004: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.36)
- `train-sin_version-017`: duplicado de train-sin_version-002: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.43)
- `train-sin_version-023`: duplicado de train-sin_version-008: misma sección y mismo contenido (líneas citadas 0.25, respuesta 0.41)
- `train-sin_version-031`: duplicado de train-sin_version-019: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.79)
- `train-sin_version-032`: duplicado de train-sin_version-022: misma sección y mismo contenido (líneas citadas 0.25, respuesta 0.58)
- `train-sin_version-033`: duplicado de train-sin_version-025: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.05)
- `train-sin_version-035`: duplicado de train-sin_version-027: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.35)
- `train-software_en_historial-007`: duplicado de train-software_en_historial-005: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.48)
- `train-software_en_historial-008`: duplicado de train-software_en_historial-006: misma sección y mismo contenido (líneas citadas 0.67, respuesta 0.28)
- `train-software_en_historial-009`: duplicado de train-software_en_historial-005: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.68)
- `train-software_en_historial-010`: duplicado de train-software_en_historial-006: misma sección y mismo contenido (líneas citadas 0.67, respuesta 0.42)
- `train-software_en_historial-012`: duplicado de train-software_en_historial-005: misma sección y mismo contenido (líneas citadas 1.00, respuesta 0.01)
- `train-version_explicita-026`: duplicado de train-version_explicita-018: misma sección y mismo contenido (líneas citadas 0.80, respuesta 0.19)
- `validation-contradiccion-008`: duplicado de validation-contradiccion-004: pregunta casi igual (Jaccard 0.56)

