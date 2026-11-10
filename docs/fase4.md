# Fase 4 — Validación y exportación de los datasets

Este documento explica cómo se validan los candidatos de la fase 3 y cómo se exportan los datasets finales. Para ejecutar la fase basta con `python -m src.fase4.run` (ver el [README](../README.md#fase-4--validación-y-exportación)).

## 1. Objetivo

La fase 4 decide qué candidatos de la fase 3 se aceptan y los exporta, listos para entrenar y evaluar. Aquí se mide **la calidad del dataset**, no la de un modelo: todavía no se ha entrenado ninguno.

Es **determinista y no usa LLM**. La revisión semántica de cada respuesta ya la hizo el verificador en la fase 3 (sección 4 de [docs/fase3.md](fase3.md)). Esta fase añade los controles que se pueden hacer con código, la eliminación de duplicados, la revisión humana y la exportación.

Cada tarea planificada termina en **un solo estado**: aceptada, en su conjunto, o rechazada, con la etapa y el motivo.

```
412 tareas (fase 3) → 407 candidatos → controles → duplicados → revisión humana → 386 aceptados
                    → 5 omitidas en la fase 3                                   → 26 rechazadas
```

## 2. Modelo a ajustar: Qwen3.5-4B

El modelo que se ajustará es **Qwen3.5-4B** (`Qwen/Qwen3.5-4B`). Es abierto y pequeño (4.000 millones de parámetros), tiene 262.144 tokens de contexto y su plantilla de chat soporta llamadas a herramientas. En esta fase solo se descarga su **tokenizer**, en una revisión fija (`851bf6e8…`), sin los pesos ni PyTorch. Con él se renderiza cada conversación tal como la verá el modelo.

Al renderizar nuestras conversaciones con su plantilla aparecieron dos detalles, que se resuelven **solo al renderizar**. Los datos canónicos no cambian:

| Detalle | Problema | Solución |
|---|---|---|
| `version: null` | La plantilla convierte cada argumento con `\|string`, y `None` se escribiría «None». El parser de llamadas de Qwen (`qwen3_coder`) no lo interpretaría como nulo | Se escribe el texto `null` |
| Modo de razonamiento | Por defecto, Qwen3.5 razona dentro de `<think>…</think>` antes de responder. Nuestras respuestas de referencia no tienen razonamiento | Se renderiza con `enable_thinking=False`. La plantilla pone un bloque `<think>` vacío antes de cada turno del asistente, y el modelo aprende a responder sin razonar |

**Qué se entrena.** Se entrenan los mensajes del asistente que van después de la última pregunta del usuario: la llamada a la herramienta y la respuesta. El sistema, el historial, la pregunta y la salida de la herramienta son contexto y no se supervisan.

Para cada conversación se comprueba que la plantilla sea **estable por prefijo** en esos mensajes: el texto que se supervisa tiene que coincidir con lo que el modelo genera a partir de ese punto. Si no coincidiera, la máscara de pérdida entrenaría algo distinto de lo que el modelo produce.

El turno del asistente dentro del historial (en `software_en_historial`) es la excepción: la plantilla lo escribe sin bloque `<think>`. Por eso no se supervisa. Para el modelo es solo contexto.

**Por qué el 4B.** Es un punto intermedio de la familia: más capaz que el 0.8B y el 2B, y se puede ajustar con LoRA en una sola GPU. Elegir el tamaño definitivo es una decisión del experimento de entrenamiento, y no cambia este dataset:
- Los cuatro modelos pequeños de Qwen3.5 (0.8B, 2B, 4B y 9B) tienen el **mismo tokenizer**.
- Sus plantillas solo difieren en el modo de razonamiento por defecto (desactivado en 0.8B y 2B, activado en 4B y 9B). Como aquí se fija `enable_thinking=False`, las 386 conversaciones se renderizan igual con el 2B que con el 4B. Se comprobó.

## 3. Controles por caso

| Control | Qué comprueba | Cubre |
|---|---|---|
| Estructura | El contrato de la fase 1 (`check_example`): esquemas, formato y rango de las citas, líneas no citables, mensajes y herramientas | T4.1 |
| Referencias | Cada cita de `procedencia` existe en el catálogo con el mismo hash. La salida de la herramienta guardada es idéntica a la que devuelve hoy el catálogo, y `expected_document_ids` coincide con ella | T4.8 |
| Aislamiento | El software del caso y el de **cada documento** que recibe pertenecen al conjunto del caso | T4.6 |
| Tokens | La conversación cabe en el presupuesto de la fase 1 (32.768 tokens), la plantilla es estable por prefijo y hay tokens supervisados | T5.3 |

Ningún candidato falló estos controles. Era lo esperado, porque la fase 3 ya aplicaba el contrato antes de verificar. Aquí se repiten sobre los datos guardados, de forma independiente, antes de exportar.

## 4. Duplicados

La fase 3 dedujo copias por archivo, no por sección. Cuando una sección es idéntica en dos versiones, pero el archivo cambia en otra parte, cada copia de la sección se usó como semilla distinta. Así salieron casos que piden lo mismo con otras palabras, a veces en otro idioma.

**Regla.** Dentro de un conjunto y una situación, dos casos son duplicados si piden el mismo contenido. Se conserva el de menor `task_id`.

| Regla | Condición |
|---|---|
| a. Misma evidencia | La semilla es la misma sección, o una idéntica en otra versión, **y** citan las mismas líneas (Jaccard ≥ 0,5, sin contar la versión) **o** la respuesta es muy parecida (Jaccard de bigramas ≥ 0,4) |
| b. Misma pregunta | La pregunta es casi igual (Jaccard de trigramas ≥ 0,5), salga de donde salga |

**Cómo se calibró.** Se revisaron a mano todos los pares de la misma situación que salen de una misma sección (50 pares):

- Compartir sección **no basta**. La primera versión de la regla eliminaba casos que preguntan por aspectos distintos: la base de producción frente a la de stage, o el flujo Feed frente al Restock. Esos casos citan líneas distintas y se conservan.
- Las líneas citadas son la mejor señal: reconocen el mismo contenido aunque la pregunta esté parafraseada o en otro idioma.
- La respuesta parecida solo se compara entre casos de la misma sección. Entre secciones distintas daría falsos positivos, porque todas las aclaraciones de `falta_software` son casi iguales («¿Sobre qué software es tu consulta?»), y la guía advierte que eso no es un duplicado.

**Resultado.** Se eliminaron 21 duplicados: 19 en `train`, 1 en `validation` y 1 en `test`. La lista, con el motivo de cada uno, está en [data/reportes/fase4/estadisticas.md](../data/reportes/fase4/estadisticas.md). Queda una paráfrasis sin detectar que se vio en la revisión (`train-sin_version-026` / `-034`, sobre el manejo de errores): cita líneas distintas y su texto se parece poco.

**Entre conjuntos no hay duplicados posibles.** La fase 2 reparte software completos, y el control de aislamiento comprueba que ningún caso reciba documentos de otro conjunto.

**Cómo se evitaría en origen.** Que el plan de la fase 3 deduplicara las semillas por texto de sección y no solo por archivo. Hacerlo ahora cambiaría el plan de casi todas las tareas y obligaría a regenerarlas, así que se corrige aquí.

## 5. Revisión humana

La guía pide que una persona revise las referencias de `validation` y `test`, porque son la verdad de la evaluación. Si solo se revisa una parte, hay que identificarla y no presentar el resto como validado.

- `python -m src.fase4.run` crea `data/fase4/revision_humana.csv`, con una fila por caso de `validation` y `test` que pasó los controles automáticos.
- La forma más cómoda de revisar es el revisor interactivo:

  ```bash
  python -m src.fase4.revisar --conjunto test
  ```

  Muestra cada caso pendiente: la conversación, el texto de cada cita sacado del documento, los `answer_checks` y el veredicto del verificador. Se responde `a` para aprobar, `r` para rechazar (pide el motivo, que es obligatorio), `s` para saltar, `v` para ver la justificación de todos los criterios y `q` para salir. Cada decisión se guarda en el CSV al momento, así que se puede cortar y retomar: la siguiente vez empieza por el primer pendiente. Con `--id <task_id>` se revisa o cambia un caso concreto, y con `--todos` se recorren también los ya decididos.
- También se puede editar el CSV a mano, escribiendo `aprobar` o `rechazar` en la columna `decision` y, si se quiere, un `comentario`.
- Al volver a ejecutar `python -m src.fase4.run`, se aplican las decisiones. Los rechazados pasan a `rejected.jsonl` con el comentario como motivo. Las decisiones ya escritas se conservan al regenerar el CSV.
- Cada fila exportada lleva `revision_humana`: `aprobado`, `pendiente` (validation y test sin revisar) o `no_aplica` (train, que no se revisa completo).

**Qué revisar en cada caso.**
- Que la pregunta sea natural y corresponda a la situación.
- Que cada afirmación de la respuesta esté en las líneas citadas.
- Que lo que falta se declare sin inventarlo y sin decir que no existe.
- Que los `answer_checks` sean justos con una respuesta correcta redactada de otra forma.

No hace falta conocer el software, porque el texto de cada cita aparece al lado.

**Estado de esta entrega.** Los 175 casos de `validation` y `test` están marcados como `aprobar`, pero **la aprobación se hizo en bloque, como ejercicio del flujo, sin revisar cada caso**. Por eso, estas referencias deben tratarse como **verificadas por el LLM** (el verificador de la fase 3), no como validadas por una persona. Para una revisión real basta con recorrerlas con `python -m src.fase4.revisar --todos`.

## 6. Resultado

| Conjunto | Candidatos | Duplicados | Aceptados |
|---|---:|---:|---:|
| `train` | 230 | 19 | 211 |
| `validation` | 98 | 1 | 97 |
| `test` | 79 | 1 | 78 |
| **Total** | **407** | **21** | **386** |

Las 10 situaciones están en los tres conjuntos. Los duplicados se concentraban en `en_que_version` y `comparacion_versiones` de `train`, porque vendor-stockkeeper tiene cuatro versiones con muchas secciones iguales: de 17 y 16 casos quedan 11 y 15.

**Longitud en tokens con la plantilla de Qwen3.5:**

| Conjunto | Mediana | p95 | Máximo | Supervisados (mediana) |
|---|---:|---:|---:|---:|
| `train` | ~6.500 | ~22.600 | ~23.000 | ~250 |
| `validation` | ~11.100 | ~21.200 | ~21.300 | ~250 |
| `test` | ~4.650 | ~10.400 | ~10.500 | ~250 |

- **Ninguna conversación supera los 23.000 tokens.** Todas caben en el presupuesto de 32.768 de la fase 1.
- **Casi todo el texto son documentos.** Los tokens supervisados (la llamada y la respuesta) son unos 250 por conversación. Para entrenar habrá que elegir una longitud máxima de al menos 24.576 tokens; si se cortaran las conversaciones, se perdería justo la respuesta, que va al final.

Las cifras exactas están en [data/reportes/fase4/estadisticas.md](../data/reportes/fase4/estadisticas.md).

## 7. Salidas

| Archivo | Contenido |
|---|---|
| `data/fase4/train.jsonl` | Una conversación por línea en formato de chat con *tool calling* (`messages` + `tools`), más el caso de evaluación, los tokens y el estado de la revisión humana. Es la versión canónica: `version` es `null` |
| `data/fase4/sft/train.jsonl`, `validation.jsonl` | **La versión para entrenar con Hugging Face** (`SFTTrainer` de TRL): solo `id`, `situacion`, `messages`, `tools` y `chat_template_kwargs` = `{"enable_thinking": false}`, con `version: null` escrito `"null"`. Se cargan con `datasets.load_dataset("json", …)` y se probaron con TRL ([docs/fase5.md](fase5.md#4-entrenamiento)). `test` no se exporta aquí porque no se usa al entrenar |
| `data/fase4/validation.jsonl`, `test.jsonl` | El mismo formato. Para evaluar, al modelo solo se le envían los mensajes hasta la pregunta (sistema, historial y pregunta); la llamada esperada, los documentos esperados, la referencia y los `answer_checks` se comparan después |
| `data/fase4/rejected.jsonl` | Las tareas que no llegaron al dataset: etapa (fase 3, duplicado, revisión humana…) y motivo |
| `data/fase4/revision_humana.csv` | Las decisiones de la revisión humana de validation y test |
| `data/fase4/dataset_report.json` | Contabilidad, y por conjunto: situaciones, idiomas, tipos de evidencia, software, tokens y revisión humana |
| `data/fase4/dataset_manifest.json` | Hash y número de filas de cada archivo exportado, hashes de las entradas, del contrato y de los prompts, modelos de la fase 3, tokenizer y versión de `transformers` |
| `data/reportes/fase4/estadisticas.md` | Las mismas cifras en tablas, con la lista de duplicados |

**Por qué los tres conjuntos tienen el mismo formato.** `validation` también se usa durante el entrenamiento, para calcular la pérdida en datos no vistos, y para eso necesita la conversación completa. `test` tiene el mismo formato por simplicidad. Que el modelo no vea su referencia lo garantiza el adaptador de evaluación, que corta la conversación antes de la llamada a la herramienta.

## 8. Tests

`src/tests/test_fase4.py`:

- **Mutaciones de la guía que se detectan con código:**
  - T4.1: una cita a un documento inexistente se rechaza.
  - Una cita fuera del documento, un hash de procedencia alterado y una salida de la herramienta modificada también se rechazan.
  - T4.6: un caso de `test` que recibe un documento de `train` se bloquea, igual que un caso asignado a un conjunto que no es el de su software.
  - T4.7: cada tarea tiene exactamente un estado final y los totales cuadran.
  - T4.8: todas las filas exportadas cumplen el contrato y sus fuentes existen con el mismo hash.
- **Duplicados:**
  - la misma sección en otra versión, con las mismas líneas, es duplicado;
  - la misma sección con otro aspecto (el par real de producción y stage) se conserva;
  - las aclaraciones genéricas idénticas no son duplicado;
  - situaciones distintas no se comparan.
- **Render:**
  - `null` se escribe como `null` sin modificar los datos;
  - T5.3: solo se supervisan la llamada y la respuesta, no la pregunta, el historial ni la salida de la herramienta.
- **Revisor interactivo** (sobre una copia del CSV):
  - cada decisión se guarda al momento;
  - un rechazo sin motivo se vuelve a pedir;
  - los casos ya decididos no se muestran;
  - se puede salir y retomar desde el primer pendiente.

**Las mutaciones semánticas de la guía** (T4.2 hecho falso con cita real, T4.3 respuesta irrelevante, T4.4 abstención excesiva, T4.5 versión mezclada) no se pueden detectar con código: las juzga el verificador. Comprobar que las rechaza requiere llamarlo y queda como paso aparte. Es el mismo material que servirá para calibrar al juez de la evaluación.

## 9. Reproducibilidad

```bash
python -m src.fase4.run
git status --short data/
```

Si `git status` no muestra nada, los datasets son idénticos byte a byte a los entregados. La primera ejecución descarga el tokenizer de Qwen3.5 (unos 13 MB) desde Hugging Face en la revisión fija; después se usa la copia local.
