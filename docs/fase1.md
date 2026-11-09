# Fase 1 — Catálogo, herramienta y contrato de los ejemplos

Este documento explica en detalle qué hace la fase 1, por qué y cómo comprobarlo. Para ejecutarla basta con `python -m src.fase1.run` (ver el [README](../README.md#fase-1--catálogo-herramienta-y-criterios-de-los-ejemplos)).

## 1. Objetivo

El asistente que se va a entrenar responde preguntas técnicas usando la documentación como evidencia. Antes de responder, **llama a una herramienta que filtra por software y versión y devuelve documentos completos**. Después lee esos documentos, responde y cita los pasajes que respaldan cada afirmación.

La fase 1 prepara todo lo que necesita la generación de conversaciones, **sin generar todavía ninguna**:

1. un **catálogo congelado** de documentos;
2. las **restricciones** que dejó la auditoría de la fase 0, en líneas de cada documento;
3. la **herramienta** `obtener_documentacion`;
4. el **contrato de los ejemplos**: prompt de sistema, reglas, formatos y conversaciones de referencia.

**Es determinista y no usa LLM.** Dos ejecuciones producen archivos idénticos byte a byte.

## 2. Diseño general

| Paso | Módulo | Salida |
|---|---|---|
| 1. Catálogo | `src/fase1/catalog.py` | `data/fase1/catalogo.jsonl` |
| 2. Restricciones | `src/fase1/restrictions.py` | `data/fase1/restricciones.jsonl`, `data/fase1/huecos.jsonl` |
| 3. Herramienta | `src/fase1/tool.py` | `data/fase1/llamadas.jsonl` |
| 4. Ejemplos de referencia | `src/fase1/reference_examples.py`, validados con `src/fase1/validate.py` | `data/fase1/ejemplos_referencia.jsonl` |
| 5. Reporte | `src/fase1/report.py` | `reports/fase1/estadisticas.md` |

`src/fase1/run.py` ejecuta los cinco pasos en orden. Si falta la salida de la fase 0, termina con un error.

Lugar de esta fase en el flujo completo:

| Fase | Contenido |
|---|---|
| 0 | Auditoría: qué secciones son fiables, qué afirmaciones se excluyen y qué falta |
| **1** | **Catálogo, herramienta y contrato** |
| 2 | Separación en conjuntos por software (`splits.json`) |
| 3 | Generación de conversaciones con un LLM, siguiendo el contrato |
| 4 | Validación y exportación de `train.jsonl` y de los casos de validación y prueba |
| 5 | Entrenamiento y evaluación |

## 3. Paso 1 — Catálogo

### 3.1 Qué es un documento

- **Un documento es un archivo de `docs_raw`.** Su `id` es la ruta relativa, por ejemplo `payment-promise-gateway/latest/guide/README.md`. Es único, estable y apunta directamente al original.
- **`software` y `version` salen de las carpetas, literalmente.** `latest` es una etiqueta de versión como cualquier otra. No significa «la más reciente» salvo que la documentación lo diga.
- **`titulo`** es el primer título Markdown del archivo. En los `swagger.yaml` es el `info.title`, y si no hay ninguno, el nombre del archivo.
- **Quedan fuera del catálogo los archivos de navegación y metadatos de docsify:** `_sidebar.md`, `_coverpage.md` y `documentationTypes.json`. Son 33 de los 107 archivos, y la fase 0 los clasificó como `navegacion_metadatos`: índice, portada y URLs de publicación. No contienen evidencia técnica y ocuparían contexto en cada llamada. El catálogo tiene **74 documentos**.
- **Las versiones idénticas se conservan como documentos distintos.** El contrato exige una versión explícita en cada documento: quien pregunta por `latest` debe recibir los documentos de `latest`.

### 3.2 Contenido canónico

El contenido canónico es lo que devuelve la herramienta, y sobre él se cuentan las líneas de las citas. Se obtiene normalizando el original **sin añadir ni quitar líneas**: la línea N del canónico es la línea N del archivo de `docs_raw`. Así, las líneas que registró la fase 0 y las citas siguen apuntando al original.

| Transformación | Ejemplo | Dónde aparece |
|---|---|---|
| `entidad_html` | `C-&gt;&gt;W` → `C->>W`; `&#34;id&#34;` → `"id"` | Mermaid, PlantUML y JSON de order-workflow y vendor-stockkeeper 0.0.10 |
| `pestana_docsify` | `<!-- tab:Operation -->` → `Operation:` | `api.md` de vendor-stockkeeper |
| `marca_docsify` | `### Título <!-- {docsify-ignore} -->` → `### Título` | price-engine |
| `insignia` | `![technology Go](https://img.shields.io/...)` → línea vacía | price-engine, catalog-portfolio |
| `secreto` | `marco.valencia@empresa.com` → `<REDACTADO>` | Correos personales de `contacto.md` (price-engine) |

**Secretos.** Se buscan tokens `Bearer`, JWT, credenciales con valor (`password`, `secret`, `api_key` o `token` seguidos de `:` o `=`), credenciales en URLs y correos personales (`nombre.apellido@`). Los valores de relleno, como `your_password`, `${AUTH_TOKEN}` o `<token>`, no se tocan, y tampoco los buzones de equipo. En el corpus solo hay correos personales: 16, en 8 líneas.

**Ninguna transformación es silenciosa.** Cada documento lista en `transformaciones` las líneas cambiadas y el tipo de cambio. Salvo en los secretos, guarda también la línea original, de modo que deshacer los cambios devuelve el archivo exacto. Un test lo comprueba.

**No se corrigen errores ni contradicciones del contenido.** Para eso están las restricciones (paso 2).

**Hashes.** Cada documento guarda dos:

| Hash | Sobre qué | Para qué |
|---|---|---|
| `sha256_original` | Los bytes del archivo de `docs_raw` | Probar la procedencia y detectar cambios en `docs_raw`. Permite encontrar las copias idénticas entre versiones, que la fase 2 debe mantener en el mismo conjunto |
| `sha256_canonico` | El contenido que devuelve la herramienta | Comprobar la integridad en la evaluación: un documento con el ID correcto pero el contenido recortado o alterado falla |

`corpus_version` es un hash corto del catálogo completo (`docs_` seguido de 12 caracteres hexadecimales). Cambia si cambia cualquier documento.

### 3.3 Tipos de evidencia

Cada documento registra en `tipos_evidencia` los rangos de líneas de cada formato:

| Tipo | Cómo se detecta |
|---|---|
| `texto` | Líneas de prosa o listas fuera de bloques de código |
| `tabla` | Tabla Markdown: una fila que empieza por `|` seguida de un separador `|---|` |
| `codigo` | Bloque de código que no es diagrama: bash, json, python, sql, yml o sin lenguaje |
| `diagrama` | Bloque `mermaid` o `plantuml` |
| `especificacion` | Archivo OpenAPI completo (`swagger.yaml`) |
| `formula` | Líneas con LaTeX (`$$`, `\sum`, `\frac`…) |

Cada ejemplo hereda el tipo de las líneas que cita (`tipo_evidencia` del caso), lo que permitirá medir el acierto por tipo.

## 4. Paso 2 — Restricciones de la fase 0

### 4.1 Qué decide la fase 0

**La fase 0 decide de qué partes de la documentación se pueden crear ejemplos, no qué ve el modelo.** La herramienta siempre devuelve los documentos enteros, igual que en el uso real, incluidas las partes que la fase 0 marcó como no fiables. Las preguntas y las respuestas objetivo, en cambio, solo pueden apoyarse en secciones `usable` o `parcial`, y nunca en sus afirmaciones excluidas.

Las restricciones nunca entran en la conversación: las usan el generador (fase 3), el verificador y la validación por código (fase 4).

### 4.2 `restricciones.jsonl`

Una fila por documento del catálogo:

| Campo | Contenido |
|---|---|
| `secciones` | Cada sección de la fase 0, con sus líneas, su estado final y su categoría |
| `no_citables` | Rangos que no pueden respaldar una respuesta: secciones `no_usable` y líneas de las afirmaciones excluidas |
| `no_citables_propias` | Lo mismo, pero solo con lo que la fase 0 marcó en este documento (ver 4.3) |
| `afirmaciones_excluidas` | Cada afirmación excluida de una sección `parcial`, con sus líneas |
| `conflictos` | Contradicciones e inconsistencias que señaló A, con sus líneas, su explicación y las otras secciones implicadas |
| `copias_identicas` | Otros documentos con el mismo `sha256_original` |

Las citas de la fase 0 se hicieron sobre el texto original, que tenía las entidades HTML sin decodificar. Por eso se localizan primero en el original y, si no aparecen, en el canónico. Los espacios se comparan normalizados, como en la fase 0. **Se localizan las 134 afirmaciones excluidas**, que son 118 sin contar las copias de versiones idénticas, y todos los conflictos.

**Excepción: la situación `contradiccion`.** Es la única que puede citar líneas no citables, y solo las que figuran en `conflictos`, para señalar el conflicto y nunca como un hecho.

### 4.3 Documentos idénticos con restricciones distintas

La fase 0 audita cada versión por separado. En 4 grupos de documentos idénticos byte a byte marcó líneas no citables distintas en el mismo texto. Por ejemplo, las líneas 351 y 352 del README de payment-promise-gateway son no citables en `latest` y citables en `0.0.10-test-crc-migration`.

El mismo texto no puede ser fiable en una versión y no en otra. Por eso se aplica una **regla conservadora: en documentos idénticos, una línea es no citable si lo es en cualquiera de las copias, y los conflictos de una copia valen para todas**. Lo que marcó cada copia por sí sola se conserva en `no_citables_propias`. El reporte lista los grupos afectados.

**Por qué el mismo LLM da criterios distintos sobre el mismo texto.** En el ejemplo de payment-promise-gateway, en `latest` A marcó la sección como `parcial` y B como `usable`, y la regla por defecto eligió `parcial`. En `0.0.10` los dos dijeron `usable`. Hay cuatro causas:

1. **Un LLM no es determinista.** Las CLI no permiten fijar la temperatura ni la semilla. Por eso la fase 0 se reproduce desde la caché de respuestas.
2. **La entrada no es la misma.** Cada llamada audita la versión completa, y en cada versión el documento va acompañado de otros archivos.
3. **Detectar el problema exige relacionar líneas lejanas.** El `CREDIT_CARD` de la línea 351 solo es incoherente frente a un ejemplo de respuesta que está unas 60 líneas más abajo. Además, son casos límite, valores dentro de un ejemplo, y ahí el criterio varía más.
4. **B revisa lo que dice A, no busca por su cuenta.** Corrige bien los problemas que A señala sin motivo, pero rara vez recupera los que A no ve.

**Medida de consistencia.** Las copias idénticas que se auditaron por separado son el mismo texto evaluado en llamadas independientes, así que permiten medir este efecto sin coste:

- hay 64 pares de secciones idénticas, y en 55 (86%) el estado final coincide;
- de los 9 pares en que no coincide, 8 son casos límite entre `usable` y `parcial`;
- el noveno es la sección 2 de `important.md` de vendor-stockkeeper: `no_usable` en `0.0.3` y `usable` en las demás copias.

La cifra es parecida al 89,5% de acuerdo entre A y B que se midió en la fase 0. **Las etiquetas de la fase 0 tienen ruido en los casos límite.**
- **En los documentos idénticos,** la regla de unión lo corrige.
- **En los documentos sin copia,** no se puede detectar. La segunda barrera es la verificación de la fase 4, que comprueba que cada respuesta generada está respaldada por los documentos.
- **Para reducirlo en origen,** habría que auditar cada versión varias veces y votar. Se descartó porque multiplica el coste y obliga a repetir la revisión humana.

La tabla de los 9 casos está en el reporte.

### 4.4 `huecos.jsonl`

Un hueco confirmado por fila (63), con su software, su versión, la descripción y la evidencia. Si la evidencia está en un documento del catálogo, se indican el documento y las líneas (60 de 63). Los otros 3 tienen su evidencia en un `_sidebar.md`, por ejemplo una página de autenticación que el índice anuncia y que no existe. Se conservan por software y versión.

Los huecos son la fuente de las situaciones `evidencia_parcial` y `sin_evidencia`. El generador debe comprobar que la información falta en **todos** los documentos devueltos, no solo en el pasaje del hueco.

## 5. Paso 3 — Herramienta

`src/fase1/tool.py`:

- **`TOOL_SCHEMA` / `TOOLS`:** la definición que reciben el modelo y el entrenador. Tiene dos parámetros obligatorios, `software` (cadena) y `version` (cadena o `null`), y ninguno más. No hay un argumento de consulta semántica.
- **`seleccionar_documentos(catalogo, software, version)`:** el filtro exacto, ordenado por `id`. No depende del tema de la pregunta: dos preguntas sobre el mismo software y versión reciben los mismos documentos.
- **`obtener_documentacion(software, version)`:** devuelve `{status, corpus_version, documentos}`. Cada documento lleva `id`, `software`, `version`, `titulo` y `contenido` completo.
  - `status` es `ok` si hay documentos, `not_found` si el filtro no coincide con nada y `error` si no se pudo leer el catálogo.
  - Un `error` no se confunde con un `not_found`.

**`llamadas.jsonl`** contiene las 26 llamadas posibles: cada software con `version=null` y con cada una de sus versiones. Para cada una indica los IDs devueltos, el tamaño y si cabe en el contexto:

- **Estimación del tamaño.** Se calcula sobre el JSON que vería el modelo, a 3,5 caracteres por token.
- **Límite de contexto.** Es de 32.768 tokens, reservando 2.048 para el sistema, la pregunta y la respuesta. Ambos valores son constantes de `tool.py` y se ajustan al elegir el modelo.
- **Medición exacta.** Se hace en la fase 4, con el tokenizador real.

La llamada más grande es `vendor-stockkeeper-api` con `version=null`: 20 documentos y unos 21.000 tokens. Todas caben. Una llamada que no cupiera se marcaría como no soportada y nunca se recortaría.

## 6. Paso 4 — Contrato de los ejemplos

### 6.1 Archivos del contrato

| Archivo | Contenido |
|---|---|
| `src/fase1/contract/system_prompt.md` | El prompt de sistema, fijo para el entrenamiento y la evaluación |
| `src/fase1/contract/reglas.md` | Qué partes se pueden usar, las 10 situaciones, las 16 reglas y qué preguntar según el tipo de evidencia. Se incluye en el prompt del generador y del verificador |
| `src/fase1/contract/conversation_schema.json` | Formato de la conversación de entrenamiento |
| `src/fase1/contract/eval_case_schema.json` | Formato del caso de evaluación |

### 6.2 Conversación de entrenamiento

Es el formato `messages` + `tools` que consume el entrenador:

```text
system     prompt de sistema (system_prompt.md)
user       pregunta
assistant  llamada: obtener_documentacion(software, version), sin texto
tool       salida REAL de la herramienta: documentos completos
assistant  respuesta con citas [documento:Linicio-Lfin]
```

- **Falta el software:** la conversación termina con una aclaración del asistente, sin llamada.
- **Hay turnos previos:** van entre el prompt de sistema y la pregunta.
- **Qué aprende el modelo:** los mensajes del asistente, es decir, la llamada y la respuesta. Los mensajes `tool` son contexto y no se aprenden.

### 6.3 Caso de evaluación

Sigue el formato de la guía del dataset:

- `case_id`, `corpus_version`, `historial` y `pregunta`;
- `expected_action`: `tool_call` o `clarification`;
- `expected_tool` y `expected_document_ids`;
- `reference_answer` y `answer_checks`.

Añade cinco campos propios:

| Campo | Contenido |
|---|---|
| `situacion` | Una de las 10 situaciones |
| `idioma` | `es` o `en` |
| `tipo_evidencia` | Tipos de las líneas citadas por la respuesta de referencia |
| `restricciones` | Hueco, conflicto o líneas no citables que intervienen en el caso |
| `procedencia` | Documento, líneas y `sha256_canonico` de cada cita de la referencia |

Solo `historial` y `pregunta` llegan al modelo evaluado, junto con el sistema y las herramientas. `expected_document_ids` se calcula desde el catálogo congelado, nunca desde la salida que se evalúa.

### 6.4 Situaciones

| `situacion` | Acción correcta | Fuente en nuestros datos |
|---|---|---|
| `version_explicita` | Llamar con software y versión | Cualquier sección `usable` o `parcial` (16 versiones) |
| `sin_version` | Llamar con `version=null` | Igual (10 software) |
| `en_que_version` | Llamar con `version=null` | Capacidades presentes en unas versiones y no en otras |
| `comparacion_versiones` | Llamar con `version=null` | Diferencias entre versiones. Hay 4 software con varias versiones: vendor-stockkeeper, catalog-portfolio, payment-promise y 2p-revenue |
| `falta_software` | Preguntar, sin llamar | Cualquier pregunta sin software |
| `software_en_historial` | Llamar con el software del historial | Conversación de dos turnos |
| `evidencia_parcial` | Llamar; responder lo respaldado y señalar lo que falta | Pasaje respaldado + hueco del mismo software/versión |
| `sin_evidencia` | Llamar; decir que la documentación no permite responder | Huecos confirmados |
| `contradiccion` | Llamar; citar ambas fuentes sin elegir | Conflictos de la fase 0 |
| `sin_documentos` | Llamar, recibir `not_found` y explicarlo | Software o versión que no está en el catálogo |

La matriz sirve para comprobar la cobertura, no impone una distribución uniforme. La distribución se fija en la fase 3.

### 6.5 Validación por código

`src/fase1/validate.py` comprueba dos cosas. Lo mismo se usará en la fase 4 con las conversaciones generadas.

1. **El esquema.** Implementa el subconjunto de JSON Schema que usan los archivos del contrato, para no añadir otra dependencia.
2. **El contrato:**
   - el prompt de sistema y las herramientas son los del contrato;
   - la acción corresponde a la situación;
   - la llamada es la esperada;
   - la salida `tool` es exactamente la que produce la herramienta real;
   - los documentos devueltos son los esperados;
   - `not_found` aparece solo en la situación `sin_documentos`;
   - cada cita apunta a un documento entregado, con un rango válido y sin líneas no citables (salvo los conflictos, en `contradiccion`);
   - el hash de la procedencia coincide.

**No comprueba que una cita respalde la afirmación.** Esa es la evaluación semántica de la fase 4.

### 6.6 Conversaciones de referencia

Hay 10, una por situación, escritas a mano sobre el corpus real. Las preguntas, las llamadas y las respuestas son manuales. La salida de la herramienta, en cambio, se obtiene ejecutándola. La procedencia, los documentos esperados y el tipo de evidencia se calculan a partir de las citas.

| Caso | Pregunta (resumen) | Qué enseña |
|---|---|---|
| `ref_version_explicita` | Orden de llamadas de `GET /payment_promise/form` en payment-promise-gateway latest | Leer un diagrama mermaid y citarlo |
| `ref_sin_version` | ¿Qué hace vendor-stockkeeper-api? | `version=null`; decir que las 4 versiones coinciden |
| `ref_en_que_version` | En inglés: in which version is Operation Validation Consumer documented? | Identificar la versión sin afirmar que no exista en las demás |
| `ref_comparacion_versiones` | Alerta Validation stock: 0.0.6-ep-restock-man frente a latest | `version=null` aunque se nombren dos versiones; no mezclarlas |
| `ref_falta_software` | ¿Cómo pauso una publicación…? | Preguntar por el software, sin llamar |
| `ref_software_en_historial` | «¿Y cómo consulto la promesa activa?», tras el primer caso | Reutilizar el software del historial |
| `ref_evidencia_parcial` | Métricas (documentadas) y formato de error (no documentado) | Responder una parte y declarar lo que falta |
| `ref_sin_evidencia` | Campos que devuelve Get Detail Doma | Decir que no está documentado, sin inventar campos |
| `ref_contradiccion` | Método HTTP de Operation Validation Consumer en 0.0.10-stock-consumer | La tabla dice GET y el ejemplo envía un cuerpo: citar ambos sin elegir |
| `ref_sin_documentos` | Reintentos en payment-promise-gateway 2.0 | Explicar el `not_found` |

Tienen dos usos: ejemplos dentro del prompt del generador (fase 3) y fixtures de la validación (fase 4).

**Solo usan `vendor-stockkeeper-api` y `payment-promise-gateway`.** Esos dos software deben quedar en entrenamiento en la fase 2, para que los ejemplos de referencia no contaminen la evaluación. Se eligieron porque tienen varias versiones, que hacen falta para las situaciones `en_que_version` y `comparacion_versiones`.

## 7. Resultado sobre el corpus entregado

Las cifras completas están en [reports/fase1/estadisticas.md](../reports/fase1/estadisticas.md):

- **Catálogo:**
  - 74 documentos, 9.180 líneas y ~310.000 caracteres;
  - 15 grupos de documentos idénticos entre versiones, y en 4 de ellos se aplicó la regla de 4.3.
- **Normalización:**
  - 402 líneas con entidades HTML decodificadas;
  - 7 insignias eliminadas;
  - 3 pestañas y 2 marcas de docsify convertidas;
  - 16 correos personales redactados.
- **Restricciones:**
  - 662 líneas no citables;
  - 134 afirmaciones excluidas localizadas;
  - 77 conflictos;
  - 63 huecos, 60 de ellos con documento y líneas.
- **Contexto:** las 26 llamadas posibles caben. La mayor tiene unos 21.000 tokens.

## 8. Tests

`src/tests/test_fase1.py`:

- **Normalización:** cada transformación sobre un caso pequeño. Normalizar no cambia el número de líneas, y al deshacerlo se recupera el original.
- **Secretos:** se redactan un token, una contraseña y un correo personal. No se tocan `your_password`, `${AUTH_TOKEN}`, el valor de ejemplo `900000734` ni un buzón de equipo.
- **Restricciones:**
  - se localiza una cita que cruza líneas;
  - todas las afirmaciones excluidas reales se localizan;
  - las copias idénticas comparten la unión de sus líneas no citables.
- **Catálogo:**
  - IDs únicos;
  - el mismo número de líneas que el original;
  - las líneas no transformadas son idénticas al original;
  - los archivos de navegación quedan fuera.
- **Herramienta:**
  - los filtros de la guía (sin versión, con versión, otro software);
  - `not_found`;
  - un error de lectura devuelve `error` y no `not_found`;
  - solo se devuelven los campos públicos;
  - con `version=null` se incluyen las copias idénticas.
- **Contrato:**
  - los esquemas rechazan argumentos extra y casos incompletos;
  - los 10 ejemplos de referencia cumplen el contrato y cubren las 10 situaciones;
  - el validador detecta una cita a un documento no entregado, un rango fuera del documento, una línea no citable (permitida solo en `contradiccion`), una salida de la herramienta recortada, una versión equivocada en la llamada y una respuesta sin citas.
- **Determinismo:** dos construcciones dan exactamente el mismo resultado.

## 9. Reproducibilidad

La fase 1 solo lee `docs_raw/` y las salidas de la fase 0. No usa LLM ni depende de fechas, de la máquina ni del orden del sistema de archivos: todo se ordena explícitamente. Para comprobar que se obtiene lo entregado:

```bash
python -m src.fase1.run
git status --short data/ reports/
```

Si `git status` no muestra nada, los archivos son idénticos byte a byte a los entregados.

## 10. Lo que no hace la fase 1

- **No separa los conjuntos.** Eso lo hace la fase 2, que reservará software completos para validación y prueba. Con 10 software, una propuesta es 6 / 2 / 2. Las copias idénticas van siempre en el mismo conjunto, y vendor-stockkeeper y payment-promise-gateway, en entrenamiento.
- **No genera conversaciones** (fase 3) **ni las valida semánticamente** (fase 4).
- **No mide tokens con el tokenizador real** (fase 4).
