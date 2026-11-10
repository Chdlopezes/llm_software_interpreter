# Fase 5 — Diseño del entrenamiento y de las comparaciones

Este documento es el diseño del experimento (el `experiment_design.md` de la guía): qué se entrenaría, contra qué se compararía y qué resultado cambiaría la decisión. **No se ha entrenado ningún modelo**, así que aquí no hay pérdidas ni métricas de un modelo. La configuración propuesta está en [src/fase5/experimento.yaml](../src/fase5/experimento.yaml), y `python -m src.fase5.run` comprueba que el diseño sea coherente con los datos (sección 7).

## 1. Hipótesis

Entrenar con SFT sobre conversaciones que muestran el comportamiento completo mejora, respecto del mismo modelo sin ajustar:
- llamar a la herramienta con los argumentos correctos;
- responder con lo que dicen los documentos;
- citar cada afirmación;
- declarar lo que falta.

Las conversaciones incluyen casos con evidencia suficiente, insuficiente, parcial y contradictoria, y casos sin software o sin documentos.

Lo que se quiere medir es si el modelo **usa evidencia nueva**, no si recuerda la de entrenamiento. Por eso validation y test son de software que el modelo nunca vio al entrenar (fase 2).

**Por qué SFT.** Se supervisa una conducta concreta: dada una pregunta, la llamada y la respuesta correctas. No hace falta preentrenamiento continuo (CPT), porque el modelo no tiene que memorizar la documentación: la recibe por la herramienta. Tampoco hace falta RL, porque hay respuestas objetivo verificadas. Cualquiera de los dos necesitaría otra hipótesis y otros datos.

## 2. Modelo

| Dato | Valor |
|---|---|
| Identificador | `Qwen/Qwen3.5-4B` |
| Revisión | `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` (la misma con la que la fase 4 midió los tokens) |
| Licencia | Apache 2.0 |
| Arquitectura | 32 capas, híbrida: tres de atención lineal por cada una de atención completa. Incluye un encoder de visión, que no se usa |
| Contexto | 262.144 tokens. Nuestras conversaciones llegan a ~23.000 |
| Plantilla de chat | La del modelo, con llamadas a herramientas en formato `<tool_call>`, con `enable_thinking=False` y `version: null` escrito como `null` (ver [docs/fase4.md](fase4.md#2-modelo-a-ajustar-qwen35-4b)) |

**Por qué este modelo.** Es abierto y pequeño, admite los contextos que construimos y soporta llamadas a herramientas en su plantilla. Su atención híbrida abarata los contextos largos. Los cuatro modelos pequeños de la familia comparten tokenizer y, con la misma configuración, producen el mismo texto, así que cambiar de tamaño no obliga a rehacer los datos.

## 3. Experimentos

| | Qué es | Para qué |
|---|---|---|
| **B0** | Qwen3.5-4B sin ajuste | Línea de base: qué hace el modelo solo con el prompt de sistema |
| **E1** | SFT con LoRA sobre todo `train` (211 conversaciones, las 10 situaciones) | La hipótesis principal |
| **E2** | Como E1, sin `evidencia_parcial` ni `sin_evidencia` (166 conversaciones) | Medir qué aportan los casos con información insuficiente o parcial |

**B0 recibe exactamente lo mismo que E1:** el mismo prompt de sistema, las mismas herramientas, las mismas preguntas y la misma configuración de generación. La única diferencia son los pesos (T5.1).

**Presupuesto de E2.** E2 tiene menos conversaciones. Si se entrenara con las mismas épocas que E1, también vería menos ejemplos, y una diferencia de resultados podría deberse al volumen y no a qué casos faltan. Por eso E2 usa **los mismos pasos que E1**: ve el mismo número de ejemplos, repartido en más épocas. El cambio de exposición queda explícito (T5.4):

| | Conversaciones | Épocas | Pasos | Ejemplos vistos | Tokens supervisados vistos |
|---|---:|---:|---:|---:|---:|
| E1 | 211 | 3 | 80 | 633 | ~170.000 |
| E2 | 166 | 3,81 | 80 | 633 | ~170.000 |

- **Lo que se mantiene fijo:** el modelo inicial, el número de pasos y de ejemplos vistos, y los tokens supervisados (casi idénticos, porque las respuestas de todas las situaciones tienen una longitud parecida).
- **Lo que cambia:**
  - la composición de los datos;
  - las veces que se repite cada conversación de E2 (3,81 frente a 3).

  Si E2 sale peor en abstención, puede deberse a que faltan esos casos o a que se repiten más los otros. El diseño no separa esas dos causas, y así debe reportarse.

## 4. Entrenamiento

Propuesta de partida (`src/fase5/experimento.yaml`):

| Parámetro | Valor | Motivo |
|---|---|---|
| Método | SFT con LoRA | Pocos datos (211 conversaciones): ajustar todos los pesos sobreajustaría y costaría mucho más |
| LoRA | r = 16, alpha = 32, dropout 0,05 | Valores habituales para un ajuste de conducta con pocos datos |
| Módulos | `q_proj`, `k_proj`, `v_proj`, `o_proj` (atención completa), `in_proj_qkv`, `in_proj_z`, `out_proj` (atención lineal) y `gate_proj`, `up_proj`, `down_proj` (MLP), solo en `model.language_model`. Encoder de visión y embeddings congelados | Nombres comprobados en el modelo diminuto, que tiene la misma arquitectura |
| Qué se supervisa | Solo la llamada a la herramienta y la respuesta, los mensajes del asistente tras la última pregunta | El resto es contexto. Verificado en la fase 4 (T5.3) |
| Longitud máxima | 24.576 tokens, sin truncar y sin *packing* | La conversación más larga de `train` tiene ~23.000. Truncar cortaría la respuesta, que va al final |
| Batch | 1 por dispositivo × 8 de acumulación = 8 conversaciones | Las conversaciones son largas; con 211, son 27 pasos por época |
| Épocas (E1) | 3 | Con pocos datos, varias pasadas; el checkpoint se elige en validation |
| Optimizador | AdamW, tasa 1e-4, programa coseno, 5% de *warmup*, sin *weight decay* | Tasa habitual para LoRA |
| Precisión | bf16, con *gradient checkpointing* | Necesario para 24k tokens por conversación |
| Semilla | 42 | |

**Cómo se entrena con Hugging Face.** El entrenamiento usa el `SFTTrainer` de TRL con LoRA (PEFT): [src/fase5/entrenar.py](../src/fase5/entrenar.py) lee `data/fase4/sft/{train,validation}.jsonl` y esta configuración. Al probarlo aparecieron cuatro puntos que, sin resolver, habrían arruinado el entrenamiento sin dar ningún error:

| Punto | Qué pasaba | Cómo se resuelve |
|---|---|---|
| Máscara de pérdida | La plantilla de Qwen3.5 no tiene marcas `{% generation %}` | Con `assistant_only_loss=True`, TRL 1.17 reconoce la plantilla y usa la suya de entrenamiento (`qwen3_5_think_training`). Supervisa cada turno del asistente, incluido su `<|im_end|>`, para que el modelo aprenda a terminar, y nada más |
| `version: null` | Se escribiría «None» | La exportación SFT ya lo trae como `"null"` (fase 4) |
| Razonamiento | TRL renderizaría con razonamiento | Cada fila lleva `chat_template_kwargs: {"enable_thinking": false}`, que TRL pasa a la plantilla |
| Longitud | `max_length` vale 1.024 por defecto en TRL y cortaría casi todas las conversaciones, y con ellas la respuesta | Se fija en 24.576 |

**Una diferencia con la máscara de la fase 4.** En las 30 conversaciones de `software_en_historial`, TRL también entrena el turno del asistente del historial («Perfecto, cuéntame qué necesitas…»), y lo escribe con un bloque `<think>` vacío que la plantilla de inferencia no pone. Se acepta, por dos razones:
- es una respuesta breve y verificada, sin contenido técnico;
- la diferencia de render es solo ese bloque vacío.

Si se quisiera evitar, la alternativa es pasar a TRL datos ya tokenizados (`input_ids` + `labels`) con la máscara de la fase 4 (`tramos_supervisados`).

**Prueba del flujo (`python -m src.fase5.entrenar --prueba`).** Corre el mismo script con un modelo diminuto de Qwen3.5 (`trl-internal-testing/tiny-Qwen3_5ForConditionalGeneration-Think`) en CPU, con 4 conversaciones y 2 pasos. Ese modelo tiene la misma arquitectura, la misma plantilla y el mismo vocabulario que el 4B. Resultado:
- TRL carga los datos sin errores.
- En la primera conversación supervisa solo la respuesta y su `<|im_end|>` (13 de 590 tokens).
- No corta nada, y evalúa en `validation`.
- La pérdida es finita (12,4, el valor esperado de un modelo con pesos aleatorios y 248.320 tokens de vocabulario, ln 248.320 ≈ 12,42).
- Guarda el adaptador. LoRA quedó en las 10 capas previstas del modelo de lenguaje y en ninguna del encoder de visión.

No es un entrenamiento real: no hay GPU en este entorno, y el modelo diminuto no aprende nada útil.

**Cómputo (supuesto, a confirmar).** Con LoRA, bf16 y *gradient checkpointing*, una conversación de 24k tokens con un modelo de 4B debería caber en una GPU de 80 GB. No se ha medido. Lo primero sería una prueba corta (unas pocas conversaciones largas) para confirmar memoria y tiempo por paso.

## 5. Inferencia

Igual para B0, E1 y E2:

| Parámetro | Valor |
|---|---|
| Entrada | Solo el prompt de sistema, el historial y la pregunta (`data/fase5/entradas_{validation,test}.jsonl`) |
| Herramienta | `obtener_documentacion`, ejecutada por el arnés con el catálogo de la fase 1. El modelo decide si llamarla y con qué argumentos |
| Razonamiento | `enable_thinking=False` |
| Decodificación | Voraz (temperatura 0), hasta 1.024 tokens nuevos |
| Llamadas | Hasta 2 por caso. Si el modelo pide una tercera, el caso cuenta como fallo de llamada |

**Por qué la entrada termina en la pregunta.** La primera medición de la evaluación es si el modelo llama a la herramienta y con qué argumentos. Si se le diera la llamada, no habría nada que medir. Por eso el arnés ejecuta la herramienta con los argumentos que el modelo elija, y la segunda medición compara los documentos que recibió con los esperados.

Se guarda cada respuesta con el ID del caso, el experimento y la configuración (`predictions.jsonl`, fase 6).

## 6. Selección y parada

- **Se elige con `validation`, nunca con `test`** (T5.5). Los candidatos son el checkpoint al final de cada época de E1 y de E2.
- **Criterio:** la mayor corrección y completitud en `validation`, sin empeorar el respaldo de citas ni la abstención correcta respecto de B0. Las métricas son las de la fase 6.
- **Márgenes (pendientes).** Cuánto tiene que mejorar la corrección y cuánto puede caer como máximo el respaldo de citas o la abstención se fijan **antes** de ver ningún resultado comparativo, y se escriben aquí. Propuesta para discutir:
  - una mejora de al menos 5 puntos en corrección;
  - una caída de como mucho 2 puntos en respaldo y en abstención.

  Con 97 casos de `validation`, una diferencia de uno o dos casos no basta para afirmar una mejora.
- **Límite de iteraciones:** como máximo 3 configuraciones probadas en `validation` antes de ir a `test`.
- **`test` se evalúa una sola vez,** con la configuración elegida, al cierre. Si después se ajusta algo mirando sus errores, deja de ser una prueba limpia.
- **Un ajuste que no mejora a B0 no es un éxito** solo porque se entrenó. Se reporta igual, como resultado negativo.

## 7. Comprobaciones del diseño

`python -m src.fase5.run` prepara las entradas de inferencia, calcula el presupuesto de cada experimento y comprueba:

| Test | Qué comprueba | Cómo |
|---|---|---|
| T5.1 Paridad | B0, E1 y E2 tienen la misma inferencia | Hay un único bloque de inferencia; ningún experimento puede redefinirlo |
| T5.2 Contrato de entrada | La entrada tiene contexto y pregunta, sin referencias ni criterios | Cada entrada termina en la pregunta del caso y es un prefijo de la conversación de referencia. No contiene la respuesta de referencia, los `answer_checks` ni los metadatos del caso |
| T5.3 Máscara de pérdida | Se supervisan la llamada y la respuesta, y nada más | Verificado en la fase 4 (`src/tests/test_fase4.py`) |
| T5.4 Presupuesto | Qué se mantiene fijo entre E1 y E2 | Mismos pasos y ejemplos vistos. El reporte muestra las épocas y los tokens de cada uno |
| T5.5 Test reservado | La selección no usa test | La configuración exige `seleccion.conjunto: validation` |

`src/tests/test_fase5.py` comprueba cada control también con su mutación: una entrada que incluye la referencia o metadatos, un experimento con otra temperatura y una selección con `test`. Las tres se detectan.

**Tests del entrenamiento:**
- **Hecho:** `python -m src.fase5.entrenar --prueba` (sección 4). TRL carga los datos, supervisa solo lo que debe, no corta, la pérdida es finita y LoRA queda en los módulos previstos.
- **Futuro, en GPU:**
  - una prueba de sobreajuste con unas pocas conversaciones: el modelo tiene que poder memorizarlas, y si no puede, hay un error de plantilla, máscara o configuración;
  - medir la memoria y el tiempo por paso con conversaciones de 24k tokens.

## 8. Qué está fijado y qué está pendiente

| Fijado | Pendiente |
|---|---|
| Modelo y revisión | Confirmar memoria y tiempo con una prueba corta en GPU |
| Datos de E1 y E2 y su presupuesto | Márgenes numéricos del criterio de selección |
| Qué se supervisa y cómo se enmascara (TRL, probado) | Hiperparámetros definitivos, si la prueba en GPU obliga a cambiarlos |
| Módulos LoRA, script de entrenamiento y dependencias | |
| Configuración de inferencia, igual para todos | |
| Selección con validation, test una sola vez | |

## 9. Salidas

| Archivo | Contenido |
|---|---|
| `src/fase5/experimento.yaml` | La configuración propuesta de B0, E1 y E2 |
| `src/fase5/entrenar.py` | Entrena E1 o E2 con TRL y LoRA; `--prueba` comprueba el flujo en CPU |
| `requirements-entrenamiento.txt` | Dependencias solo para entrenar: PyTorch, TRL, PEFT y `datasets` |
| `data/fase5/entradas_validation.jsonl`, `entradas_test.jsonl` | Lo que recibirán los modelos en inferencia: `messages` hasta la pregunta y `tools` |
| `data/fase5/experimentos.json` | La configuración y el presupuesto de cada experimento, con las conversaciones de `train` que usa |
| `reports/fase5/estadisticas.md` | Experimentos, situaciones en el entrenamiento y entradas de inferencia |
