# Fase 5 — Estadísticas del diseño

Generado por `python -m src.fase5.run`. No se ha entrenado ningún modelo: las cifras describen los datos y el presupuesto de cada experimento.

## 1. Experimentos

| Experimento | Conversaciones | Épocas | Pasos | Ejemplos vistos | Tokens supervisados vistos |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 | — | — | — | — | — |
| E1 | 211 | 3 | 80 | 633 | 169686 |
| E2 | 166 | 3.81 | 80 | 633 | 170144 |

## 2. Situaciones en el entrenamiento

| Situación | E1 | E2 |
| --- | ---: | ---: |
| version_explicita | 34 | 34 |
| sin_version | 29 | 29 |
| software_en_historial | 30 | 30 |
| en_que_version | 11 | 11 |
| comparacion_versiones | 15 | 15 |
| evidencia_parcial | 22 | 0 |
| sin_evidencia | 23 | 0 |
| contradiccion | 19 | 19 |
| falta_software | 14 | 14 |
| sin_documentos | 14 | 14 |

## 3. Entradas de inferencia

- `validation`: 97 entradas (83 con 2 mensajes, 14 con 4 mensajes).
- `test`: 78 entradas (67 con 2 mensajes, 11 con 4 mensajes).

Cada entrada termina en la pregunta del usuario. No incluye la llamada esperada, los documentos esperados, la respuesta de referencia ni los `answer_checks`.

