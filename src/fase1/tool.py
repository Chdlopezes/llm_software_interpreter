"""Fase 1, herramienta obtener_documentacion.

Filtra el catálogo por software y versión y devuelve los documentos COMPLETOS.
No busca por similitud, no ordena por relevancia y no selecciona secciones: dos
preguntas sobre el mismo software y versión reciben siempre los mismos documentos.

    version=None  → toda la documentación del software (todas sus versiones)
    version="x"   → solo los documentos de esa versión (comparación literal)

Estados: "ok" (hay documentos), "not_found" (el filtro no coincide con nada) y
"error" (no se pudo leer el catálogo). Un error no es lo mismo que la ausencia de
documentación.

También escribe data/fase1/llamadas.jsonl con cada llamada posible, los documentos
que devuelve y su tamaño estimado frente a la ventana de contexto.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from src.fase0.label import read_jsonl, write_jsonl
from src.fase1.catalog import CATALOG_PATH, FASE1

CALLS_PATH = FASE1 / "llamadas.jsonl"
TOOL_NAME = "obtener_documentacion"

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": ("Devuelve documentos completos por software y versión. "
                        "version=null incluye todas las versiones disponibles del software."),
        "parameters": {
            "type": "object",
            "properties": {
                "software": {"type": "string", "description": "Identificador del software en el catálogo."},
                "version": {"type": ["string", "null"], "description": "Versión exacta, o null para todas."},
            },
            "required": ["software", "version"],
            "additionalProperties": False,
        },
    },
}
TOOLS = [TOOL_SCHEMA]

# Ventana de contexto. Se fija al elegir el modelo; la medición exacta con su
# tokenizador se hace al exportar. Aquí se estima con CHARS_PER_TOKEN.
MAX_CONTEXT_TOKENS = 32_768
RESERVED_TOKENS = 2_048          # sistema, pregunta, llamada y respuesta
CHARS_PER_TOKEN = 3.5            # estimación conservadora para texto técnico en inglés

PUBLIC_FIELDS = ("id", "software", "version", "titulo", "contenido")


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    return read_jsonl(path)


def seleccionar_documentos(catalogo: list[dict], software: str, version: str | None) -> list[dict]:
    return sorted((d for d in catalogo
                   if d["software"] == software and (version is None or d["version"] == version)),
                  key=lambda d: d["id"])


def obtener_documentacion(software: str, version: str | None, catalogo: list[dict] | None = None) -> dict:
    try:
        catalogo = load_catalog() if catalogo is None else catalogo
    except (OSError, ValueError):
        return {"status": "error", "corpus_version": None, "documentos": []}
    docs = seleccionar_documentos(catalogo, software, version)
    return {
        "status": "ok" if docs else "not_found",
        "corpus_version": catalogo[0]["corpus_version"] if catalogo else None,
        "documentos": [{k: d[k] for k in PUBLIC_FIELDS} for d in docs],
    }


def tool_message(result: dict) -> str:
    """Contenido del mensaje `tool`, tal como lo verá el modelo."""
    return json.dumps(result, ensure_ascii=False)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def possible_calls(catalogo: list[dict]) -> list[dict]:
    rows = []
    for software in sorted({d["software"] for d in catalogo}):
        versions = sorted({d["version"] for d in catalogo if d["software"] == software})
        for version in [None] + versions:
            result = obtener_documentacion(software, version, catalogo)
            tokens = estimate_tokens(tool_message(result))
            rows.append({"software": software, "version": version,
                         "ids": [d["id"] for d in result["documentos"]],
                         "caracteres": len(tool_message(result)), "tokens_estimados": tokens,
                         "cabe_en_contexto": tokens + RESERVED_TOKENS <= MAX_CONTEXT_TOKENS})
    return rows


def main() -> int:
    calls = possible_calls(load_catalog())
    write_jsonl(CALLS_PATH, calls)
    big = max(calls, key=lambda c: c["tokens_estimados"])
    print(f"Llamadas posibles: {len(calls)}; la mayor es {big['software']} version={big['version']} "
          f"(~{big['tokens_estimados']:,} tokens); no caben: {sum(not c['cabe_en_contexto'] for c in calls)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
