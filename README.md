# Datos de entrenamiento a partir de documentación técnica

Flujo local que convierte la documentación cruda de `docs_raw/` en datasets de entrenamiento y evaluación para un modelo abierto pequeño. Cada fila de salida se puede rastrear hasta su archivo y sus líneas de origen.

## Estado

| Fase | Qué hace | Estado |
|---|---|---|
| Preparación | Entorno, configuración de los LLM y verificación | Hecha |
| 0 — Auditoría | Etiqueta toda la documentación: qué es usable, qué no y por qué, y qué falta | Paso 1 de 6 hecho |

Las fases siguientes se añadirán a esta tabla a medida que se implementen.

## Estructura del repositorio

```
docs_raw/          Documentación cruda de entrada (no se modifica)
src/               Todo el código del flujo
  llm.py             Capa única para llamar a los LLM (CLI o API)
  check_setup.py     Verificación del entorno
  fase0/             Fase 0: auditoría de la documentación
  tests/             Tests deterministas
data/              Todas las salidas generadas por el flujo (se suben al repositorio)
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

  El paso 1 de la fase 0 no usa ningún LLM: para ejecutarlo solo necesitas Python.

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

Etiqueta toda la documentación de `docs_raw/`. Cada sección de cada software/versión queda evaluada (usable, parcial o no usable) y categorizada, y se registra lo que falta por documentar. Las fases siguientes solo generan datos a partir de lo que esta fase marca como usable.

El diseño completo, la justificación de cada regla y el significado de cada campo de salida están en **[docs/fase0.md](docs/fase0.md)**.

### Paso 1 — Inventario, secciones y chequeos automáticos

```bash
python -m src.fase0.extract
```

Qué hace (sin usar ningún LLM):

1. **Inventaría** todos los archivos de `docs_raw/`, con su software, versión y hash SHA-256.
2. **Parte cada archivo en secciones**, con su archivo y su rango de líneas:
   - Markdown: por títulos `#` y `##`.
   - OpenAPI: una sección por operación.
   - JSON: el archivo completo.
3. **Corre chequeos automáticos:** enlaces y anclas rotas, recursos ausentes, secciones vacías, entidades HTML sin decodificar en el código, archivos que no se pueden interpretar y metadatos de versión incoherentes.
4. **Detecta versiones idénticas,** que heredarán las etiquetas en lugar de auditarse dos veces.
5. **Verifica la cobertura.** Las secciones de cada archivo deben cubrir el 100% de sus líneas y reconstruirlo exactamente; si no, el proceso termina con error.

Salida esperada:

```
Unidades software/versión: 16
Archivos inventariados:    107 (todos los de docs_raw/)
Secciones:                 360 (cubren el 100% de las líneas)
Idéntica:                  catalog-portfolio-api/latest = catalog-portfolio-api/0.0.1-test-bench-v2a (heredará etiquetas)
Chequeos deterministas:
    29  recurso_ausente
    20  ancla_rota
    14  enlace_roto
     9  metadatos_latest_resuelve_a
     7  seccion_vacia
     5  entidad_html_en_codigo
     2  enlace_correo_sin_mailto
     1  enlace_mal_formado
Salidas en data/fase0/
```

Qué significa cada tipo de chequeo, y qué no permite concluir, está en [docs/fase0.md, sección 3.3](docs/fase0.md#33-chequeos-automáticos).

Archivos que escribe en `data/fase0/`:

| Archivo | Contenido |
|---|---|
| `units.jsonl` | Un registro por software/versión, con su huella de contenido y la versión idéntica de la que hereda etiquetas, si existe. |
| `inventory.jsonl` | Un registro por archivo: hash, tipo, número de secciones y resultado de los chequeos. |
| `sections.jsonl` | Un registro por sección: `section_id`, archivo, `line_start`, `line_end` y texto original. |

## Reproducir y verificar los resultados

Las salidas de cada paso están commiteadas en `data/`. Para comprobar que tu ejecución da exactamente los mismos resultados, corre el paso y compara con lo commiteado:

```bash
python -m src.fase0.extract
git status --short data/
```

Si `git status` no muestra nada, tus archivos son idénticos byte a byte a los entregados. El paso 1 es determinista: no usa LLM ni red, y recorre los archivos siempre en el mismo orden.

Los pasos que usan LLM no son deterministas: el mismo prompt puede dar respuestas distintas. Esos pasos se reproducen con un caché de respuestas que también se sube a `data/`. Ver [docs/fase0.md, sección 4](docs/fase0.md#4-reproducibilidad).

Para ejecutar los tests:

```bash
python -m pytest src/tests
```

Comprueban cada regla de partición y los chequeos principales con casos escritos a mano. Además verifican, sobre todo el corpus, que cada sección coincide exactamente con sus líneas de origen.

## Decisiones principales

- **La unidad de auditoría es el software/versión.** La consistencia se evalúa solo dentro de una misma versión: que v1 y v2 digan cosas distintas no es un defecto.
- **Cada versión se audita completa en una sola llamada.** El corpus es pequeño (~320 KB) y la versión más grande ronda los 12k tokens, así que el LLM puede ver todos sus archivos a la vez y detectar contradicciones entre ellos.
- **Las secciones cubren el 100% de cada archivo.** Ninguna parte de la documentación puede quedar sin evaluar, y el código lo garantiza.
- **Los chequeos automáticos no deciden, informan.** Son pistas para los LLM, que deciden con el contexto si un problema invalida la sección.
- **Dos LLM de proveedores distintos.** A etiqueta y B valida cada etiqueta; lo que B no confirma pasa a revisión humana.

El detalle y la justificación de cada regla están en [docs/fase0.md](docs/fase0.md).
