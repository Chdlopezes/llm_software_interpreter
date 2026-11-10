"""Fase 4, render con la plantilla de chat del modelo a ajustar y medición en tokens.

El modelo elegido es Qwen3.5-4B. Solo se descarga su tokenizer (con la plantilla de chat), no los
pesos, y en una revisión fija para que las cifras se puedan reproducir. Los modelos pequeños de la
familia Qwen3.5 comparten tokenizer.

Dos adaptaciones, solo al renderizar (los datos canónicos no cambian):
- Sin modo de razonamiento (`enable_thinking=False`): las respuestas de referencia no tienen
  razonamiento, y la plantilla escribe un bloque <think> vacío antes de cada turno del asistente
  posterior a la última pregunta.
- `version: null` se escribe como el texto `null`. La plantilla convierte cada argumento con
  `|string`, y None se convertiría en «None», que el parser de llamadas de Qwen (qwen3_coder)
  no interpreta como nulo.

Qué se entrena: los mensajes del asistente posteriores a la última pregunta del usuario (la
llamada a la herramienta y la respuesta). El historial previo es contexto: la plantilla lo
renderiza distinto (sin bloque <think>) y no se supervisa. Para cada conversación se comprueba
que la plantilla sea estable por prefijo en esos mensajes; si no, la máscara de pérdida no
coincidiría con lo que el modelo genera.
"""

from __future__ import annotations

import copy
from functools import lru_cache

from src.fase1.tool import MAX_CONTEXT_TOKENS

MODELO = "Qwen/Qwen3.5-4B"
REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
MAX_TOKENS = MAX_CONTEXT_TOKENS          # presupuesto de la fase 1: 32.768


@lru_cache(maxsize=1)
def load_tokenizer():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(MODELO, revision=REVISION)


def para_qwen(messages: list[dict]) -> list[dict]:
    out = copy.deepcopy(messages)
    for m in out:
        for c in m.get("tool_calls") or []:
            c["function"]["arguments"] = {k: ("null" if v is None else v)
                                          for k, v in c["function"]["arguments"].items()}
    return out


def render(tok, messages: list[dict], tools: list[dict], generation_prompt: bool = False) -> str:
    return tok.apply_chat_template(para_qwen(messages), tools=tools, tokenize=False, enable_thinking=False,
                                   add_generation_prompt=generation_prompt)


def tramos_supervisados(tok, messages: list[dict], tools: list[dict]) -> tuple[str, list[tuple[int, int]], list[str]]:
    """Texto completo y tramos (en caracteres) de los mensajes del asistente que se entrenan."""
    full = render(tok, messages, tools)
    last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
    spans, errors = [], []
    for k in range(last_user + 1, len(messages)):
        if messages[k]["role"] != "assistant":
            continue
        prefix = render(tok, messages[:k], tools, generation_prompt=True)
        upto = render(tok, messages[:k + 1], tools)
        if not (full.startswith(prefix) and full.startswith(upto) and upto.startswith(prefix)):
            errors.append(f"la plantilla no es estable por prefijo en el mensaje {k}")
            continue
        spans.append((len(prefix), len(upto)))
    if not spans and not errors:
        errors.append("no hay mensajes del asistente que supervisar")
    return full, spans, errors


def medir(tok, conversation: dict) -> dict:
    """Tokens totales, tokens supervisados y errores de render de una conversación."""
    full, spans, errors = tramos_supervisados(tok, conversation["messages"], conversation["tools"])
    enc = tok(full, add_special_tokens=False, return_offsets_mapping=True)
    supervised = sum(1 for a, _ in enc["offset_mapping"] if any(s <= a < e for s, e in spans))
    n = len(enc["input_ids"])
    if n > MAX_TOKENS:
        errors.append(f"{n} tokens, más que el presupuesto de {MAX_TOKENS}")
    return {"tokens": n, "tokens_supervisados": supervised, "errores": errors}
