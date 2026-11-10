# Fase 2 — Separación en entrenamiento, validación y prueba

Este documento explica en detalle cómo se separan los conjuntos y por qué. Para ejecutar la fase basta con `python -m src.fase2.run` (ver el [README](../README.md#fase-2--separación-en-conjuntos)).

## 1. Objetivo

La fase 2 asigna cada software a **entrenamiento** (`train`), **validación** (`validation`) o **prueba** (`test`) **antes de generar ninguna pregunta**. Así se evalúa si el modelo aprendió el comportamiento —llamar bien a la herramienta, leer, citar y abstenerse cuando falta información— sobre documentación que nunca vio al ajustar los pesos.

| Conjunto | Uso |
|---|---|
| `train` | Ajustar los pesos |
| `validation` | Iterar prompts, reglas y decisiones; comparar el modelo base con el ajustado |
| `test` | Medición final, una sola vez y con el experimento cerrado |

**El catálogo de la herramienta es siempre el completo.** El reparto no cambia lo que devuelve `obtener_documentacion`; decide a qué conjunto va cada conversación. Una conversación pertenece al conjunto del software sobre el que pregunta, así que ninguna conversación de `train` contiene documentos de `validation` ni de `test`. Las que no llegan a recibir documentos (`falta_software`, `sin_documentos`) van al conjunto del software del que salió la pregunta. La fase 3 lo consulta con `conjunto_de(software)`.

Es **determinista y no usa LLM**.

## 2. Criterio

**Lo importante es que en cada conjunto se puedan plantear los mismos tipos de pregunta, no las mismas preguntas.** Cuántas preguntas hay de cada tipo se balancea después, en la fase 3.

### 2.1 Datos de cada software

Todos se calculan a partir de las fases 0 y 1:

| Dato | Fuente | Uso |
|---|---|---|
| Secciones aprovechables (`usable` + `parcial`, sin copias heredadas) | `data/fase0/section_status.jsonl` | Tamaño: es lo que se reparte en 60/20/20 |
| Líneas de cada tipo de contenido: tablas, código, diagramas, OpenAPI y fórmulas | `tipos_evidencia` de `data/fase1/catalogo.jsonl`; cada texto idéntico se cuenta una vez | Mínimo obligatorio |
| Si tiene varias versiones, y si su contenido difiere | Hashes del catálogo | Mínimo obligatorio |
| Huecos y conflictos | `data/fase1/huecos.jsonl`, `data/fase1/restricciones.jsonl` | Mínimo obligatorio |

### 2.2 Unidad: el grupo de software

Cada software va entero a un conjunto, con todas sus versiones. Así, las copias idénticas entre versiones quedan siempre juntas.

Si dos software comparten contenido, por ejemplo porque uno copió el README del otro, deben ir al mismo conjunto. Si no, la prueba se haría sobre texto ya visto en el entrenamiento. Se consideran **un grupo** cuando comparten 3 o más líneas de más de 25 caracteres. En este corpus no hay ninguno: solo una línea larga aparece en dos software, y es un header de curl. Con muchos miles de documentos, esta comparación de todos contra todos se sustituiría por MinHash/LSH, que encuentra los casi duplicados sin comparar cada par.

### 2.3 Nivel 1: mínimo obligatorio

Un reparto que no cumple estas condiciones se descarta, por cerca que esté del 60/20/20.

| Condición | Tipo de pregunta que habilita |
|---|---|
| Cada conjunto tiene tablas, código, diagramas y OpenAPI | Preguntas sobre cada tipo de evidencia |
| Cada conjunto tiene huecos | `evidencia_parcial`, `sin_evidencia` |
| Cada conjunto tiene conflictos | `contradiccion` |
| Cada conjunto tiene algún software con varias versiones | `en_que_version`, `comparacion_versiones` |
| `test` tiene un software cuyas versiones difieren en contenido | Comparaciones con diferencias reales en la medición final |
| vendor-stockkeeper y payment-promise van a `train` | Los usan las conversaciones de referencia de la fase 1; si estuvieran en evaluación, la contaminarían |

- **Elementos escasos.** Un elemento que aparece en menos de 3 grupos no puede estar en los tres conjuntos, así que no se exige. En este corpus es la fórmula, que solo aparece en demand-forecast.
- **Versiones que difieren solo en prueba.** Solo dos software tienen versiones con contenido distinto: vendor-stockkeeper y 2p-revenue. Como vendor-stockkeeper va obligatoriamente a `train`, la condición solo puede exigirse en un conjunto de evaluación, y se exige en `test`.

### 2.4 Nivel 2: objetivo

Entre los repartos que cumplen el mínimo se elige el más cercano a **60 / 20 / 20 en secciones aprovechables**: el que menos se aleja sumando la diferencia de cada conjunto con su porcentaje objetivo. Los empates se resuelven en este orden:

1. `validation` y `test` lo más parecidos en tamaño;
2. `test` el más grande, porque es la medición final y con más casos varía menos;
3. el orden alfabético de la asignación, para que el resultado sea siempre el mismo.

**Por qué no se exige que cada conjunto reproduzca la distribución del corpus.** Lo ideal sería que cada conjunto tuviera el 20% de las tablas, el 20% de los diagramas, etc. Con 10 software no es posible, porque cada tipo se concentra en uno o dos: demand-forecast tiene el 40% de las líneas de diagrama, zenith el 51% del OpenAPI y catalog-portfolio el 52% de las tablas. El reparto que más se acerca a esa distribución sigue lejos y deja `train` en el 52%. Por eso se exige la **presencia** de cada elemento y se optimiza el tamaño. Con muchos software, la distribución sí se puede reproducir, y bastaría con añadirla al objetivo.

### 2.5 Cómo se busca el reparto

- **Pocos grupos** (12 o menos sin asignar): se prueban todas las combinaciones, es decir, todas las formas de asignar cada grupo a un conjunto. Para cada una se comprueba el mínimo y se calcula su distancia al objetivo. En este corpus quedan 8 software libres, que dan 3⁸ = 6.561 combinaciones; 138 cumplen el mínimo.
- **Muchos grupos:** probar todas deja de ser posible, porque crecen como 3ⁿ. Se ordenan los grupos de mayor a menor tamaño y cada uno va al conjunto que más lejos está de su objetivo. Al final se comprueba el mínimo; con muchos software se cumple casi siempre. Un test lo comprueba con 200 software simulados: el resultado queda a menos de un punto del 60/20/20 y cumple el mínimo.

El criterio y los datos son los mismos en los dos casos. Solo cambia la forma de buscar el reparto.

## 3. Resultado

| Conjunto | Software | Secciones |
|---|---|---:|
| `train` | vendor-stockkeeper, payment-promise, zenith-keeper, demand-forecast, order-workflow | 116 (56%) |
| `validation` | catalog-portfolio, price-engine | 50 (24%) |
| `test` | traffic-gate, 2p-revenue, unified-transaction-configs | 40 (19%) |

El 60/20/20 exacto no se alcanza porque los software son piezas grandes: catalog-portfolio por sí solo es el 21% del material.

**Tipos de pregunta por conjunto** (detalle en [data/reportes/fase2/estadisticas.md](../data/reportes/fase2/estadisticas.md)): los tres conjuntos permiten todos los tipos, con dos excepciones que no se pueden resolver con este corpus:

- **Comparación de versiones con diferencias reales en `validation`.** Sus versiones son idénticas (catalog-portfolio), así que la respuesta correcta siempre será «no cambia».
- **Preguntas sobre fórmulas fuera de `train`.** Hay una sola fórmula en todo el corpus.

**Puntos débiles de `test`,** que deberá compensar la fase 3:
- **Pocos huecos** (7): se generarán también preguntas cuya respuesta no está en ningún documento devuelto.
- **Poco código** (31 líneas).

**Limitación.** Tres software de prueba son una muestra pequeña. Los resultados de `test` indican generalización a documentación nueva **de este corpus**, no una garantía general. El reporte final dará las cifras por software, además del total.

## 4. Salidas

| Archivo | Contenido |
|---|---|
| `data/fase2/splits.json` | Criterio aplicado, grupos, perfil de cada software, asignación, y por conjunto sus software, proporción, cobertura y documentos con su hash |
| `data/reportes/fase2/estadisticas.md` | Reparto, tipos de pregunta por conjunto, cobertura, perfiles y fugas entre conjuntos |

## 5. Tests

`src/tests/test_fase2.py`:
- **Agrupación:** los software que comparten contenido forman un grupo.
- **Elementos escasos:** no se exigen.
- **Mínimo obligatorio:** se detecta cuando falta un elemento o faltan versiones distintas en `test`, cuando un software forzado está fuera de `train` y cuando un grupo queda repartido entre conjuntos.
- **Búsqueda:** la exhaustiva elige el reparto más cercano; la voraz, con 200 software simulados, cumple el mínimo y se queda a menos de un punto del objetivo.
- **Corpus real:** todos los software están asignados, los forzados están en `train`, `test` tiene versiones distintas y ningún documento idéntico cruza conjuntos.
- **Determinismo:** dos ejecuciones dan el mismo resultado.

## 6. Reproducibilidad

```bash
python -m src.fase2.run
git status --short data/
```

Si `git status` no muestra nada, el reparto es idéntico al entregado.
