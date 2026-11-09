# Fase 0 — Auditoría de la documentación

Este documento explica qué hace la fase 0, por qué está diseñada así y cómo interpretar cada salida. Los comandos para ejecutarla están en el [README](../README.md).

## 1. Objetivo

La documentación de `docs_raw/` viene de equipos distintos, con estructura inconsistente, contenido duplicado y partes rotas. Antes de generar datos de entrenamiento hay que saber qué parte es fiable. La fase 0 **etiqueta toda la documentación**: cada sección de cada software/versión termina evaluada y categorizada, sin excepciones. Con esas etiquetas responde tres preguntas:

1. **¿Qué es usable?** Secciones íntegras, sin contradicciones ni inconsistencias internas.
2. **¿Qué no es usable y por qué?** Contradicciones dentro del mismo software/versión, inconsistencias (nombres, rutas o valores que no cuadran), contenido roto, ilegible o sin contenido técnico.
3. **¿Qué no está documentado?** Partes que la propia documentación promete o referencia y no cubre.

Las fases siguientes solo generan datos de entrenamiento a partir de lo que esta fase marca como usable.

## 2. Diseño general

| Paso | Qué hace | Quién lo hace | Estado |
|---|---|---|---|
| 1 | Inventario, partición en secciones y chequeos automáticos | Código, determinista | Implementado |
| 2 | Clasificar cada sección (estado y categoría) y listar huecos | LLM A | Implementado |
| 3 | Validar las respuestas de A y de B: cobertura, valores permitidos, citas literales | Código | Implementado |
| 4 | Emitir un veredicto sobre cada clasificación de A | LLM B | Implementado |
| 5 | Etiqueta final: si A y B dan el mismo estado, se acepta; si no, una persona elige A o B (o se aplica una regla por defecto) | Código y persona | Implementado |
| 6 | Verificación de cobertura: toda sección tiene etiqueta final; si no, error | Código | Implementado |

Se ejecuta con dos comandos:

| Comando | Qué hace |
|---|---|
| `python -m src.fase0.run` ([`run.py`](../src/fase0/run.py)) | Pasos 1 a 4 y genera `data/fase0/human_review.csv` con las secciones en las que A y B dan estados distintos. |
| `python -m src.fase0.finalize` ([`finalize.py`](../src/fase0/finalize.py)) | Se ejecuta después de rellenar el CSV. Pasos 5 y 6, y genera `reports/fase0/estadisticas.md`. |

Cada paso también se puede ejecutar por separado, con los comandos indicados en su sección. Es útil para depurar o para probar con una sola versión.

Decisiones de fondo:

- **Unidad de auditoría: software/versión** (`docs_raw/<software>/<versión>/`). La consistencia se evalúa solo dentro de una misma versión. Que dos versiones digan cosas distintas es esperable y no es un defecto; las versiones se tratan en la deduplicación de la fase 2.
- **Cada software/versión se audita completo, en una sola llamada al LLM.** El corpus es pequeño: 16 unidades, 107 archivos y ~320 KB, y la unidad más grande ronda los 12k tokens. Así el LLM ve toda la documentación de esa versión a la vez y puede detectar contradicciones entre archivos.
- **Dos LLM de proveedores distintos.** A, de Anthropic, clasifica; B, de OpenAI, revisa cada clasificación de A. Que sean de proveedores distintos reduce los errores compartidos, aunque no los elimina. Si dan estados distintos, una persona elige cuál de los dos criterios usar.
- **El código verifica todo lo que se puede verificar sin interpretar:** cobertura, formatos y que las citas existan literalmente en el texto. Los LLM solo deciden lo que requiere leer y entender.

## 3. Paso 1 — Inventario, secciones y chequeos

Comando: `python -m src.fase0.extract`. Código: [`src/fase0/extract.py`](../src/fase0/extract.py).

No usa ningún LLM y es determinista: con el mismo `docs_raw/`, produce siempre los mismos archivos, byte a byte.

### 3.1 Inventario

Recorre `docs_raw/` en orden alfabético. Por cada archivo (se ignoran solo los `.DS_Store` de macOS) registra:
- la ruta;
- el software y la versión, que se toman del nombre de las carpetas;
- el tipo;
- el SHA-256 de sus bytes, que sirve para demostrar que el archivo de origen no cambió;
- su tamaño y su número de líneas.

Al final comprueba que el conjunto de archivos inventariados es exactamente el conjunto de archivos en disco.

### 3.2 Partición en secciones

La sección es la unidad que se etiqueta y la que después se usará para generar datos. Cada una conserva su archivo y su rango de líneas, para que cualquier dato derivado se pueda rastrear hasta su origen.

**Markdown** (`.md`):
- Se parte por títulos de nivel 1 y 2 (`#` y `##`). Los de nivel 3 o inferior quedan dentro de su sección. Así una sección es un tema completo, por ejemplo un endpoint con sus parámetros y ejemplos, y no un fragmento suelto.
- Los `#` dentro de bloques de código no son títulos. Suelen ser comentarios de bash.
- Se aceptan títulos sin espacio (`#API FRESH PRODUCTS DOCUMENTATION`), porque aparecen en el corpus.
- El texto anterior al primer título es su propia sección (tipo `markdown_preambulo`) si tiene contenido. Si solo son líneas en blanco, se une a la primera sección.
- Un título sin texto propio seguido directamente de un subtítulo (`# Components` y luego `## Database`) se une con esa subsección y su título pasa a ser `Components / Database`. Es estructura, no un hueco.
- Un título sin texto seguido de otro del mismo nivel (`# API` y luego `# Domain`) se conserva como sección y se marca `seccion_vacia`.
- Los títulos escritos en HTML (`<h2>`) no parten secciones: quedan como contenido.

**OpenAPI** (`swagger.yaml`):
- Una sección para la cabecera: `openapi`, `info`, `servers`, `tags`, `security`, hasta `paths:` inclusive.
- Una sección por operación (método + ruta, p. ej. `POST /v1/whitelist`). La línea de la ruta y sus parámetros comunes van con la primera operación de esa ruta.
- Una sección por cada bloque de nivel superior posterior a `paths`, como `components`.
- La partición se hace por líneas, no sobre el YAML ya interpretado, para conservar los números de línea exactos.

**JSON** (`documentationTypes.json`): una sección por archivo.

**Archivo vacío:** una sección de tipo `vacio`.

**Invariante:** en cada archivo, las secciones son contiguas, no se solapan y cubren todas las líneas, y la concatenación de sus textos reproduce el archivo exactamente. Si no se cumple, el proceso termina con error. Es la garantía de que ninguna parte de la documentación queda sin evaluar.

**Identificador:** `section_id = <software>/<versión>/<ruta dentro de la versión>#<n>`, donde `n` es el orden de la sección dentro del archivo, empezando en 0. Ejemplo: `vendor-stockkeeper-api/latest/guide/api.md#2`.

### 3.3 Chequeos automáticos

Detectan problemas objetivos que se pueden comprobar sin interpretar el texto. **No deciden por sí mismos si algo es usable**: se entregan a A como pistas. A y B deciden, porque, por ejemplo, una imagen ausente no afecta igual a una sección que vive del diagrama que a otra que solo tenía un logo.

| Tipo | Qué significa | Qué no permite concluir |
|---|---|---|
| `enlace_roto` | Un enlace a una página local que no existe, p. ej. un sidebar que promete `/support.md`. | No prueba que la página no exista en el sitio original; sí que su contenido no está en la muestra. Es candidato a hueco. |
| `ancla_rota` | Un enlace `#algo` que no corresponde a ningún título del archivo destino. | Puede ser un error tipográfico del enlace o una sección que falta; A lo decide con el contexto. |
| `recurso_ausente` | Una imagen u otro recurso referenciado que no está en la muestra. | Su contenido (p. ej. un diagrama de arquitectura) no está disponible y no se debe inventar. |
| `enlace_mal_formado` | Sintaxis de enlace rota, p. ej. `((https://...))`. | El destino puede ser válido; es un defecto de formato. |
| `enlace_correo_sin_mailto` | Un correo usado como enlace sin `mailto:`. | Defecto menor de formato. |
| `seccion_vacia` | Un título sin contenido, seguido de otro del mismo nivel. | — |
| `archivo_vacio` | Un archivo sin contenido. | — |
| `marcador_pendiente` | Una línea cuyo único contenido es un marcador como `TO DO.`, `TBD` o `FIXME`. Se exige la línea completa y en mayúsculas para no confundirlo con frases como "To do this, run…". | — |
| `entidad_html_en_codigo` | Bloques de código con `&#39;`, `&#34;`, `&gt;`… sin decodificar, típico de una exportación defectuosa. Se reporta una vez por archivo con el número de líneas afectadas. | El contenido se puede recuperar, pero tal cual no es código válido para copiar. |
| `json_invalido`, `yaml_invalido`, `utf8_invalido`, `openapi_sin_paths` | El archivo no se puede interpretar. | — |
| `metadatos_latest_resuelve_a` | `documentationTypes.json` de una carpeta `latest` apunta a una versión concreta. Es informativo. | No es un error por sí solo; es relevante si la versión resuelta es incoherente, p. ej. más antigua que otra de la muestra. |
| `metadatos_version_distinta`, `metadatos_software_distinto` | `documentationTypes.json` apunta a otra versión o a otro software distinto del de su carpeta. | — |
| `metadatos_spec_ausente`, `metadatos_guide_ausente` | Los metadatos declaran una especificación o guía que no está en la carpeta. | — |

**Cómo se resuelven los enlaces.** Estos sitios se generan con [docsify](https://docsify.js.org/), y los enlaces siguen sus convenciones, así que el chequeo las aplica:
- `/api` se resuelve desde la raíz de la guía; un enlace relativo se prueba primero desde el archivo y luego desde la raíz.
- Si no tiene extensión, se prueba `.md`; si es una carpeta, su `README.md`.
- Se ignoran las opciones tras el destino (`':size=200'`) y los parámetros (`?raw=true`).
- `![color](#f0f0f0)` es el color de fondo de una portada docsify, no un ancla.
- Los enlaces externos (`http`, `https`, `mailto`) no se comprueban, porque el flujo debe funcionar sin red.

**Cómo se comparan las anclas.** Se reducen ancla y títulos a letras y dígitos en minúsculas y sin acentos (`#Get-Detail` ≈ `Get Detail`). Así se evitan falsos positivos por diferencias entre los algoritmos de slug de GitHub y docsify. La contrapartida es que un ancla que solo difiere en puntuación se da por buena; se prefirió eso a llenar la salida de falsos avisos.

### 3.4 Versiones idénticas

Para cada software/versión se calcula una huella: el hash de la lista de sus archivos con el hash de cada uno. Si dos versiones tienen la misma huella, son idénticas archivo por archivo, y la segunda heredará las etiquetas de la primera sin volver a llamar a los LLM. Cada sección heredada conserva su propio registro, así que no desaparece del conteo.

Solo se hereda cuando la versión completa es idéntica. Que coincida un archivo suelto no basta, porque otra sección de la versión nueva podría contradecirlo. En la muestra solo ocurre con `catalog-portfolio-api/latest`, idéntica a `catalog-portfolio-api/0.0.1-test-bench-v2a`.

### 3.5 Salidas

Todas en `data/fase0/`, en formato JSON Lines (un objeto JSON por línea).

**`units.jsonl`** — un registro por software/versión.

| Campo | Contenido |
|---|---|
| `unit` | `<software>/<versión>` |
| `software`, `version` | Tomados de las carpetas |
| `n_files`, `n_sections`, `bytes` | Tamaño de la unidad |
| `fingerprint` | Huella de contenido de la versión completa |
| `identica_a` | Versión idéntica previa de la que hereda etiquetas, o `null` |

**`inventory.jsonl`** — un registro por archivo.

| Campo | Contenido |
|---|---|
| `path` | Ruta relativa a `docs_raw/` |
| `unit`, `software`, `version` | Unidad a la que pertenece |
| `file_type` | `markdown`, `openapi` o `json` |
| `sha256`, `bytes`, `n_lines` | Huella y tamaño del archivo original |
| `parse_ok` | `false` si el archivo no se pudo interpretar |
| `checks` | Lista de `{tipo, linea, detalle}` con los chequeos de la tabla anterior |
| `n_sections` | Número de secciones en que se partió |

**`sections.jsonl`** — un registro por sección.

| Campo | Contenido |
|---|---|
| `section_id` | Identificador único (ver 3.2) |
| `unit`, `software`, `version`, `file` | Procedencia |
| `n` | Orden de la sección dentro del archivo, desde 0 |
| `kind` | `markdown`, `markdown_preambulo`, `openapi_cabecera`, `openapi_operacion`, `openapi_bloque`, `json` o `vacio` |
| `title` | Título de la sección (vacío si no tiene) |
| `line_start`, `line_end` | Rango de líneas en el archivo original, ambos incluidos, empezando en 1 |
| `text` | Texto original de esas líneas, sin modificar |
| `text_sha256`, `n_chars` | Huella y tamaño del texto |

### 3.6 Resultado sobre la muestra entregada

- 16 unidades software/versión, 107 archivos y 360 secciones, que cubren el 100% de las líneas.
- Una versión idéntica: `catalog-portfolio-api/latest` = `0.0.1-test-bench-v2a`.

Chequeos:

| Tipo | Casos | Ejemplos |
|---|---:|---|
| `recurso_ausente` | 29 | Diagramas de arquitectura (`media/arch.png`, `workflow-api-architecture.png`) y logos no exportados |
| `ancla_rota` | 20 | En las 4 versiones de `vendor-stockkeeper-api`, la tabla de endpoints de `api.md` apunta a secciones de detalle que no existen |
| `enlace_roto` | 14 | `catalog-portfolio-api`: `brand-management/README.md` enlaza `lifecycle.md`, `creation.md`, `updates.md`, `activation.md` y `validation.md`, que no existen. El sidebar de `order-workflow-api` enlaza `/support.md` y la portada de `price-engine-api` un `README.md` inexistente |
| `metadatos_latest_resuelve_a` | 9 | `2p-revenue-optimizer-api/latest` apunta a `0.0.3-rc-1`, anterior a la `0.2.2` presente en la muestra |
| `seccion_vacia` | 7 | `# API` seguido directamente de `# Domain` en `vendor-stockkeeper-api/*/guide/api.md` |
| `entidad_html_en_codigo` | 5 archivos | `vendor-stockkeeper-api/0.0.10-stock-consumer` (`api.md`, `important.md`); las otras 3 versiones de ese software están limpias. También `order-workflow-api` (`use-cases.md`, `services/database.md`, `services/bigq.md`) |
| `marcador_pendiente` | 3 | `price-engine-api/latest/guide/general.md`: Introducción y Responsabilidades contienen solo `TO DO.` |
| `enlace_correo_sin_mailto` | 2 | `traffic-gate-api/latest/guide/README.md` |
| `enlace_mal_formado` | 1 | `traffic-gate-api/latest/guide/sections/processes.md`: `((https://go.dev/...))` |

### 3.7 Limitaciones conocidas

- **Hay secciones grandes.** La mayor, "The data pipelines" de `demand-forecast-docs`, tiene ~28k caracteres porque solo se parte por títulos de nivel 1 y 2. Para la auditoría no es un problema, porque el LLM recibe la versión completa. Para generar datos en fases posteriores puede convenir subdividirla.
- **El contenido en HTML se trata como texto.** Los títulos `<h2>` no parten secciones.
- **No se comprueban los enlaces externos.** El flujo debe poder correr sin red.
- **El swagger de `price-engine-api` tiene un bloque `models:` en el nivel superior,** que no es OpenAPI estándar. Queda como su propia sección para que el LLM lo evalúe.

### 3.8 Tests

[`src/tests/test_extract.py`](../src/tests/test_extract.py) cubre cada regla de partición y los chequeos principales con casos pequeños escritos a mano. Además comprueba sobre el corpus real que cada sección de cada archivo coincide exactamente con sus líneas de origen.

## 4. Pasos 2 a 4 — Clasificación (A) y validación (B)

Comandos: `python -m src.fase0.label --role A` y después `python -m src.fase0.label --role B`. Código: [`src/fase0/label.py`](../src/fase0/label.py).

### 4.1 Un prompt fijo por LLM

Hay un único prompt para A y otro para B, en archivos que se pueden leer y revisar:

- [`src/fase0/prompts/clasificador_a.md`](../src/fase0/prompts/clasificador_a.md): A clasifica cada sección y lista los huecos.
- [`src/fase0/prompts/validador_b.md`](../src/fase0/prompts/validador_b.md): B revisa cada clasificación de A y cada hueco.

El prompt es el mismo para todas las versiones. Lo único que cambia de una llamada a otra son los datos: el software, la versión, los chequeos automáticos del paso 1 y todas sus secciones, cada una con su `section_id`, archivo, líneas y texto. B recibe además la clasificación de A.

Se hace una llamada por software/versión, para que el LLM vea a la vez todas las secciones de esa versión y pueda detectar contradicciones entre ellas.

### 4.2 Criterio de clasificación

"Usable" se define por el uso final: **de la sección se pueden sacar pares pregunta-respuesta cuya respuesta está en el propio texto y es fiable.**

| Estado | Significado |
|---|---|
| `usable` | Información técnica concreta y fiable: endpoints, parámetros, configuración, procedimientos, arquitectura, reglas, alertas… |
| `parcial` | Útil, salvo algunas afirmaciones concretas no fiables. A las cita literalmente; se excluyen y el resto se usa. |
| `no_usable` | No sirve para generar pares fiables. |

Toda sección `parcial` o `no_usable` lleva al menos un problema con uno de estos motivos:

| Motivo | Significado |
|---|---|
| `contradiccion` | Choca con otra sección de la misma versión. |
| `inconsistencia` | Nombres, rutas o valores que no cuadran con el resto. |
| `incompleto` | Contenido pendiente (`TO DO`), cortado, o que depende de algo ausente, como un diagrama. |
| `roto` | Formato dañado que altera el contenido. |
| `vacio` | Sin contenido. |
| `sin_contenido_tecnico` | Navegación, portadas, metadatos o contactos de personas. Excluir los contactos evita además entrenar con datos personales. |

Categorías: `endpoint_api`, `modelo_datos`, `configuracion`, `procedimiento`, `arquitectura`, `troubleshooting`, `descripcion_general`, `navegacion_metadatos` y `otro`.

Un **hueco** es algo que la propia documentación anuncia o referencia y no cubre: una página enlazada que no existe, un endpoint listado sin detalle o un apartado pendiente. No cuenta lo que el LLM crea que "debería" estar documentado.

### 4.3 Validación por código (paso 3)

Cada respuesta se comprueba antes de aceptarla:

- **Cobertura:** la respuesta contiene exactamente las secciones enviadas, sin faltantes, extras ni duplicados.
- **Valores:** el estado, la categoría y el motivo pertenecen a sus listas cerradas. Esto lo garantiza además el esquema JSON que se exige al LLM.
- **Coherencia:** una sección `usable` no tiene problemas; una `parcial` o `no_usable` tiene al menos uno. Si B dice estar de acuerdo, su estado y su categoría deben coincidir con los de A.
- **Citas:** cada cita debe aparecer literalmente en el texto de la sección, salvo diferencias de espacios en blanco. Así el LLM no puede justificar una decisión con texto inventado.

Si algo falla, se hace **un único reintento**, mostrándole al LLM su respuesta y la lista de errores. Las secciones que sigan fallando quedan marcadas como no válidas y, en el paso 5, pasan a la cola de decisión. Nunca quedan sin etiqueta.

### 4.4 Caché de respuestas

Cada respuesta se guarda en `data/cache/fase0/<a|b>/<software>__<versión>.json`, con una clave que depende del prompt, el modelo, el esquema y los mensajes enviados. Si se vuelve a ejecutar sin cambios, se usa la respuesta guardada y no se llama al LLM. Si cambia el prompt, el modelo o la documentación, la clave cambia y se vuelve a llamar. El caché se sube al repositorio: es lo que permite reproducir exactamente los resultados (ver la sección 6).

### 4.5 Versiones idénticas

Una versión idéntica a otra ya procesada (sección 3.4) hereda las etiquetas sin llamar al LLM. Solo se cambian los identificadores, y el campo `heredada_de` indica de qué sección viene cada etiqueta.

### 4.6 Salidas

**`labels_a.jsonl`** — una línea por sección, con la clasificación de A.

| Campo | Contenido |
|---|---|
| `section_id`, `unit` | Sección clasificada |
| `estado`, `categoria` | Clasificación de A |
| `problemas` | Lista de `{motivo, cita, otras_secciones, explicacion}` |
| `justificacion` | Una frase con el porqué del estado |
| `valida`, `errores` | Resultado de la validación por código |
| `intentos`, `modelo`, `heredada_de` | Trazabilidad |

**`labels_b.jsonl`** — una línea por sección, con el veredicto de B.

| Campo | Contenido |
|---|---|
| `de_acuerdo` | Si B coincide con A |
| `estado`, `categoria` | Los que B considera correctos |
| `cita` | Si el estado de B no es `usable`, texto literal que lo respalda |
| `explicacion` | Si discrepa, qué falló en la clasificación de A |
| `valida`, `errores`, `intentos`, `modelo`, `heredada_de` | Como en A |

**`gaps_a.jsonl` / `gaps_b.jsonl`** — los huecos que lista A (descripción, evidencia citada y sección) y el veredicto de B sobre cada uno.

## 5. Pasos 5 y 6 — Etiqueta final y verificación de cobertura

Código: [`src/fase0/finalize.py`](../src/fase0/finalize.py). No usa LLM y es determinista. La cola de revisión la genera `python -m src.fase0.run` al terminar; la etiqueta final, `python -m src.fase0.finalize`.

### 5.1 Reglas de la etiqueta final

| Situación | Etiqueta final | `origen` |
|---|---|---|
| A y B dan el mismo estado, y sus dos respuestas son válidas | Estado y categoría de A | `acuerdo_a_b` |
| Estados distintos, o alguna respuesta no válida, y la persona eligió `A` o `B` en el CSV | Estado y categoría del modelo elegido | `decision_humana` |
| Lo mismo, pero la fila quedó vacía | Estado y categoría del modelo elegido por la regla por defecto | `decision_por_defecto` |

- **Solo el estado decide si hace falta revisión.** Si A y B dan el mismo estado pero distinta categoría, no se revisa y se usa la categoría de A. La categoría describe el contenido, pero no decide si la sección se usa para entrenar.
- **Regla por defecto para filas vacías:** gana el modelo que eligió `parcial`; si ninguno lo eligió, el que eligió `usable`. `parcial` es el término medio: aprovecha la sección pero excluye las afirmaciones dudosas que citó ese modelo. Si ninguno eligió `parcial`, se prefiere conservar el contenido que uno de los dos modelos consideró fiable.
- **No se decide por votación ni por confianza del modelo:** decide la persona, o una regla fija y documentada.

Una sección `parcial` se usa sin sus **afirmaciones excluidas**:
- si A y B coinciden: las citas de los problemas de A y, si B también la ve parcial, la cita de B;
- si se eligió un modelo, por decisión humana o por defecto: solo las citas de ese modelo.

### 5.2 Revisión humana

`python -m src.fase0.run` escribe en `data/fase0/human_review.csv` las secciones en las que A y B dan estados distintos, o en las que alguna respuesta no pasó la validación. El archivo se abre con Excel o cualquier hoja de cálculo. Cada fila tiene:
- la sección, su archivo y sus líneas;
- su contenido completo (columna `contenido`);
- el estado, la categoría, la justificación y los problemas citados por A;
- el estado, la categoría, la explicación y la cita de B;
- el motivo de la revisión;
- la columna `decision`, que es la única que se rellena.

**La persona no reclasifica la sección: solo elige qué criterio es el correcto, el de A o el de B.** Así la revisión es rápida y toda etiqueta final procede de un análisis completo, con justificación y citas verificadas. El procedimiento:

1. Leer el contenido y los dos criterios.
2. Escribir `A` o `B` en la columna `decision`. Se acepta también en minúscula. Las filas pueden quedar vacías: se completan con la regla por defecto.
3. Guardar el CSV y ejecutar `python -m src.fase0.finalize`.

Detalles:
- **Las decisiones se conservan** si se vuelve a ejecutar `run`: el CSV se regenera manteniendo la columna `decision` de cada sección.
- **Un valor distinto de `A` o `B` detiene el proceso,** con un error que indica la fila.
- **Las copias de versiones idénticas no aparecen en el CSV** (sección 3.4). Toman automáticamente la decisión de su sección original, porque el texto y los veredictos son los mismos. Esto se determina por código, comparando huellas de contenido, sin LLM.
- **Las decisiones son parte de los resultados:** se suben al repositorio y se reproducen igual que el resto.

### 5.3 Huecos

Los huecos no pasan por revisión humana, porque no alimentan el entrenamiento: sirven para saber qué falta. Un hueco queda `confirmado` si su evidencia es una cita literal válida y B está de acuerdo.

### 5.4 Verificación de cobertura (paso 6)

Antes de escribir nada, el código comprueba que:
- cada sección del paso 1 tiene exactamente una etiqueta final, sin faltantes, extras ni duplicados;
- todo estado es `usable`, `parcial` o `no_usable`;
- toda categoría es una de las permitidas.

Si algo falla, el proceso termina con error y lista las secciones afectadas. No existe una salida parcial de la fase 0.

### 5.5 Salidas

| Archivo | Contenido |
|---|---|
| `data/fase0/section_status.jsonl` | **La salida principal de la fase 0, la que usarán las fases siguientes.** Una línea por sección con: procedencia (`file`, `line_start`, `line_end`), `estado`, `categoria`, `origen`, `motivo_revision`, `decision` (`A`, `B` o vacío si A y B coincidieron), `afirmaciones_excluidas`, los veredictos completos de A y de B, y `heredada_de`. |
| `data/fase0/gaps.jsonl` | Huecos con su descripción, evidencia, sección, si están `confirmado`s y la explicación de B. |
| `data/fase0/human_review.csv` | Cola de revisión, con las decisiones tomadas. |
| `reports/fase0/estadisticas.md` | Estadísticas principales, para el reporte final: corpus, chequeos, uso de los LLM, acuerdo entre A y B (con la matriz de estados), decisiones humanas y por defecto, etiqueta final por versión y por categoría, motivos, material disponible para generar datos y huecos confirmados. |

### 5.6 Inspeccionar secciones en la terminal

[`src/utils/show_section.py`](../src/utils/show_section.py) muestra una sección con su texto original y los veredictos de A y de B, incluidas todas las citas. Sirve para revisar ejemplos concretos, por ejemplo durante la presentación:

```bash
python -m src.utils.show_section --llm A                       # una sección al azar
python -m src.utils.show_section --llm B --veredicto parcial   # al azar entre las que B marcó parcial
python -m src.utils.show_section --llm A --id <section_id>     # una sección concreta
```

- El filtro (`--llm`, `--veredicto`) se aplica sobre el modelo elegido; el otro modelo se muestra para comparar.
- `--seed` fija la elección al azar.

## 6. Reproducibilidad

No todos los pasos son deterministas, y conviene distinguirlos.

**Paso 1 (código): determinista.** Con el mismo `docs_raw/` produce los mismos archivos byte a byte:
- no usa LLM, red ni fecha;
- recorre los archivos en orden alfabético;
- no escribe rutas absolutas en las salidas.

Se verificó ejecutándolo dos veces y en un clon limpio en otra ruta; en los dos casos el resultado fue idéntico. Para que esto también valga en Windows, `.gitattributes` impide que Git convierta los saltos de línea de `docs_raw/` y `data/`. Esa conversión cambiaría los hashes y el texto de las secciones.

**Pasos con LLM (2 y 4): no deterministas.** Un LLM puede dar respuestas distintas al mismo prompt:
- Las CLIs no permiten fijar la temperatura.
- `claude-opus-5-5` no acepta ese parámetro ni por API.
- Incluso con temperatura 0, los proveedores no garantizan respuestas idénticas.

La reproducibilidad de estos pasos se consigue con un **caché**. Cada respuesta de A y de B se guarda en `data/cache/` con una clave que depende del prompt, del modelo y del contenido auditado, y el caché se sube al repositorio. Al volver a ejecutar la fase se leen esas respuestas en lugar de llamar al LLM. Así el resultado es idéntico al entregado, sin sesión ni API key.

Si se borra el caché o se cambia de modelo, la fase se vuelve a ejecutar contra los LLM y las etiquetas pueden variar en los casos dudosos. Hay dos mecanismos que acotan esa variación:
- El código rechaza cualquier salida que no cumpla el formato o que cite texto que no existe en la documentación.
- Lo que B no confirma va a revisión humana, en lugar de aceptarse.

**Revisión humana: reproducible.** Las decisiones se guardan en un archivo, y al volver a ejecutar la fase se aplican de nuevo.
