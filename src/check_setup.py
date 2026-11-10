"""Verifica que el entorno está listo para correr el flujo.

Uso, desde la raíz del repositorio:
    python -m src.check_setup          # comprobaciones locales, sin llamar a ningún LLM
    python -m src.check_setup --ping   # además, una llamada mínima real a cada LLM
"""

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 10)

# nombre en pip -> nombre del módulo a importar
PACKAGES = {
    "anthropic": "anthropic",
    "openai": "openai",
    "python-dotenv": "dotenv",
    "pyyaml": "yaml",
    "pytest": "pytest",
}

def check_backend(tarea: str, errors: list, warnings: list):
    """Comprueba lo que necesita el backend configurado para una tarea."""
    from src.llm import TAREAS, LLMError, get_config

    try:
        cfg = get_config(tarea)
    except LLMError as e:
        errors.append(str(e))
        return None

    name = f"LLM {tarea} ({TAREAS[tarea]})"
    if cfg.backend == "anthropic_api":
        if not os.getenv("ANTHROPIC_API_KEY", "").strip():
            errors.append(f"{name} usa anthropic_api pero ANTHROPIC_API_KEY está vacía en .env.")
            return None
    elif cfg.backend == "openai_api":
        if not os.getenv("OPENAI_API_KEY", "").strip():
            errors.append(f"{name} usa openai_api pero OPENAI_API_KEY está vacía en .env.")
            return None
    elif cfg.backend == "claude_code":
        if shutil.which("claude") is None:
            errors.append(f"{name} usa claude_code pero el comando `claude` no está en el PATH.")
            return None
        status = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True)
        try:
            logged_in = json.loads(status.stdout).get("loggedIn", False)
        except json.JSONDecodeError:
            logged_in = status.returncode == 0
        if not logged_in:
            errors.append(f"{name} usa claude_code pero no hay sesión iniciada: ejecuta `claude` e inicia sesión.")
            return None
    elif cfg.backend == "codex":
        if shutil.which("codex") is None:
            errors.append(f"{name} usa codex pero el comando `codex` no está en el PATH.")
            return None
        status = subprocess.run(["codex", "login", "status"], capture_output=True, text=True)
        if status.returncode != 0:
            errors.append(f"{name} usa codex pero no hay sesión iniciada: ejecuta `codex login`.")
            return None

    print(f"[ok] {name}: {cfg.label}")
    return cfg


def ping(cfg) -> bool:
    """Llamada mínima con salida estructurada para confirmar que el backend responde."""
    from src.llm import LLMError, generate

    schema = {
        "type": "object",
        "properties": {"respuesta": {"type": "string"}},
        "required": ["respuesta"],
        "additionalProperties": False,
    }
    start = time.monotonic()
    try:
        out = generate(cfg, "Responde de forma breve.", "Devuelve respuesta = \"ok\".", schema)
    except (LLMError, Exception) as e:  # noqa: BLE001 - queremos reportar cualquier fallo
        print(f"[error] ping LLM {cfg.tarea} ({cfg.label}): {e}")
        return False
    print(f"[ok] ping LLM {cfg.tarea} ({cfg.label}) -> {out} en {time.monotonic() - start:.1f}s")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ping", action="store_true", help="hace una llamada mínima real a cada LLM")
    args = parser.parse_args()

    errors = []
    warnings = []

    # 1. Python
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info < MIN_PYTHON:
        errors.append(f"Python {version}: se necesita {MIN_PYTHON[0]}.{MIN_PYTHON[1]} o superior.")
    else:
        print(f"[ok] Python {version}")

    # 2. Dependencias
    missing = False
    for pip_name, module in PACKAGES.items():
        try:
            importlib.import_module(module)
            print(f"[ok] {pip_name} instalado")
        except ImportError:
            missing = True
            errors.append(f"Falta {pip_name}: ejecuta `pip install -r requirements.txt`.")

    # 3. .env y backend de cada tarea
    configs = []
    if not (ROOT / ".env").exists():
        errors.append("No existe .env: ejecuta `cp .env.example .env` y complétalo.")
    elif not missing:
        from src.llm import TAREAS
        for tarea in TAREAS:
            cfg = check_backend(tarea, errors, warnings)
            if cfg:
                configs.append(cfg)

    # 4. Carpetas
    docs_raw = ROOT / "docs_raw"
    if not docs_raw.is_dir():
        errors.append("No se encuentra la carpeta docs_raw/ en la raíz del repositorio.")
    else:
        n_files = sum(1 for p in docs_raw.rglob("*") if p.is_file() and p.name != ".DS_Store")
        print(f"[ok] docs_raw/ encontrada ({n_files} archivos)")

    (ROOT / "data").mkdir(exist_ok=True)
    print("[ok] data/ disponible para las salidas")

    # 5. Llamada real opcional
    if args.ping and not errors:
        for cfg in configs:
            if not ping(cfg):
                errors.append(f"El LLM {cfg.tarea} no respondió correctamente (ver arriba).")

    for w in warnings:
        print(f"[aviso] {w}")
    for e in errors:
        print(f"[error] {e}")

    if errors:
        print("\nEl entorno NO está listo.")
        return 1
    print("\nEntorno listo." if args.ping else "\nEntorno listo. Para probar una llamada real: python -m src.check_setup --ping")
    return 0


if __name__ == "__main__":
    sys.exit(main())
