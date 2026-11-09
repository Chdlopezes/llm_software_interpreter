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
| 2 | Etiquetar cada sección (estado y categoría) y listar huecos | LLM A | Pendiente |
| 3 | Validar la salida de A: cobertura, valores permitidos, citas literales | Código | Pendiente |
| 4 | Validar cada etiqueta de A | LLM B | Pendiente |
| 5 | Etiqueta final: si B confirma, se acepta; si no, pasa a revisión humana | Código y persona | Pendiente |
| 6 | Verificación de cobertura: toda sección tiene etiqueta; si no, error | Código | Pendiente |

Decisiones de fondo:

- **Unidad de auditoría: software/versión** (`docs_raw/<software>/<versión>/`). La consistencia se evalúa solo dentro de una misma versión. Que dos versiones digan cosas distintas es esperable y no es un defecto; las versiones se tratan en la deduplicación de la fase 2.
- **Cada software/versión se audita completo, en una sola llamada al LLM.** El corpus es pequeño: 16 unidades, 107 archivos y ~320 KB, y la unidad más grande ronda los 12k tokens. Así el LLM ve toda la documentación de esa versión a la vez y puede detectar contradicciones entre archivos.
- **Dos LLM de proveedores distintos.** A, de Anthropic, etiqueta; B, de OpenAI, valida cada etiqueta de A. Que sean de proveedores distintos reduce los errores compartidos, aunque no los elimina. Lo que B no confirma va a revisión humana.
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
| `enlace_correo_sin_mailto` | 2 | `traffic-gate-api/latest/guide/README.md` |
| `enlace_mal_formado` | 1 | `traffic-gate-api/latest/guide/sections/processes.md`: `((https://go.dev/...))` |

### 3.7 Limitaciones conocidas

- **Hay secciones grandes.** La mayor, "The data pipelines" de `demand-forecast-docs`, tiene ~28k caracteres porque solo se parte por títulos de nivel 1 y 2. Para la auditoría no es un problema, porque el LLM recibe la versión completa. Para generar datos en fases posteriores puede convenir subdividirla.
- **El contenido en HTML se trata como texto.** Los títulos `<h2>` no parten secciones.
- **No se comprueban los enlaces externos.** El flujo debe poder correr sin red.
- **El swagger de `price-engine-api` tiene un bloque `models:` en el nivel superior,** que no es OpenAPI estándar. Queda como su propia sección para que el LLM lo evalúe.

### 3.8 Tests

[`src/tests/test_extract.py`](../src/tests/test_extract.py) cubre cada regla de partición y los chequeos principales con casos pequeños escritos a mano. Además comprueba sobre el corpus real que cada sección de cada archivo coincide exactamente con sus líneas de origen.

## 4. Reproducibilidad

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
