"""Capa única para llamar a los LLM del flujo, con cuatro backends intercambiables.

Cada tarea que usa un LLM tiene su propia configuración en .env (ver TAREAS).
Ninguna tarea toma la de otra, aunque usen el mismo modelo:

    LLM_<TAREA>_BACKEND=claude_code | anthropic_api | codex | openai_api
    LLM_<TAREA>_MODEL=      # opcional; vacío = DEFAULT_MODELS

Todos los backends reciben lo mismo (system, prompt, esquema JSON) y devuelven
un dict que cumple el esquema. Los esquemas deben ser "estrictos": todas las
propiedades en `required` y `additionalProperties: false`, porque OpenAI y
Codex lo exigen.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

BACKENDS = ("claude_code", "codex", "anthropic_api", "openai_api")

# Modelo por defecto si LLM_<ROL>_MODEL está vacío. Es el mismo por CLI y por
# API, para que cambiar de backend solo cambie la autenticación, no el modelo.
DEFAULT_MODELS = {
    "claude_code": "claude-opus-5-5",
    "anthropic_api": "claude-opus-5-5",
    "codex": "gpt-6.1-sol",
    "openai_api": "gpt-6.1-sol",
}

CLI_TIMEOUT_S = 900

# Modelos de Anthropic que admiten `fallbacks: "default"` en la API.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


# Tareas que usan un LLM. La clave forma el nombre de las variables de .env
# (LLM_CLASIFICADOR_BACKEND, ...).
TAREAS = {
    "clasificador": "fase 0: clasifica cada sección",
    "validador": "fase 0: valida cada clasificación",
    "generador": "fase 3: genera las conversaciones candidatas",
    "verificador": "fase 3: verifica cada candidato",
}


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    tarea: str
    backend: str
    model: str | None

    @property
    def label(self) -> str:
        return f"{self.backend}:{self.model or 'default'}"


def load_env() -> None:
    """Carga .env sin pisar variables ya definidas en la terminal."""
    load_dotenv(ROOT / ".env", override=False)


def get_config(tarea: str) -> LLMConfig:
    """Lee backend y modelo de una tarea de TAREAS desde el entorno."""
    if tarea not in TAREAS:
        raise LLMError(f"Tarea '{tarea}' desconocida. Usa una de: {', '.join(TAREAS)}.")
    load_env()
    var = f"LLM_{tarea.upper()}"
    backend = os.getenv(f"{var}_BACKEND", "").strip()
    if backend not in BACKENDS:
        raise LLMError(
            f"{var}_BACKEND='{backend}' no es válido. Usa uno de: {', '.join(BACKENDS)}."
        )
    model = os.getenv(f"{var}_MODEL", "").strip() or DEFAULT_MODELS[backend]
    return LLMConfig(tarea=tarea, backend=backend, model=model)


def generate(config: LLMConfig, system: str, prompt: str, schema: dict) -> dict:
    """Ejecuta una llamada y devuelve el JSON de salida ya parseado."""
    fn = {
        "claude_code": _claude_code,
        "codex": _codex,
        "anthropic_api": _anthropic_api,
        "openai_api": _openai_api,
    }[config.backend]
    return fn(config.model, system, prompt, schema)


# ---------------------------------------------------------------------------
# Backends de CLI: usan la sesión iniciada en Claude Code / Codex.
# Se ejecutan en una carpeta temporal vacía, sin herramientas, y sin las API
# keys en el entorno para que nunca cobren por API en lugar de la suscripción.
# ---------------------------------------------------------------------------

def _env_without(*keys: str) -> dict:
    env = dict(os.environ)
    for k in keys:
        env.pop(k, None)
    return env


def _run(cmd: list[str], stdin: str, cwd: str, env: dict) -> subprocess.CompletedProcess:
    if shutil.which(cmd[0]) is None:
        raise LLMError(f"No se encuentra el comando `{cmd[0]}` en el PATH.")
    try:
        return subprocess.run(
            cmd, input=stdin, cwd=cwd, env=env, capture_output=True,
            text=True, timeout=CLI_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"`{cmd[0]}` superó {CLI_TIMEOUT_S}s sin responder.") from e


def _claude_code(model, system, prompt, schema):
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--tools", "",                 # sin herramientas: solo genera texto
        "--setting-sources", "",       # ignora settings/CLAUDE.md del usuario y del proyecto
        "--no-session-persistence",
        "--system-prompt", system,
    ]
    if model:
        cmd += ["--model", model]
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run(cmd, prompt, tmp, _env_without("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(f"claude devolvió una salida no JSON (exit {proc.returncode}): "
                       f"{(proc.stderr or proc.stdout)[-500:]}") from e
    if out.get("is_error") or out.get("structured_output") is None:
        raise LLMError(f"claude falló: {out.get('subtype')} {str(out.get('result'))[:500]}")
    return out["structured_output"]


def _codex(model, system, prompt, schema):
    with tempfile.TemporaryDirectory() as tmp:
        schema_file = Path(tmp) / "schema.json"
        out_file = Path(tmp) / "out.json"
        schema_file.write_text(json.dumps(schema))
        cmd = [
            "codex", "exec",
            "--output-schema", str(schema_file),
            "-o", str(out_file),
            "--sandbox", "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "-C", tmp,
        ]
        if model:
            cmd += ["-m", model]
        cmd.append("-")  # el prompt llega por stdin
        # codex exec no tiene opción de system prompt: va como bloque inicial.
        full_prompt = f"<instrucciones>\n{system}\n</instrucciones>\n\n{prompt}"
        proc = _run(cmd, full_prompt, tmp, _env_without("OPENAI_API_KEY"))
        if proc.returncode != 0 or not out_file.exists():
            raise LLMError(f"codex falló (exit {proc.returncode}): {proc.stderr[-500:]}")
        text = out_file.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"codex devolvió una salida no JSON: {text[:500]}") from e


# ---------------------------------------------------------------------------
# Backends de API: usan ANTHROPIC_API_KEY / OPENAI_API_KEY.
# ---------------------------------------------------------------------------

def _anthropic_api(model, system, prompt, schema):
    import anthropic

    client = anthropic.Anthropic()
    kwargs = {}
    if model in FALLBACK_MODELS:
        # Si el modelo rechaza la petición por un falso positivo de seguridad,
        # el servidor la reintenta con otro modelo en la misma llamada.
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    # Streaming para no chocar con timeouts en salidas largas.
    with client.beta.messages.stream(
        model=model,
        max_tokens=64000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": schema},
        },
        **kwargs,
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason != "end_turn":
        raise LLMError(f"Anthropic API terminó con stop_reason={msg.stop_reason}.")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if text is None:
        raise LLMError("Anthropic API no devolvió texto.")
    return json.loads(text)


def _openai_api(model, system, prompt, schema):
    import openai

    client = openai.OpenAI()
    resp = client.responses.create(
        model=model,
        instructions=system,
        input=prompt,
        text={"format": {"type": "json_schema", "name": "salida", "schema": schema, "strict": True}},
    )
    if resp.status != "completed":
        raise LLMError(f"OpenAI API terminó con status={resp.status}.")
    return json.loads(resp.output_text)
