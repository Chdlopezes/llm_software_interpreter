# Fase 0 — Estadísticas

Generado por `python -m src.fase0.finalize`. Las cifras salen de `data/fase0/`.

## 1. Corpus auditado

| Concepto | Valor |
| --- | ---: |
| Software distintos | 10 |
| Versiones (software/versión) | 16 |
| Versiones idénticas a otra (heredan etiquetas) | 1 |
| Archivos | 107 |
| Tamaño total | 322,273 bytes |
| Secciones | 360 |
| Secciones con etiqueta final (cobertura verificada) | 360 (100.0%) |

- `catalog-portfolio-api/latest` es idéntica a `catalog-portfolio-api/0.0.1-test-bench-v2a`.

## 2. Chequeos automáticos (paso 1)

| Tipo | Casos | Archivos afectados |
| --- | ---: | ---: |
| `recurso_ausente` | 29 | 20 |
| `ancla_rota` | 20 | 4 |
| `enlace_roto` | 14 | 6 |
| `metadatos_latest_resuelve_a` | 9 | 7 |
| `seccion_vacia` | 7 | 7 |
| `entidad_html_en_codigo` | 5 | 5 |
| `marcador_pendiente` | 3 | 1 |
| `enlace_correo_sin_mailto` | 2 | 1 |
| `enlace_mal_formado` | 1 | 1 |

## 3. Clasificación con LLM (pasos 2 a 4)

| Concepto | LLM A (clasifica) | LLM B (valida) |
| --- | ---: | ---: |
| Modelo | claude-opus-5-5 | gpt-6.1-sol |
| Versiones procesadas | 15 | 15 |
| Llamadas (incluidos reintentos) | 16 | 15 |
| Versiones que necesitaron reintento | 1 | 0 |
| Secciones con respuesta inválida tras el reintento | 0 | 0 |

## 4. Acuerdo entre A y B

Sobre 295 secciones (sin contar las copias heredadas):

| Medida | Secciones | % |
| --- | ---: | ---: |
| Mismo estado | 264 | 89.5% |
| Misma categoría | 282 | 95.6% |

Estado de A (filas) frente a estado de B (columnas):

| A \ B | usable | parcial | no_usable |
| --- | ---: | ---: | ---: |
| usable | 131 | 12 | 2 |
| parcial | 7 | 44 | 0 |
| no_usable | 6 | 4 | 89 |

## 5. Revisión humana (paso 5)

Secciones con estados distintos entre A y B, o con alguna respuesta inválida: **31** filas en `data/fase0/human_review.csv`.

| Decisión | Eligió A | Eligió B | Total |
| --- | ---: | ---: | ---: |
| Humana | 0 | 0 | 0 |
| Por defecto (fila vacía) | 9 | 22 | 31 |

Regla por defecto: gana el modelo que eligió `parcial`; si ninguno, el que eligió `usable`.

## 6. Etiqueta final

| Estado | Secciones | % |
| --- | ---: | ---: |
| `usable` | 167 | 46.4% |
| `parcial` | 83 | 23.1% |
| `no_usable` | 110 | 30.6% |

| Origen de la etiqueta | Secciones |
| --- | ---: |
| A y B de acuerdo | 316 |
| Decisión humana | 0 |
| Decisión por defecto | 44 |

### Por software/versión

| Software/versión | usable | parcial | no_usable | Huecos confirmados |
| --- | ---: | ---: | ---: | ---: |
| 2p-revenue-optimizer-api/0.2.2 | 4 | 2 | 2 | 3 |
| 2p-revenue-optimizer-api/latest | 4 | 3 | 2 | 2 |
| catalog-portfolio-api/0.0.1-test-bench-v2a | 28 | 16 | 21 | 7 |
| catalog-portfolio-api/latest | 28 | 16 | 21 | 7 |
| demand-forecast-docs/latest | 8 | 6 | 3 | 2 |
| order-workflow-api/5.6.2-hotfix-1 | 8 | 4 | 5 | 8 |
| payment-promise-gateway/0.0.10-test-crc-migration | 15 | 0 | 3 | 1 |
| payment-promise-gateway/latest | 14 | 1 | 3 | 2 |
| price-engine-api/latest | 4 | 2 | 11 | 5 |
| traffic-gate-api/latest | 11 | 11 | 5 | 1 |
| unified-transaction-configs/v0.0.2 | 4 | 1 | 2 | 1 |
| vendor-stockkeeper-api/0.0.10-stock-consumer | 7 | 4 | 7 | 6 |
| vendor-stockkeeper-api/0.0.3-paused-seller | 6 | 4 | 8 | 5 |
| vendor-stockkeeper-api/0.0.6-ep-restock-man | 8 | 3 | 7 | 6 |
| vendor-stockkeeper-api/latest | 9 | 2 | 7 | 5 |
| zenith-keeper/1.1.6 | 9 | 8 | 3 | 2 |

### Por categoría

| Categoría | usable | parcial | no_usable |
| --- | ---: | ---: | ---: |
| endpoint_api | 24 | 31 | 6 |
| modelo_datos | 7 | 10 | 0 |
| configuracion | 32 | 5 | 0 |
| procedimiento | 28 | 13 | 2 |
| arquitectura | 19 | 9 | 3 |
| troubleshooting | 21 | 10 | 3 |
| descripcion_general | 35 | 5 | 4 |
| navegacion_metadatos | 0 | 0 | 81 |
| otro | 1 | 0 | 11 |

### Motivos de `parcial` y `no_usable`

Según A, en las secciones cuya etiqueta final es la de A. Una sección puede tener varios motivos.

| Motivo | Secciones |
| --- | ---: |
| `contradiccion` | 23 |
| `inconsistencia` | 27 |
| `incompleto` | 28 |
| `roto` | 11 |
| `vacio` | 8 |
| `sin_contenido_tecnico` | 90 |

## 7. Material disponible para generar datos

Secciones `usable` y `parcial` (de las parciales se excluyen las afirmaciones citadas).

| Concepto | Secciones | Caracteres |
| --- | ---: | ---: |
| Todas las versiones | 250 | 296,830 |
| Sin contar copias de versiones idénticas | 206 | 269,545 |

Por software (sin copias):

| Software | Versiones | Secciones | Caracteres |
| --- | ---: | ---: | ---: |
| 2p-revenue-optimizer-api | 2 | 13 | 14,513 |
| catalog-portfolio-api | 1 | 44 | 27,285 |
| demand-forecast-docs | 1 | 14 | 46,446 |
| order-workflow-api | 1 | 12 | 17,254 |
| payment-promise-gateway | 2 | 30 | 32,116 |
| price-engine-api | 1 | 6 | 4,272 |
| traffic-gate-api | 1 | 22 | 35,400 |
| unified-transaction-configs | 1 | 5 | 1,849 |
| vendor-stockkeeper-api | 4 | 43 | 67,021 |
| zenith-keeper | 1 | 17 | 23,389 |

## 8. Huecos de documentación

A listó 70 huecos; B confirmó 63 (90.0%).

- **2p-revenue-optimizer-api/0.2.2**: No se explica qué datos guarda la tabla rule_header; la descripción está cortada.
- **2p-revenue-optimizer-api/0.2.2**: La columna type de rule_header no tiene descripción de su significado ni de sus valores posibles.
- **2p-revenue-optimizer-api/0.2.2**: No se explica qué datos guarda la tabla rule_row; la descripción está cortada.
- **2p-revenue-optimizer-api/latest**: Falta qué almacenan las tablas rule_header, rule_row y rule_custom_field; la frase que debería explicarlo está vacía.
- **2p-revenue-optimizer-api/latest**: La columna type de rule_header aparece en la tabla pero sin descripción.
- **catalog-portfolio-api/0.0.1-test-bench-v2a**: No existe la página de autenticación, aunque se dice que todos los endpoints la requieren.
- **catalog-portfolio-api/0.0.1-test-bench-v2a**: Faltan las páginas de ciclo de vida, creación, actualización, activación y validación de marcas.
- **catalog-portfolio-api/0.0.1-test-bench-v2a**: Los endpoints de logos aparecen en la tabla pero no tienen detalle de parámetros ni respuestas.
- **catalog-portfolio-api/0.0.1-test-bench-v2a**: Los endpoints de collectors aparecen en la tabla pero no tienen detalle.
- **catalog-portfolio-api/0.0.1-test-bench-v2a**: El endpoint de recursos aparece en la tabla pero no tiene detalle.
- **catalog-portfolio-api/0.0.1-test-bench-v2a**: Los endpoints allstatus, ping y borrado de tags están listados pero brands.md no los detalla.
- **catalog-portfolio-api/0.0.1-test-bench-v2a**: Se referencia una sección de configuración de la base de datos que no existe.
- **catalog-portfolio-api/latest**: No existe la página de autenticación, aunque se dice que todos los endpoints la requieren.
- **catalog-portfolio-api/latest**: Faltan las páginas de ciclo de vida, creación, actualización, activación y validación de marcas.
- **catalog-portfolio-api/latest**: Los endpoints de logos aparecen en la tabla pero no tienen detalle de parámetros ni respuestas.
- **catalog-portfolio-api/latest**: Los endpoints de collectors aparecen en la tabla pero no tienen detalle.
- **catalog-portfolio-api/latest**: El endpoint de recursos aparece en la tabla pero no tiene detalle.
- **catalog-portfolio-api/latest**: Los endpoints allstatus, ping y borrado de tags están listados pero brands.md no los detalla.
- **catalog-portfolio-api/latest**: Se referencia una sección de configuración de la base de datos que no existe.
- **demand-forecast-docs/latest**: No se dice cuál es el archivo yml donde se definen los datasets del catálogo ni cómo está estructurado.
- **demand-forecast-docs/latest**: Se anuncia el paso de ejecutar un plan con rda workflow run, pero no se explica ni se da un ejemplo.
- **order-workflow-api/5.6.2-hotfix-1**: La página de soporte enlazada no existe.
- **order-workflow-api/5.6.2-hotfix-1**: Faltan los diagramas de arquitectura de producción y de test.
- **order-workflow-api/5.6.2-hotfix-1**: El mensaje Protect branch se anuncia pero no se documenta.
- **order-workflow-api/5.6.2-hotfix-1**: El objeto Cron History está pendiente de documentar.
- **order-workflow-api/5.6.2-hotfix-1**: El caso de uso de búsqueda de pipeline se lista sin detalle.
- **order-workflow-api/5.6.2-hotfix-1**: El caso de uso de abortar un pipeline se lista sin detalle.
- **order-workflow-api/5.6.2-hotfix-1**: Los casos de uso de protección de ramas y de creación de backports se listan sin detalle.
- **order-workflow-api/5.6.2-hotfix-1**: La API REST no se documenta en la guía; solo se remite a una especificación externa.
- **payment-promise-gateway/0.0.10-test-crc-migration**: La documentación detallada de la API (OpenAPI/Swagger) se remite a specs-hub y no está incluida en esta documentación.
- **payment-promise-gateway/latest**: La documentación detallada de la API (OpenAPI/Swagger) se remite a specs-hub, que no está incluida en esta documentación.
- **payment-promise-gateway/latest**: Se anuncia un formato de error común y excepciones propias, pero no se documentan ni el formato, ni los códigos HTTP, ni las excepciones.
- **price-engine-api/latest**: La portada enlaza a README.md, que no existe.
- **price-engine-api/latest**: El diagrama de arquitectura referenciado no está disponible.
- **price-engine-api/latest**: La introducción del servicio está pendiente.
- **price-engine-api/latest**: Las responsabilidades y exclusiones del servicio están pendientes.
- **price-engine-api/latest**: La sección de flujos anuncia un flujo de endpoint pero solo tiene texto de plantilla; el endpoint de cobertura del swagger no se explica en la guía.
- **traffic-gate-api/latest**: Se anuncia un diagrama de arquitectura cuya imagen no existe.
- **unified-transaction-configs/v0.0.2**: Se pide hacer un PUT para que la actualización tenga efecto, pero no se documenta qué endpoint es, ni sus parámetros ni el cuerpo; se remite a documentación externa.
- **vendor-stockkeeper-api/0.0.10-stock-consumer**: El endpoint Get Detail aparece en la tabla de servicios pero no tiene detalle, y su ancla está rota.
- **vendor-stockkeeper-api/0.0.10-stock-consumer**: El endpoint Internal Item Detail aparece en la tabla pero no tiene documentación.
- **vendor-stockkeeper-api/0.0.10-stock-consumer**: El endpoint Get Detail Doma aparece en la tabla pero no tiene documentación.
- **vendor-stockkeeper-api/0.0.10-stock-consumer**: Los enlaces de Feed Consumer y Restock Consumer apuntan a anclas que no existen.
- **vendor-stockkeeper-api/0.0.10-stock-consumer**: Se hace referencia a una imagen de la base de datos que no existe.
- **vendor-stockkeeper-api/0.0.10-stock-consumer**: Faltan las imágenes de apoyo de los flujos Restock y Feed.
- **vendor-stockkeeper-api/0.0.3-paused-seller**: El endpoint Get Detail aparece en la tabla, pero no tiene detalle: ni parámetros, ni respuesta, ni ejemplo.
- **vendor-stockkeeper-api/0.0.3-paused-seller**: El endpoint Internal Item Detail aparece en la tabla, pero no tiene detalle.
- **vendor-stockkeeper-api/0.0.3-paused-seller**: El endpoint Get Detail Doma aparece en la tabla, pero no tiene detalle.
- **vendor-stockkeeper-api/0.0.3-paused-seller**: Se referencia una imagen de la base de datos que no existe.
- **vendor-stockkeeper-api/0.0.3-paused-seller**: Faltan las imágenes que ilustran los tags de ítem de prueba y la tabla 1p_3pl_product_stock_mov.
- **vendor-stockkeeper-api/0.0.6-ep-restock-man**: El endpoint Get Detail aparece en la tabla pero no tiene detalle documentado.
- **vendor-stockkeeper-api/0.0.6-ep-restock-man**: El endpoint Internal Item Detail aparece en la tabla pero no tiene detalle documentado.
- **vendor-stockkeeper-api/0.0.6-ep-restock-man**: El endpoint Get Detail Doma aparece en la tabla pero no tiene detalle documentado.
- **vendor-stockkeeper-api/0.0.6-ep-restock-man**: Falta la imagen de la tabla 1p_3pl_product_stock_mov de la base de datos de 1p-3pl-integrator.
- **vendor-stockkeeper-api/0.0.6-ep-restock-man**: Falta la imagen ilustrativa de las etiquetas de ítem de prueba.
- **vendor-stockkeeper-api/0.0.6-ep-restock-man**: Falta la imagen referenciada en la sección de base de datos.
- **vendor-stockkeeper-api/latest**: El endpoint GET Get Detail está en la tabla pero no tiene detalle.
- **vendor-stockkeeper-api/latest**: El endpoint GET Internal Item Detail está en la tabla pero no tiene detalle.
- **vendor-stockkeeper-api/latest**: El endpoint GET Get Detail Doma está en la tabla pero no tiene detalle.
- **vendor-stockkeeper-api/latest**: Faltan las imágenes de las etiquetas de ítems de prueba y de la tabla 1p_3pl_product_stock_mov.
- **vendor-stockkeeper-api/latest**: Falta la imagen referenciada en la sección de base de datos.
- **zenith-keeper/1.1.6**: La página Getting started, enlazada en el sidebar, solo tiene el título.
- **zenith-keeper/1.1.6**: La guía documenta GET /fresh-products/list{productId} sin sort, pero ese endpoint no aparece en el swagger.
