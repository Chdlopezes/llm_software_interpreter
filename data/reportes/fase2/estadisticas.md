# Fase 2 — Estadísticas

Generado por `python -m src.fase2.run`. Las cifras salen de `data/fase2/splits.json`.

## 1. Reparto

| Conjunto | Software | Secciones | Proporción | Objetivo |
| --- | --- | ---: | ---: | ---: |
| `train` | demand-forecast-docs, order-workflow-api, payment-promise-gateway, vendor-stockkeeper-api, zenith-keeper | 116 | 56.3% | 60% |
| `validation` | catalog-portfolio-api, price-engine-api | 50 | 24.3% | 20% |
| `test` | 2p-revenue-optimizer-api, traffic-gate-api, unified-transaction-configs | 40 | 19.4% | 20% |

- Método: **exhaustivo**: 138 de 6,561 repartos cumplen el mínimo obligatorio; se elige el más cercano al objetivo.
- Peso: secciones aprovechables (usable + parcial, sin copias heredadas).
- Forzados a `train` (conversaciones de referencia de la fase 1): `payment-promise-gateway`, `vendor-stockkeeper-api`.
- Desempates: validation y test lo más parecidos en tamaño; test más grande; orden alfabético de la asignación.
- Grupos de software con contenido compartido: ninguno (cada software es su propio grupo).

## 2. Tipos de pregunta que permite cada conjunto

Lo importante es que en cada conjunto se puedan plantear los mismos tipos de pregunta; cuántas de cada tipo se balancea en la fase 3.

| Tipo de pregunta | `train` | `validation` | `test` |
| --- | --- | --- | --- |
| version_explicita, sin_version | sí | sí | sí |
| falta_software, software_en_historial, sin_documentos | sí | sí | sí |
| en_que_version | sí | sí | sí |
| comparacion_versiones (con diferencias reales) | sí | **no** | sí |
| comparacion_versiones (versiones idénticas: «no cambia») | sí | sí | sí |
| evidencia_parcial, sin_evidencia | sí | sí | sí |
| contradiccion | sí | sí | sí |
| preguntas sobre tablas | sí | sí | sí |
| preguntas sobre código | sí | sí | sí |
| preguntas sobre diagramas | sí | sí | sí |
| preguntas sobre OpenAPI | sí | sí | sí |
| preguntas sobre fórmulas | sí | **no** | **no** |

No se exige en todos los conjuntos (aparece en menos de 3 software): `formula`.

## 3. Cobertura por conjunto

| Concepto | `train` | `validation` | `test` |
| --- | --- | --- | --- |
| Huecos | 37 | 19 | 7 |
| Conflictos | 32 | 11 | 7 |
| Líneas de tablas | 51 | 108 | 49 |
| Líneas de código | 968 | 419 | 31 |
| Líneas de diagramas | 1365 | 74 | 81 |
| Líneas de OpenAPI | 560 | 136 | 393 |
| Líneas de fórmulas | 9 | 0 | 0 |
| Varias versiones | payment-promise-gateway, vendor-stockkeeper-api | catalog-portfolio-api | 2p-revenue-optimizer-api |
| Versiones con contenido distinto | vendor-stockkeeper-api | — | 2p-revenue-optimizer-api |
| Documentos | 37 | 21 | 16 |

## 4. Perfil de cada software

| Software | Conjunto | Secciones | Versiones | Difieren | Huecos | Conflictos | Contenido |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| demand-forecast-docs | train | 14 | 1 | no | 2 | 6 | código 159, diagramas 603, fórmulas 9 |
| order-workflow-api | train | 12 | 1 | no | 8 | 0 | tablas 18, código 139, diagramas 281 |
| payment-promise-gateway | train | 30 | 2 | no | 3 | 2 | código 201, diagramas 152 |
| vendor-stockkeeper-api | train | 43 | 4 | sí | 22 | 10 | tablas 33, código 469, diagramas 24 |
| zenith-keeper | train | 17 | 1 | no | 2 | 14 | diagramas 305, OpenAPI 560 |
| catalog-portfolio-api | validation | 44 | 2 | no | 14 | 9 | tablas 108, código 419, diagramas 74 |
| price-engine-api | validation | 6 | 1 | no | 5 | 2 | OpenAPI 136 |
| 2p-revenue-optimizer-api | test | 13 | 2 | sí | 5 | 0 | tablas 49, código 8 |
| traffic-gate-api | test | 22 | 1 | no | 1 | 7 | código 12, diagramas 81, OpenAPI 393 |
| unified-transaction-configs | test | 5 | 1 | no | 1 | 0 | código 11 |

## 5. Fugas entre conjuntos

Líneas de más de 25 caracteres que aparecen en más de un conjunto: **1**.

- `-H "Content-Type: application/json" \` (train, validation)

Documentos idénticos (mismo hash) en más de un conjunto: **0**.
