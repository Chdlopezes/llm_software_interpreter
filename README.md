# Datos de entrenamiento a partir de documentación técnica

Flujo local que convierte la documentación cruda de `docs_raw/` en datasets de entrenamiento y evaluación para un modelo abierto pequeño. Cada fila de salida se puede rastrear hasta su archivo y sus líneas de origen.

> Estado: **preparación del entorno.** Las fases del flujo se irán añadiendo a este README a medida que se implementen.

## Estructura del repositorio

```
docs_raw/          Documentación cruda de entrada (no se modifica)
src/               Todo el código del flujo
data/              Todas las salidas generadas por el flujo
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

El flujo llama a estas CLIs sin herramientas y en una carpeta temporal vacía: no leen ni modifican tus archivos. Las llamadas cuentan contra los límites de tu suscripción, no contra saldo de API.

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
