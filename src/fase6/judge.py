"""Fase 6, juez de la evaluación (LLM_JUEZ_*).

El juez recibe la pregunta, lo que hizo y recibió el modelo, la referencia con sus criterios y la
respuesta, y devuelve un juicio por criterio, por afirmación y por cita, con etiquetas de error.
La aprobación no la decide el juez: la decide `veredicto`, con una regla fija sobre su salida.
No sabe qué modelo escribió la respuesta.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.fase3.generate import render_docs

PROMPTS = Path(__file__).parent / "prompts"
ETIQUETAS = ["afirmacion_sin_respaldo", "contradiccion_con_fuente", "cita_no_respalda", "falta_cita", "omision",
             "no_responde", "abstencion_indebida", "falta_incertidumbre", "version_incorrecta",
             "conflicto_no_senalado", "llamada_incorrecta"]

JUEZ_SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {"type": "array", "items": {
            "type": "object",
            "properties": {"indice": {"type": "integer"},
                           "resultado": {"type": "string", "enum": ["cumple", "parcial", "no_cumple"]},
                           "evidencia": {"type": "string"}},
            "required": ["indice", "resultado", "evidencia"], "additionalProperties": False}},
        "afirmaciones": {"type": "array", "items": {
            "type": "object",
            "properties": {"texto": {"type": "string"}, "cita": {"type": "string"},
                           "respaldo": {"type": "string",
                                        "enum": ["respaldada", "no_respaldada", "contradicha", "sin_verificar"]},
                           "cita_respalda": {"type": "boolean"}},
            "required": ["texto", "cita", "respaldo", "cita_respalda"], "additionalProperties": False}},
        "abstencion": {"type": "string", "enum": ["correcta", "indebida", "faltante", "no_aplica"]},
        "etiquetas_error": {"type": "array", "items": {"type": "string", "enum": ETIQUETAS}},
        "incidencia_referencia": {"type": "boolean"},
        "motivo_incidencia": {"type": "string"},
        "resumen": {"type": "string"},
    },
    "required": ["checks", "afirmaciones", "abstencion", "etiquetas_error", "incidencia_referencia",
                 "motivo_incidencia", "resumen"],
    "additionalProperties": False,
}


def system_juez() -> str:
    return (PROMPTS / "juez.md").read_text(encoding="utf-8")


def describir_llamadas(llamadas: list[dict]) -> str:
    if not llamadas:
        return "ninguna (el modelo no llamó a la herramienta)"
    return "\n".join(f"- {c['name']}({json.dumps(c['arguments'], ensure_ascii=False)}) → {c['status']}"
                     for c in llamadas)


def prompt_juez(caso: dict, respuesta: str, llamadas: list[dict], documentos: list[dict], restrictions: list[dict],
                referencia: str | None = None, orden: list[int] | None = None) -> str:
    """`referencia` permite pasar otra referencia (calibración T6.7); `orden` presenta los criterios en otro
    orden (estabilidad T6.8) sin cambiar su número."""
    restr = {r["id"]: r for r in restrictions}
    checks = caso["answer_checks"]
    orden = orden or list(range(len(checks)))
    hist = "\n".join(f"{m['role']}: {m['content']}" for m in caso["historial"]) or "(vacío)"
    restricciones = "\n".join(f"- {x['tipo']}: {x.get('descripcion') or x.get('documento', '')}"
                              for x in caso["restricciones"]) or "ninguna"
    return "\n\n".join([
        "## Documentos que recibió el modelo\n" + (render_docs(documentos, restr) or "(ninguno)"),
        "## Historial\n" + hist,
        "## Pregunta\n" + caso["pregunta"],
        "## Llamadas que hizo el modelo\n" + describir_llamadas(llamadas),
        "## Restricciones del caso\n" + restricciones,
        "## Respuesta de referencia\n" + (referencia if referencia is not None else caso["reference_answer"]),
        "## Criterios (answer_checks)\n" + "\n".join(f"{i + 1}. {checks[i]}" for i in orden),
        "## Respuesta del modelo a evaluar\n" + (respuesta or "(vacía)"),
    ])


def errores_juicio(juicio: dict, caso: dict) -> list[str]:
    """Lo que el código comprueba de la salida del juez antes de usarla."""
    esperados = list(range(1, len(caso["answer_checks"]) + 1))
    if sorted(c["indice"] for c in juicio["checks"]) != esperados:
        return [f"el juez devolvió los criterios {sorted(c['indice'] for c in juicio['checks'])} en lugar de {esperados}"]
    return []


def veredicto(juicio: dict) -> dict:
    """Regla fija sobre la salida del juez. estado ∈ aprueba | falla | incidencia_referencia."""
    motivos = []
    if any(c["resultado"] != "cumple" for c in juicio["checks"]):
        motivos.append("criterios no cumplidos: " + ", ".join(str(c["indice"]) for c in juicio["checks"]
                                                               if c["resultado"] != "cumple"))
    tecnicas = [a for a in juicio["afirmaciones"] if a["respaldo"] != "sin_verificar"]
    if any(a["respaldo"] in ("no_respaldada", "contradicha") for a in tecnicas):
        motivos.append("afirmaciones sin respaldo o contradichas")
    if any(a["respaldo"] == "respaldada" and not a["cita_respalda"] for a in tecnicas):
        motivos.append("afirmaciones sin una cita que las respalde")
    if juicio["abstencion"] in ("indebida", "faltante"):
        motivos.append(f"abstención {juicio['abstencion']}")
    if juicio["incidencia_referencia"]:
        # La referencia contradice la fuente: no se penaliza al modelo; el caso va a revisión humana.
        return {"estado": "incidencia_referencia", "motivos": motivos}
    return {"estado": "falla" if motivos else "aprueba", "motivos": motivos}
