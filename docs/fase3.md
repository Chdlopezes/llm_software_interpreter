# Fase 3 — Generación de los ejemplos candidatos

Este documento explica cómo se generan y verifican las conversaciones de entrenamiento, validación y prueba. Para ejecutar la fase basta con `python -m src.fase3.run` (ver el [README](../README.md#fase-3--generación-de-los-ejemplos)).

## 1. Objetivo

La fase 3 produce, para cada conjunto de la fase 2, **candidatos**: una conversación lista para entrenar y su caso de evaluación, en el formato definido en la fase 1. El caso de evaluación incluye la llamada esperada, los documentos esperados, la respuesta de referencia y los `answer_checks`.

Los candidatos salen verificados, pero **todavía no son el dataset final**. En la fase 4 se eliminan duplicados, se hace la revisión humana, se miden las longitudes en tokens y se exportan.

Cada caso sirve a las tres mediciones de la evaluación:

| Medición | Cómo se mide | Qué deja preparado esta fase |
|---|---|---|
| ¿Llama a la herramienta y con los argumentos correctos? | Con código, comparando con `expected_tool` | Los argumentos los decide el programa (sección 3), no el LLM |
| ¿Trae los documentos correctos? | Con código, por IDs y hashes | `expected_document_ids` es la salida real de la herramienta |
| ¿La respuesta es correcta y está bien citada? | Las citas, con código; el contenido, con un LLM juez y una rúbrica | La respuesta de referencia, con citas, y los `answer_checks` en texto libre para el juez |

**No se generan ejemplos malos a propósito.** Todos los casos de los tres conjuntos son referencias correctas. Para calibrar al juez de la evaluación se construirá en la fase 4 un conjunto aparte: respuestas aprobadas de `validation` corrompidas a propósito y etiquetadas por una persona.

## 2. Cuántos casos y de qué tipo

**Tamaño.** Cada conjunto tiene 2 casos por sección aprovechable:

| Conjunto | Secciones | Casos |
|---|---:|---:|
| `train` | 116 | 232 |
| `validation` | 50 | 100 |
| `test` | 40 | 80 |

**Situaciones.** La mezcla es la misma en los tres conjuntos, para que la evaluación mida lo mismo que se entrena. Las cuotas se redondean por el método del mayor resto, así que siempre suman el total.

| Grupo | Situación | Proporción |
|---|---|---:|
| Responder | `version_explicita`, `sin_version`, `software_en_historial` | 15% cada una |
| Versiones | `en_que_version`, `comparacion_versiones` | 7,5% cada una |
| Falta información | `evidencia_parcial`, `sin_evidencia` | 10% cada una |
| Contradicción | `contradiccion` | 8% |
| Sin llamada o sin documentos | `falta_software`, `sin_documentos` | 6% cada una |

**Idioma.** El 20% de los casos son en inglés y el resto en español. Lo decide un hash del identificador de la tarea, así que el reparto es siempre el mismo.

## 3. Plan de tareas (sin LLM)

`src/fase3/tasks.py` decide de forma determinista qué caso se genera, de qué parte de la documentación sale y con qué argumentos.

**Semillas.** Cada tarea parte de una semilla real del conjunto:

| Semilla | De dónde sale | Situaciones |
|---|---|---|
| Sección | `data/fase0/section_status.jsonl` (usable o parcial, sin copias heredadas) | Casi todas |
| Hueco | `data/fase1/huecos.jsonl` | `evidencia_parcial`, `sin_evidencia` |
| Conflicto | `data/fase1/restricciones.jsonl` | `contradiccion` |

- **Copias idénticas.** Los huecos y conflictos que se repiten en varias versiones se cuentan una sola vez, por el hash del documento.
- **Repetición de secciones.** Cada sección se usa como máximo 2 veces por conjunto, y antes de repetir alguna se usan todas las libres. Así, dos situaciones no comparten semilla (y casi la misma pregunta) mientras queden secciones sin usar. En el segundo uso, el generador debe preguntar por un aspecto secundario de la sección.
- **Tipos de evidencia.** Las secciones se intercalan por su tipo principal (tabla, código, diagrama, OpenAPI, fórmula, texto), para repartir los tipos entre las situaciones.
- **Versiones.** Las comparaciones y `en_que_version` usan primero las secciones cuyo contenido cambia entre versiones.
- **Huecos que no alcanzan.** `sin_evidencia` usa huecos distintos de los de `evidencia_parcial` mientras haya. Si se acaban, se usa una sección con **dato ausente**: el generador pregunta algo plausible que no está en ningún documento entregado, y el verificador lo confirma.

**Argumentos de la llamada.** Los fija el programa según la situación, siguiendo las reglas de la fase 1:

| Situación | Argumentos |
|---|---|
| `falta_software` | Ninguno: no se llama a la herramienta |
| `sin_version`, `en_que_version`, `comparacion_versiones` | El software, sin versión |
| `sin_documentos` | El software y una versión que no existe en el catálogo |
| Las demás | El software y la versión de la semilla |

El generador nunca elige los argumentos. Escribe una pregunta que los implique, el código comprueba lo que puede comprobar (por ejemplo, que la pregunta nombre la versión cuando debe y no la nombre cuando no debe) y el verificador comprueba el resto.

## 4. Generación y verificación, por rondas

Intervienen dos LLM de proveedores distintos, cada uno con su propia configuración en `.env`:

| Tarea | Variables | Modelo usado |
|---|---|---|
| Generador | `LLM_GENERADOR_BACKEND`, `LLM_GENERADOR_MODEL` | Claude Opus 5.5, por Claude Code |
| Verificador | `LLM_VERIFICADOR_BACKEND`, `LLM_VERIFICADOR_MODEL` | gpt-6-luna, por la API de OpenAI |

El programa se niega a ejecutarse si los dos son el mismo modelo.

```
ronda 1..3
  1. generador, por tarea
       recibe: situación, argumentos, salida real de la herramienta (documentos completos,
               con número de línea y líneas no citables), semilla, reglas, un ejemplo de
               referencia y, si lo hay, el intento anterior rechazado con su motivo
       devuelve: pregunta, respuesta con citas, answer_checks (o «omitir», con el motivo)
  2. código: check_example de la fase 1 + coherencia de la pregunta con los argumentos
       si falla → el error vuelve al generador (hasta 2 correcciones)
  3. verificador, por grupos de hasta 10 casos del mismo software
       devuelve, por caso, un resultado para cada criterio de la rúbrica
  4. el programa decide: aprobado, o rechazado → a la ronda siguiente, con el motivo
tras 3 rondas, los que sigan rechazados quedan «omitidos», con su motivo
```

**La conversación la ensambla el programa.** El generador solo escribe la pregunta, la respuesta y los `answer_checks`. La llamada a la herramienta, su salida y el prompt de sistema salen del código de la fase 1, así que los documentos de cada conversación son exactamente los que devuelve la herramienta.

### 4.1 Validación por código

Antes de gastar una llamada al verificador, el código comprueba:

- **Contrato de la fase 1** (`check_example`): las citas tienen el formato correcto, apuntan a documentos entregados y a rangos que existen, y no usan líneas no citables. También comprueba los esquemas de la conversación y del caso.
- **Coherencia con la situación:** la pregunta nombra el software exactamente como en el catálogo, salvo en `falta_software` y `software_en_historial`; nombra la versión cuando la situación lo exige y no la nombra cuando no debe; el historial solo existe en `software_en_historial`; hay entre 3 y 5 `answer_checks`.

### 4.2 Verificador

La rúbrica sigue la guía de evaluación. Para cada caso, el verificador devuelve `cumple`, `parcial`, `no_cumple` o `no_aplica` en cada criterio, con una justificación que menciona las líneas:

| Criterio | Pregunta |
|---|---|
| `pregunta_coherente` | ¿Es natural, está en el idioma del caso e implica exactamente los argumentos? |
| `correccion_tecnica` | ¿Los hechos coinciden con los documentos? |
| `responde_pregunta` | ¿Resuelve todo lo que los documentos permiten? |
| `respaldo_citas` | ¿Cada cita sostiene su afirmación? |
| `cobertura_citas` | ¿Cada afirmación técnica tiene cita? |
| `evidencia_insuficiente` | ¿Declara lo que falta, y falta de verdad en todos los documentos entregados? |
| `sin_abstencion_injustificada` | ¿Aprovecha la evidencia disponible? |
| `consistencia` | ¿Evita contradicciones y mezclar versiones? |
| `conflictos` | ¿Muestra las dos fuentes de un conflicto sin elegir una? |
| `answer_checks_validos` | ¿Los criterios son verificables y no exigen una redacción concreta? |

**El verificador no decide la aprobación, la decide el programa.** Un caso se aprueba solo si todos los criterios son `cumple` o `no_aplica`. Si el verificador marca `needs_review`, el caso queda como `revisar`, para la revisión humana de la fase 4.

**Por qué recibe los documentos completos y no solo la sección citada.** Para confirmar que algo «no está documentado» o detectar un conflicto, tiene que ver todo lo que recibió el modelo. Con un extracto aprobaría respuestas que declaran como faltante algo que está en otro archivo.

**Por qué por grupos.** Los documentos son el 90–97% del prompt del verificador, y muchos casos del mismo software reciben los mismos documentos. Verificando caso por caso, cada documento se enviaba decenas de veces. Por grupos, cada llamada lleva la unión de los documentos del grupo una sola vez, al principio del prompt, que es lo que permite aprovechar también la caché de prompt del proveedor. Después vienen los casos, y cada uno indica qué documentos le entregó la herramienta. El verificador debe juzgar cada caso solo con los suyos, y el código ya comprueba que las citas apunten a documentos entregados.

| | Por caso | Por grupos |
|---|---:|---:|
| Llamadas al verificador en la corrida completa | ~445 | 56 |
| Tokens de entrada del verificador, todas las rondas (estimados por tamaño del prompt) | ~6,0 M | ~1,2 M (20%) |

**Por qué hasta 10 casos por grupo.** Con más casos, la salida (unos 500 tokens por caso) se acerca a los límites del modelo y la revisión de cada caso pierde atención.

### 4.3 El motivo del rechazo vuelve al generador

En la primera versión, tras un rechazo se escribía un caso nuevo sin feedback, y en el piloto el generador repitió el mismo error en los tres intentos. Ahora el nuevo intento recibe el caso rechazado, el motivo y la justificación de cada criterio que falló. En el piloto, los rechazos bajaron del 31% al 9%.

El riesgo de esta decisión es que el generador aprenda a contentar al verificador en lugar de corregir el caso. Aquí es bajo, porque los rechazos son por citas que no respaldan lo afirmado, no por estilo, y la fase 4 incluye revisión humana.

## 5. Resultado

| Conjunto | Tareas | Verificados | Omitidos |
|---|---:|---:|---:|
| `train` | 232 | 230 | 2 |
| `validation` | 100 | 98 | 2 |
| `test` | 80 | 79 | 1 |
| **Total** | **412** | **407** | **5** |

- **Llamadas:**
  - generador: 464, de las cuales 15 fueron correcciones por errores de código;
  - verificador: 56, que hicieron 445 verificaciones de caso.
- **Rechazos del verificador:** 38 (9%), resueltos casi todos en la ronda 2. Los criterios que más fallaron fueron `respaldo_citas` (20), `correccion_tecnica` (19) y `cobertura_citas` (17).
- **Todas las situaciones están cubiertas en los tres conjuntos.** El detalle por situación, idioma y tipo de evidencia está en [reports/fase3/estadisticas.md](../reports/fase3/estadisticas.md).

**Omitidos.** De los 5, cuatro los descartó el propio generador porque la semilla no permitía un caso válido:
- dos secciones casi vacías o cuyo único contenido técnico está en líneas no citables;
- una comparación cuya diferencia entre versiones está solo en líneas no citables;
- un conflicto cuya segunda fuente es un archivo que la herramienta no devuelve.

El quinto agotó las 3 rondas: el verificador consideró, las tres veces, que una cita no respaldaba del todo lo afirmado. Omitir en estos casos es lo correcto: forzarlos produciría referencias malas.

**Revisión manual.** Se revisó una muestra de cada situación en `test` comparando cada cita con las líneas reales del documento. Las citas contienen lo que afirman, las comparaciones atribuyen cada dato a su versión y los casos de falta de información declaran lo que falta sin inventarlo.

### Ver ejemplos

[`src/utils/show_example.py`](../src/utils/show_example.py) muestra candidatos al azar. Para cada uno muestra la conversación completa, el texto de cada cita sacado del documento, los `answer_checks`, el veredicto del verificador y, si los hubo, los rechazos anteriores:

```bash
python -m src.utils.show_example --conjunto test                          # uno al azar de test
python -m src.utils.show_example --situacion contradiccion -n 3 --seed 7  # tres, siempre los mismos
python -m src.utils.show_example --idioma en --tipo tabla                 # en inglés, citando una tabla
python -m src.utils.show_example --software traffic --buscar whitelist    # por software y texto
python -m src.utils.show_example --rechazados                             # aprobados tras un rechazo
python -m src.utils.show_example --id test-sin_evidencia-001 --criterios  # uno concreto, con toda la rúbrica
python -m src.utils.show_example --omitidos                               # tareas omitidas y su motivo
```

Los filtros se combinan entre sí. `python -m src.utils.show_example --help` los lista todos.

## 6. Limitaciones

- **`test` es pequeño.** Tiene 40 secciones para 80 casos, así que cada sección se usa dos veces y varios casos tratan el mismo tema (por ejemplo, la tabla `rule_header`) desde preguntas distintas. La fase 4 revisa los casos casi duplicados.
- **Pocas fórmulas.** Solo hay una en el corpus, y por eso solo aparece en `train`.
- **El verificador es un LLM.** Los criterios deterministas los comprueba el código, pero la corrección del contenido depende del verificador. La revisión humana de la fase 4 lo contrasta con una muestra.
- **Tokens.** Las cifras de tokens son estimaciones por tamaño del prompt (unos 3,5 caracteres por token). No se registra el uso real que devuelve la API.

## 7. Salidas

| Archivo | Contenido |
|---|---|
| `data/fase3/candidatos.jsonl` | Un candidato por línea: conversación (mensajes y herramienta, formato de chat con *tool calling*), caso de evaluación, veredicto del verificador, semilla y número de intentos |
| `data/fase3/generation_log.jsonl` | Cada llamada al generador y al verificador: ronda, corrección, modelo, clave de caché y resultado; en el verificador, también el grupo y el veredicto completo, incluidos los rechazos |
| `data/fase3/coverage_report.json` | Cuotas y resultados por conjunto y situación, idiomas, omitidos y uso de cada sección |
| `data/fase3/cache/` | Respuestas de los LLM: `<tarea>.json` las del generador, `verificador/<clave>.json` las del verificador (una por grupo) |
| `reports/fase3/estadisticas.md` | Resultado por conjunto y situación, idioma, tipo de evidencia, calidad del generador y omitidos |

## 8. Tests

`src/tests/test_fase3.py` no llama a ningún LLM: el generador y el verificador son falsos.

- **Plan:**
  - las cuotas suman el total;
  - el plan es determinista;
  - cada tarea pertenece a un software de su conjunto;
  - los argumentos corresponden a la situación;
  - ninguna sección se usa más de dos veces, ni se repite mientras queden libres;
  - las comparaciones de `test` empiezan por versiones que difieren.
- **Ciclo:**
  - un caso válido queda verificado y cumple el contrato de la fase 1;
  - un error de código vuelve al generador;
  - un rechazo vuelve al generador con su motivo;
  - agotar las rondas omite el caso;
  - los casos del mismo software se verifican en una sola llamada, con cada documento una sola vez;
  - la caché evita repetir llamadas;
  - la entrada del modelo no contiene la respuesta de referencia ni los criterios.
- **Decisión:**
  - la coherencia de la pregunta detecta un software o una versión mal nombrados;
  - la aprobación la decide el programa.

## 9. Reproducibilidad

```bash
python -m src.fase3.run --solo-cache
git status --short data/ reports/
```

`--solo-cache` usa solo las respuestas guardadas y falla si falta alguna, así que no llama a ningún LLM ni necesita API keys. Tampoco depende del `.env`: usa los modelos registrados en `generation_log.jsonl`, que son los que produjeron las salidas (Claude Opus 5.5 y gpt-6-luna). Esto importa porque la clave de la caché incluye el modelo. Si `git status` no muestra nada, los candidatos son idénticos a los entregados.

La clave de cada llamada en la caché depende del prompt de sistema, del prompt completo (documentos, semilla, intento, rechazo anterior), del esquema y del modelo. Si cambia cualquiera de ellos, por ejemplo una línea de `generador.md`, esa llamada se vuelve a hacer.

Para probar cambios sin la corrida completa: `--piloto` genera el primer caso de cada situación de `train`, y `--conjunto`, `--situacion` y `--limite` seleccionan un subconjunto. Estas pruebas escriben en `data/fase3/piloto/` o `data/fase3/parcial/` y no tocan las salidas entregadas.
