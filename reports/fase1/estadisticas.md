# Fase 1 — Estadísticas

Generado por `python -m src.fase1.run`. Las cifras salen de `data/fase1/`.

## 1. Catálogo

- Versión del corpus: `docs_b36991f86732`.
- Documentos: **74** (archivos de `docs_raw` sin los de navegación: `_coverpage.md`, `_sidebar.md`, `documentationTypes.json`).
- Líneas: 9,180; caracteres: 309,899.

| Software | Versión | Documentos | Líneas | Caracteres |
| --- | --- | ---: | ---: | ---: |
| 2p-revenue-optimizer-api | 0.2.2 | 3 | 120 | 6,942 |
| 2p-revenue-optimizer-api | latest | 4 | 133 | 7,633 |
| catalog-portfolio-api | 0.0.1-test-bench-v2a | 8 | 1264 | 32,912 |
| catalog-portfolio-api | latest | 8 | 1264 | 32,912 |
| demand-forecast-docs | latest | 4 | 1070 | 46,993 |
| order-workflow-api | 5.6.2-hotfix-1 | 8 | 620 | 17,453 |
| payment-promise-gateway | 0.0.10-test-crc-migration | 1 | 548 | 16,353 |
| payment-promise-gateway | latest | 1 | 548 | 16,353 |
| price-engine-api | latest | 5 | 192 | 5,265 |
| traffic-gate-api | latest | 7 | 743 | 35,768 |
| unified-transaction-configs | v0.0.2 | 2 | 50 | 1,852 |
| vendor-stockkeeper-api | 0.0.10-stock-consumer | 5 | 468 | 17,564 |
| vendor-stockkeeper-api | 0.0.3-paused-seller | 5 | 422 | 16,236 |
| vendor-stockkeeper-api | 0.0.6-ep-restock-man | 5 | 421 | 15,990 |
| vendor-stockkeeper-api | latest | 5 | 422 | 16,236 |
| zenith-keeper | 1.1.6 | 3 | 895 | 23,437 |

Documentos idénticos byte a byte entre versiones: **15 grupos**. La fase 2 debe mantener cada grupo en el mismo conjunto.

En **4 grupos** la fase 0 marcó líneas no citables distintas en el mismo texto (cada versión se auditó por separado). Se aplica la regla conservadora: una línea es no citable si lo es en cualquiera de las copias.

| Documentos idénticos | No citables propias | No citables aplicadas |
| --- | --- | --- |
| `payment-promise-gateway/0.0.10-test-crc-migration/guide/README.md`<br>`payment-promise-gateway/latest/guide/README.md` | [[538, 548]]<br>[[351, 352], [538, 548]] | [[351, 352], [538, 548]] |
| `vendor-stockkeeper-api/0.0.10-stock-consumer/guide/database.md`<br>`vendor-stockkeeper-api/0.0.3-paused-seller/guide/database.md`<br>`vendor-stockkeeper-api/0.0.6-ep-restock-man/guide/database.md`<br>`vendor-stockkeeper-api/latest/guide/database.md` | [[25, 25]]<br>[[25, 25]]<br>[]<br>[] | [[25, 25]] |
| `vendor-stockkeeper-api/0.0.3-paused-seller/guide/api.md`<br>`vendor-stockkeeper-api/0.0.6-ep-restock-man/guide/api.md`<br>`vendor-stockkeeper-api/latest/guide/api.md` | [[1, 2], [16, 18], [25, 25]]<br>[[1, 2], [16, 18], [25, 25]]<br>[[1, 2], [16, 16], [19, 19], [25, 25]] | [[1, 2], [16, 19], [25, 25]] |
| `vendor-stockkeeper-api/0.0.3-paused-seller/guide/important.md`<br>`vendor-stockkeeper-api/0.0.6-ep-restock-man/guide/important.md`<br>`vendor-stockkeeper-api/latest/guide/important.md` | [[7, 7], [16, 21], [28, 32], [131, 131], [139, 139], [231, 231], [242, 242], [250, 250]]<br>[[7, 7], [28, 32], [131, 131], [231, 231], [234, 234], [242, 242], [250, 250]]<br>[[28, 32], [131, 131], [231, 231], [242, 242], [250, 250]] | [[7, 7], [16, 21], [28, 32], [131, 131], [139, 139], [231, 231], [234, 234], [242, 242], [250, 250]] |

### Consistencia de la fase 0 entre copias idénticas

Los documentos idénticos de versiones que la fase 0 auditó por separado permiten medir cuánto varía su etiqueta cuando se audita el mismo texto en llamadas independientes al LLM.

Pares de secciones idénticas: **64**. Mismo estado final: **55** (85.9%). Distinto: **9**.

| Documento | Líneas | Estado en una copia | Estado en la otra |
| --- | --- | --- | --- |
| `payment-promise-gateway/0.0.10-test-crc-migration/guide/README.md` | 306-385 | 0.0.10-test-crc-migration: `usable` | latest: `parcial` |
| `vendor-stockkeeper-api/0.0.10-stock-consumer/guide/database.md` | 1-25 | 0.0.10-stock-consumer: `parcial` | 0.0.6-ep-restock-man: `usable` |
| `vendor-stockkeeper-api/0.0.10-stock-consumer/guide/database.md` | 1-25 | 0.0.10-stock-consumer: `parcial` | latest: `usable` |
| `vendor-stockkeeper-api/0.0.3-paused-seller/guide/database.md` | 1-25 | 0.0.3-paused-seller: `parcial` | 0.0.6-ep-restock-man: `usable` |
| `vendor-stockkeeper-api/0.0.3-paused-seller/guide/database.md` | 1-25 | 0.0.3-paused-seller: `parcial` | latest: `usable` |
| `vendor-stockkeeper-api/0.0.3-paused-seller/guide/important.md` | 16-21 | 0.0.3-paused-seller: `no_usable` | 0.0.6-ep-restock-man: `usable` |
| `vendor-stockkeeper-api/0.0.3-paused-seller/guide/important.md` | 1-8 | 0.0.3-paused-seller: `parcial` | latest: `usable` |
| `vendor-stockkeeper-api/0.0.3-paused-seller/guide/important.md` | 16-21 | 0.0.3-paused-seller: `no_usable` | latest: `usable` |
| `vendor-stockkeeper-api/0.0.6-ep-restock-man/guide/important.md` | 1-8 | 0.0.6-ep-restock-man: `parcial` | latest: `usable` |

Las líneas no citables de estas copias se unen (regla conservadora); el estado de cada sección se conserva tal como lo dejó la fase 0.

## 2. Normalización (sin mover líneas)

| Transformación | Líneas | Documentos |
| --- | ---: | ---: |
| `entidad_html` | 402 | 9 |
| `secreto` | 8 | 1 |
| `insignia` | 7 | 3 |
| `pestana_docsify` | 3 | 3 |
| `marca_docsify` | 2 | 1 |

Secretos redactados por tipo: `correo_personal` 16.

## 3. Tipos de evidencia

| Tipo | Documentos | Líneas |
| --- | ---: | ---: |
| `texto` | 71 | 3015 |
| `tabla` | 24 | 336 |
| `codigo` | 31 | 2500 |
| `diagrama` | 13 | 1746 |
| `especificacion` | 3 | 1089 |
| `formula` | 1 | 9 |

## 4. Restricciones de la fase 0

La herramienta devuelve los documentos completos; estas restricciones solo limitan de qué partes se crean ejemplos.

| Concepto | Valor |
| --- | ---: |
| Líneas en secciones `usable` | 3811 |
| Líneas en secciones `parcial` | 4835 |
| Líneas en secciones `no_usable` | 534 |
| Líneas no citables (no_usable + afirmaciones excluidas) | 687 |
| Afirmaciones excluidas (localizadas / total) | 134 / 134 |
| Conflictos (contradicción / inconsistencia) | 27 / 50 |
| Huecos confirmados (con documento y líneas / total) | 60 / 63 |

Las cifras incluyen las copias de versiones idénticas.

## 5. Llamadas posibles y ventana de contexto

Estimación: 3.5 caracteres por token sobre el JSON que devuelve la herramienta. Límite: 32,768 tokens, reservando 2,048 para sistema, pregunta y respuesta. La medición exacta se hace con el tokenizador del modelo al exportar.

| Software | version | Documentos | Tokens estimados | Cabe |
| --- | --- | ---: | ---: | ---: |
| 2p-revenue-optimizer-api | null | 7 | 4,641 | sí |
| 2p-revenue-optimizer-api | 0.2.2 | 3 | 2,199 | sí |
| 2p-revenue-optimizer-api | latest | 4 | 2,462 | sí |
| catalog-portfolio-api | null | 16 | 20,705 | sí |
| catalog-portfolio-api | 0.0.1-test-bench-v2a | 8 | 10,395 | sí |
| catalog-portfolio-api | latest | 8 | 10,331 | sí |
| demand-forecast-docs | null | 4 | 13,994 | sí |
| demand-forecast-docs | latest | 4 | 13,994 | sí |
| order-workflow-api | null | 8 | 5,655 | sí |
| order-workflow-api | 5.6.2-hotfix-1 | 8 | 5,655 | sí |
| payment-promise-gateway | null | 2 | 9,941 | sí |
| payment-promise-gateway | 0.0.10-test-crc-migration | 1 | 4,986 | sí |
| payment-promise-gateway | latest | 1 | 4,976 | sí |
| price-engine-api | null | 5 | 1,794 | sí |
| price-engine-api | latest | 5 | 1,794 | sí |
| traffic-gate-api | null | 7 | 10,801 | sí |
| traffic-gate-api | latest | 7 | 10,801 | sí |
| unified-transaction-configs | null | 2 | 668 | sí |
| unified-transaction-configs | v0.0.2 | 2 | 668 | sí |
| vendor-stockkeeper-api | null | 20 | 21,104 | sí |
| vendor-stockkeeper-api | 0.0.10-stock-consumer | 5 | 5,624 | sí |
| vendor-stockkeeper-api | 0.0.3-paused-seller | 5 | 5,216 | sí |
| vendor-stockkeeper-api | 0.0.6-ep-restock-man | 5 | 5,148 | sí |
| vendor-stockkeeper-api | latest | 5 | 5,179 | sí |
| zenith-keeper | null | 3 | 7,099 | sí |
| zenith-keeper | 1.1.6 | 3 | 7,099 | sí |

## 6. Material para cada situación

| Situación | Material disponible |
| --- | --- |
| version_explicita | 16 versiones |
| sin_version | 10 software |
| en_que_version, comparacion_versiones | 4 software con varias versiones: 2p-revenue-optimizer-api, catalog-portfolio-api, payment-promise-gateway, vendor-stockkeeper-api |
| evidencia_parcial, sin_evidencia | 63 huecos confirmados |
| contradiccion | 77 conflictos localizados |
| falta_software, software_en_historial, sin_documentos | siempre |

## 7. Ejemplos de referencia

10 conversaciones, una por situación, validadas contra el contrato. Usan solo `payment-promise-gateway`, `vendor-stockkeeper-api`, que deben quedar en entrenamiento en la fase 2.

| Caso | Situación | Idioma | Llamada | Documentos | Tipo de evidencia |
| --- | --- | --- | --- | --- | --- |
| `ref_version_explicita` | version_explicita | es | `payment-promise-gateway`, `latest` | 1 | texto, diagrama |
| `ref_sin_version` | sin_version | es | `vendor-stockkeeper-api`, `None` | 20 | texto |
| `ref_en_que_version` | en_que_version | en | `vendor-stockkeeper-api`, `None` | 20 | texto, codigo, diagrama |
| `ref_comparacion_versiones` | comparacion_versiones | es | `vendor-stockkeeper-api`, `None` | 20 | texto |
| `ref_falta_software` | falta_software | es | — | 0 | — |
| `ref_software_en_historial` | software_en_historial | es | `payment-promise-gateway`, `latest` | 1 | texto, codigo, diagrama |
| `ref_evidencia_parcial` | evidencia_parcial | es | `payment-promise-gateway`, `latest` | 1 | texto |
| `ref_sin_evidencia` | sin_evidencia | es | `vendor-stockkeeper-api`, `latest` | 5 | tabla |
| `ref_contradiccion` | contradiccion | es | `vendor-stockkeeper-api`, `0.0.10-stock-consumer` | 5 | tabla, codigo |
| `ref_sin_documentos` | sin_documentos | es | `payment-promise-gateway`, `2.0` | 0 | — |
