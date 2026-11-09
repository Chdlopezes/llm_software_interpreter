# Datos de entrenamiento a partir de documentación técnica

Flujo local que convierte la documentación cruda de `docs_raw/` en datasets de entrenamiento y evaluación para un modelo abierto pequeño. Cada fila de salida se puede rastrear hasta su archivo y sus líneas de origen.

## Estado

| Fase | Qué hace | Estado |
|---|---|---|
| Preparación | Entorno, configuración de los LLM y verificación | Hecha |
| 0 — Auditoría | Etiqueta toda la documentación: qué es usable, qué no y por qué, y qué falta | Hecha |
| 1 — Catálogo y contrato | Catálogo de documentos, herramienta de consulta y criterios para construir los ejemplos | Hecha |

Las fases siguientes se añadirán a esta tabla a medida que se implementen.

## Estructura del repositorio

```
docs_raw/          Documentación cruda de entrada (no se modifica)
src/               Todo el código del flujo
  llm.py             Capa única para llamar a los LLM (CLI o API)
  check_setup.py     Verificación del entorno
  fase0/             Fase 0: auditoría de la documentación
  fase1/             Fase 1: catálogo, herramienta y contrato de los ejemplos
  utils/             Herramientas para inspeccionar resultados
  tests/             Tests deterministas
data/              Todas las salidas generadas por el flujo (se suben al repositorio)
reports/           Estadísticas de cada fase, para el reporte final
docs/              Explicación detallada de cada fase y sus decisiones
requirements.txt   Dependencias de Python, con versiones fijas
.env.example       Plantilla de las variables de entorno (LLM y API keys)
```

## Requisitos

- **Python 3.10 o superior.** Comprueba tu versión con `python3 --version`.
- Acceso a un modelo de **Anthropic** y a uno de **OpenAI**. El flujo usa dos LLM: **A** analiza la documentación (por defecto `claude-opus-5-5`) y **B** valida ese análisis (por defecto `gpt-6.1-sol`). Cada uno se puede usar de dos formas; elige la que tengas:

| LLM | Con tu sesión (sin API key) | Con API key |
|---|---|---|
| A | [Claude Code](https://docs.claude.com/en/docs/claude-code) — backend `claude_code` | `ANTHROPIC_API_KEY` — backend `anthropic_api` |
| B | [Codex CLI](https://github.com/openai/codex) — backend `codex` | `OPENAI_API_KEY` — backend `openai_api` |

  Las dos formas usan el mismo modelo y producen el mismo tipo de salida; solo cambia cómo te autenticas.

  El paso 1 de la fase 0 y toda la fase 1 no usan ningún LLM: para ejecutarlos solo necesitas Python.

## Configuración

Todos los comandos se ejecutan desde la raíz del repositorio.

### 1. Clonar el repositorio

```bash
git clone <url-del-repositorio>
cd <carpeta-del-repositorio>
```

### 2. Crear y activar un entorno virtual

El entorno virtual usa la versión de Python con la que lo crees. Si `python3 --version` muestra una versión anterior a 3.10, crea el entorno con un intérprete más nuevo. 

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Con el entorno activado, el prompt de la terminal empieza por `(.venv)`. A partir de aquí, `python` y `pip` se refieren a los del entorno virtual.

### 3. Instalar las dependencias

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

| Paquete | Para qué se usa |
|---|---|
| `anthropic` | LLM A con el backend `anthropic_api` |
| `openai` | LLM B con el backend `openai_api` |
| `python-dotenv` | Leer la configuración de `.env` |
| `pyyaml` | Validar los `swagger.yaml` de la documentación |
| `pytest` | Ejecutar los tests |

### 4. Configurar los LLM

```bash
cp .env.example .env
```

Abre `.env` con cualquier editor y elige el backend de cada LLM:

```
LLM_A_BACKEND=claude_code      # o anthropic_api
LLM_B_BACKEND=codex            # o openai_api
```

`LLM_A_MODEL` y `LLM_B_MODEL` pueden quedar vacíos para usar los modelos por defecto.

**Si usas un backend de sesión** (`claude_code` o `codex`), instala la CLI e inicia sesión una vez. Requiere [Node.js](https://nodejs.org/) 18 o superior:

```bash
# Claude Code
npm install -g @anthropic-ai/claude-code
claude          # inicia sesión con tu cuenta y sal con /exit

# Codex
npm install -g @openai/codex
codex login
```

El flujo llama a estas CLIs sin herramientas y en una carpeta temporal vacía: no leen ni modifican tus archivos. Además, quita las API keys del entorno al llamarlas, para que siempre usen tu sesión y no te cobren por API. Las llamadas cuentan contra los límites de tu suscripción.

**Si usas un backend de API** (`anthropic_api` u `openai_api`), pega la clave correspondiente después del `=`, sin comillas ni espacios:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

Solo hace falta la clave de los backends `*_api` que elijas. `.env` está en `.gitignore`, así que tus claves no se suben al repositorio.

### 5. Verificar la configuración

```bash
python -m src.check_setup
```

Este comando no llama a ningún LLM ni consume saldo. Comprueba:

- la versión de Python;
- que las dependencias estén instaladas;
- que exista `docs_raw/`;
- para cada LLM, lo que necesita su backend: la CLI instalada con sesión iniciada, o la API key definida.

Si todo está bien, la salida termina así:

```
[ok] Python 3.x.x
[ok] anthropic instalado
[ok] openai instalado
[ok] python-dotenv instalado
[ok] pyyaml instalado
[ok] pytest instalado
[ok] LLM A (análisis): claude_code:claude-opus-5-5
[ok] LLM B (validación): codex:gpt-6.1-sol
[ok] docs_raw/ encontrada (107 archivos)
[ok] data/ disponible para las salidas

Entorno listo. Para probar una llamada real: python -m src.check_setup --ping
```

Para confirmar que los dos LLM responden, haz una llamada mínima real a cada uno. Tarda unos segundos y consume muy pocos tokens:

```bash
python -m src.check_setup --ping
```

```
[ok] ping LLM A (claude_code:claude-opus-5-5) -> {'respuesta': 'ok'} en 6.1s
[ok] ping LLM B (codex:gpt-6.1-sol) -> {'respuesta': 'ok'} en 6.2s

Entorno listo.
```

Si algo falla, cada línea `[error]` indica qué falta y cómo corregirlo.

## Fase 0 — Auditoría de la documentación

Antes de generar datos de entrenamiento hay que saber qué parte de la documentación es fiable. La fase 0 parte toda la documentación en secciones y las etiqueta **todas**, sin excepciones:
- **Estado:** `usable`, `parcial` o `no_usable`. Una sección es usable si de ella se pueden sacar pares pregunta-respuesta cuya respuesta está en el propio texto y es fiable.
- **Categoría:** endpoint, configuración, procedimiento, etc.

También registra qué partes anuncia la documentación sin llegar a cubrirlas. Las fases siguientes solo generan datos a partir de las secciones `usable` y `parcial`.

La clasificación la hacen dos LLM de proveedores distintos: **A** clasifica cada sección y **B** revisa cada clasificación de A. Cuando dan estados distintos, una persona elige cuál de los dos criterios usar.

### 1. Ejecutar la auditoría

```bash
python -m src.fase0.run
```

Ejecuta todos los pasos hasta generar el archivo de revisión humana:
1. Inventario de archivos, partición en secciones y chequeos automáticos (sin LLM).
2. El LLM A clasifica cada sección.
3. El LLM B revisa cada clasificación de A.
4. Se escribe `data/fase0/human_review.csv` con las secciones en las que A y B dan estados distintos.

Cada respuesta de los LLM se guarda en `data/cache/`, que está en el repositorio. Por eso, con los resultados entregados, este comando **no llama a ningún LLM**: reutiliza las respuestas guardadas y no necesita sesión ni API key.

### 2. Revisar el CSV

Abre `data/fase0/human_review.csv` con Excel o cualquier hoja de cálculo. Cada fila es una sección en la que A y B discrepan, con:
- su contenido;
- el criterio de A: estado, categoría, justificación y problemas citados;
- el criterio de B: estado, categoría, explicación y cita.

En la columna `decision`, escribe **`A`** o **`B`**, el criterio que te parezca correcto, y guarda el archivo. La sección toma la etiqueta completa del modelo elegido.

Puedes dejar filas vacías. Al finalizar, se completan por defecto: gana el modelo que eligió `parcial`; si ninguno lo eligió, el que eligió `usable`.

### 3. Finalizar la fase

```bash
python -m src.fase0.finalize
```

Aplica las decisiones, verifica que todas las secciones tengan una etiqueta final válida (si no, termina con error) y escribe:

| Archivo | Contenido |
|---|---|
| `data/fase0/section_status.jsonl` | **Resultado de la fase 0.** Etiqueta final de cada sección, con su procedencia (archivo y líneas), su estado, su categoría y, si es `parcial`, las afirmaciones que no se deben usar. |
| `data/fase0/gaps.jsonl` | Partes que la documentación anuncia y no cubre. |
| `reports/fase0/estadisticas.md` | Estadísticas principales de la fase. |

El detalle de cada paso, los prompts, las reglas y el significado de cada archivo están en **[docs/fase0.md](docs/fase0.md)**.

## Fase 1 — Catálogo, herramienta y criterios de los ejemplos

El asistente que se va a entrenar no recibe fragmentos elegidos de antemano. Ante una pregunta técnica, **llama a la herramienta `obtener_documentacion(software, version)`**, que devuelve los **documentos completos** de ese software (de todas sus versiones si `version` es `null`), y responde citando `[documento:Linicio-Lfin]`. La fase 1 deja listo todo lo necesario para generar esas conversaciones, sin generar todavía ninguna:

1. **Catálogo.** Un documento por archivo de `docs_raw`, con su contenido normalizado (sin mover ninguna línea, para que las citas apunten al original), sus hashes y los tipos de evidencia que contiene (texto, tabla, código, diagrama, especificación OpenAPI, fórmula).
2. **Restricciones.** Los resultados de la fase 0, trasladados a líneas de cada documento.
3. **Herramienta.** El filtro exacto por software y versión, sin búsqueda semántica.
4. **Contrato.** El prompt de sistema, las reglas, el formato de la conversación de entrenamiento y del caso de evaluación, y 10 conversaciones de referencia escritas a mano.

**Decisión: los archivos de navegación quedan fuera del catálogo.** `_sidebar.md`, `_coverpage.md` y `documentationTypes.json` (33 de los 107 archivos) son índice, portada y metadatos de docsify. La fase 0 los clasificó como navegación, no contienen evidencia técnica y ocuparían contexto en cada llamada. El catálogo tiene 74 documentos.

### Criterios para crear los ejemplos

- **La fase 0 decide de qué se crean ejemplos, no qué ve el modelo.** La herramienta siempre devuelve los documentos completos, como en el uso real. Las preguntas y respuestas objetivo, en cambio, solo pueden apoyarse en secciones `usable` o `parcial`, y nunca en sus afirmaciones excluidas.
  - **Única excepción, la situación «contradicción»:** cita las líneas en conflicto para señalarlo, nunca como un hecho.
  - **Documentos idénticos en varias versiones:** una línea es no citable si lo es en cualquiera de las copias.
- **Diez situaciones que cubrir:**
  - versión explícita;
  - sin versión;
  - «¿en qué versión…?»;
  - comparación de versiones;
  - falta el software (se pregunta por él, sin llamar a la herramienta);
  - software ya indicado en un turno anterior;
  - evidencia parcial;
  - sin evidencia;
  - contradicción;
  - versión o software sin documentos.

  Los huecos de la fase 0 son la fuente de los casos sin evidencia completa, y sus contradicciones, la de los conflictos.
- **Llamada:** la versión solo se fija si la pregunta la nombra. En las preguntas «¿en qué versión?», en las comparaciones y cuando no se indica versión, va `null`.
- **Respuesta:**
  - usa solo los documentos devueltos;
  - cita cada afirmación técnica;
  - no mezcla versiones;
  - distingue «no está documentado» de «no se soporta»;
  - responde lo que tiene respaldo y declara lo que falta.
- **Idioma:** la mayoría de las preguntas en español y una parte en inglés. La respuesta va en el idioma de la pregunta.

Las reglas completas están en [src/fase1/contract/reglas.md](src/fase1/contract/reglas.md).

### Ejecutar la fase

Requiere la fase 0 terminada.

```bash
python -m src.fase1.run
```

| Archivo | Contenido |
|---|---|
| `data/fase1/catalogo.jsonl` | Un documento por línea: contenido canónico, hashes, transformaciones y tipos de evidencia por líneas. |
| `data/fase1/restricciones.jsonl` | Por documento: líneas no citables, afirmaciones excluidas y conflictos. |
| `data/fase1/huecos.jsonl` | Huecos confirmados por software/versión, con sus líneas. |
| `data/fase1/llamadas.jsonl` | Cada llamada posible a la herramienta, con sus documentos y su tamaño estimado en tokens. |
| `data/fase1/ejemplos_referencia.jsonl` | Las 10 conversaciones de referencia (una por situación), validadas contra el contrato. |
| `src/fase1/contract/` | Prompt de sistema, reglas y esquemas de la conversación y del caso de evaluación. |
| `reports/fase1/estadisticas.md` | Estadísticas de la fase. |

El detalle de cada paso está en **[docs/fase1.md](docs/fase1.md)**.

## Reproducir y verificar los resultados

Todas las salidas están commiteadas en `data/` y `reports/`. Para comprobar que obtienes exactamente los mismos resultados:

```bash
python -m src.fase0.run
python -m src.fase0.finalize
python -m src.fase1.run
git status --short data/ reports/
```

Si `git status` no muestra nada, tus archivos son idénticos byte a byte a los entregados. Esto incluye las decisiones de la revisión humana, que están en el CSV.

- **Los pasos con código son deterministas:** inventario, secciones, chequeos, validaciones, etiqueta final y toda la fase 1.
- **Los pasos con LLM no lo son,** pero se reproducen exactamente porque sus respuestas están guardadas en `data/cache/`.

Ver [docs/fase0.md, sección 6](docs/fase0.md#6-reproducibilidad) y [docs/fase1.md](docs/fase1.md).

Para ejecutar los tests:

```bash
python -m pytest src/tests
```

## Decisiones principales

- **La unidad de auditoría es el software/versión.** La consistencia se evalúa solo dentro de una misma versión: que v1 y v2 digan cosas distintas no es un defecto.
- **Cada versión se audita completa en una sola llamada.** El corpus es pequeño (~320 KB) y la versión más grande ronda los 12k tokens, así que el LLM puede ver todos sus archivos a la vez y detectar contradicciones entre ellos.
- **Las secciones cubren el 100% de cada archivo.** Ninguna parte de la documentación puede quedar sin evaluar, y el código lo garantiza.
- **Los chequeos automáticos no deciden, informan.** Son pistas para los LLM, que deciden con el contexto si un problema invalida la sección.
- **Dos LLM de proveedores distintos.** A clasifica y B revisa cada clasificación. Si dan estados distintos, una persona elige el criterio de A o el de B. Si no elige, se aplica una regla fija: gana `parcial`; si no hay `parcial`, gana `usable`.
- **La categoría no se revisa.** Si A y B solo discrepan en la categoría, se usa la de A.

El detalle y la justificación de cada regla están en [docs/fase0.md](docs/fase0.md).
