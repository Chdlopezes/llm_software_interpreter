"""Fase 1, validación por código de conversaciones y casos de evaluación.

Dos niveles:
1. Esquema: `check_schema` implementa el subconjunto de JSON Schema que usan los
   archivos de src/fase1/contract/ (type, enum, required, properties,
   additionalProperties, items, minItems, minLength, pattern). Así no hace falta
   añadir una dependencia.
2. Contrato (`check_example`): la acción corresponde a la situación, la salida de la
   herramienta es la real, los documentos son los esperados y cada cita apunta a un
   documento entregado, con un rango válido y sin líneas no citables (salvo las
   líneas en conflicto en la situación «contradiccion»).

No comprueba que una cita RESPALDE la afirmación: eso es la evaluación semántica de
la fase 4.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.fase1.tool import TOOL_NAME, TOOLS, obtener_documentacion, tool_message

CONTRACT = Path(__file__).parent / "contract"
CITE_RE = re.compile(r"\[([^\[\]\s]+?):L(\d+)-L(\d+)\]")
NO_CALL_SITUATIONS = {"falta_software"}
NO_CITE_SITUATIONS = {"falta_software", "sin_documentos", "sin_evidencia"}

_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}


def load_schema(name: str) -> dict:
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def check_schema(value, schema: dict, path: str = "$") -> list[str]:
    errors = []
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        ok = any(isinstance(value, _TYPES[t]) and not (t == "integer" and isinstance(value, bool)) for t in types)
        if not ok:
            return [f"{path}: se esperaba {'/'.join(types)}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} no está en {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: texto vacío")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: no cumple el patrón {schema['pattern']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: menos de {schema['minItems']} elementos")
        for i, item in enumerate(value):
            if "items" in schema:
                errors += check_schema(item, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: falta '{key}'")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                errors += check_schema(item, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: campo no permitido '{key}'")
    return errors


def citations(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(1), int(m.group(2)), int(m.group(3))) for m in CITE_RE.finditer(text)]


def intersects(a: list[int], b: list[int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def check_example(conversation: dict, case: dict, catalog: list[dict], restrictions: list[dict]) -> list[str]:
    """Errores de contrato de una conversación de entrenamiento y su caso de evaluación."""
    errors = check_schema(conversation, load_schema("conversation_schema.json"), "conversacion")
    errors += check_schema(case, load_schema("eval_case_schema.json"), "caso")
    if errors:
        return errors

    msgs = conversation["messages"]
    n_hist = len(case["historial"])
    if conversation["tools"] != TOOLS:
        errors.append("las herramientas no son las del contrato")
    if msgs[0]["role"] != "system" or msgs[0]["content"] != (CONTRACT / "system_prompt.md").read_text(encoding="utf-8").strip():
        errors.append("el primer mensaje no es el prompt de sistema del contrato")
    if msgs[1:1 + n_hist] != case["historial"]:
        errors.append("el historial del caso no coincide con la conversación")
    current = msgs[1 + n_hist:]
    if not current or current[0] != {"role": "user", "content": case["pregunta"]}:
        return errors + ["la pregunta del caso no es el mensaje de usuario tras el historial"]
    current = current[1:]

    # Acción: aclaración sin llamada, o llamada + salida real + respuesta.
    situation = case["situacion"]
    if situation in NO_CALL_SITUATIONS:
        if case["expected_action"] != "clarification" or case["expected_tool"] is not None:
            errors.append(f"«{situation}» espera una aclaración, sin herramienta")
        if len(current) != 1 or current[0]["role"] != "assistant" or current[0].get("tool_calls"):
            errors.append("la aclaración debe ser un único mensaje del asistente, sin llamada")
        if current and citations(current[0]["content"]):
            errors.append("la aclaración no debe citar documentos")
        return errors
    if case["expected_action"] != "tool_call" or len(current) != 3:
        return errors + ["se esperaba llamada, salida de la herramienta y respuesta"]
    call, tool, answer = current
    calls = call.get("tool_calls") or []
    if call["role"] != "assistant" or len(calls) != 1 or call["content"]:
        return errors + ["la llamada debe ser un mensaje del asistente con una sola tool_call y sin texto"]
    args = calls[0]["function"]["arguments"]
    if calls[0]["function"] != case["expected_tool"]:
        errors.append(f"la llamada {args} no es la esperada {case['expected_tool']['arguments']}")
    if tool["role"] != "tool" or tool.get("name") != TOOL_NAME:
        return errors + ["falta el mensaje de la herramienta"]
    result = obtener_documentacion(args["software"], args["version"], catalog)
    if tool["content"] != tool_message(result):
        errors.append("la salida de la herramienta no es la salida real")
    ids = [d["id"] for d in result["documentos"]]
    if ids != case["expected_document_ids"]:
        errors.append("los documentos devueltos no son los esperados")
    if (situation == "sin_documentos") != (result["status"] == "not_found"):
        errors.append(f"«{situation}» y status «{result['status']}» no son coherentes")
    if answer["role"] != "assistant" or answer.get("tool_calls"):
        errors.append("la respuesta final debe ser un mensaje del asistente sin llamada")

    # Citas: en la respuesta final, sobre documentos entregados en esta llamada.
    delivered = {d["id"]: d for d in result["documentos"]}
    restr = {r["id"]: r for r in restrictions}
    lengths = {d["id"]: d["n_lineas"] for d in catalog}
    cites = citations(answer["content"])
    if not cites and situation not in NO_CITE_SITUATIONS:
        errors.append("la respuesta no tiene citas")
    for doc, a, b in cites:
        if doc not in delivered:
            errors.append(f"cita a un documento no entregado: {doc}")
            continue
        if not 1 <= a <= b <= lengths[doc]:
            errors.append(f"rango fuera del documento: {doc}:L{a}-L{b}")
            continue
        conflict_lines = [c["lineas"] for c in restr[doc]["conflictos"] if c["lineas"]]
        for nc in restr[doc]["no_citables"]:
            if not intersects([a, b], nc):
                continue
            allowed = situation == "contradiccion" and all(
                any(c[0] <= n <= c[1] for c in conflict_lines)
                for n in range(max(a, nc[0]), min(b, nc[1]) + 1))
            if not allowed:
                errors.append(f"cita líneas no citables: {doc}:L{a}-L{b} (no citables {nc[0]}-{nc[1]})")
    for p in case["procedencia"]:
        if p["documento"] not in delivered:
            errors.append(f"procedencia en un documento no entregado: {p['documento']}")
        elif p["sha256_canonico"] != next(d for d in catalog if d["id"] == p["documento"])["sha256_canonico"]:
            errors.append(f"hash de procedencia distinto: {p['documento']}")
    return errors
