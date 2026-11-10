"""Fase 4, controles deterministas de cada candidato y detección de duplicados.

Estructura: se vuelve a aplicar el contrato de la fase 1 y se resuelve cada referencia hasta
el catálogo (hash de cada cita, salida de la herramienta idéntica a la actual).
Aislamiento: el caso y todos los documentos que recibe son de software de su conjunto.
Duplicados: dentro de un conjunto y una situación, dos casos que piden el mismo contenido. Se
conserva el primero por task_id. Reglas, calibradas revisando a mano todos los pares que salen
de una misma sección (ver docs/fase4.md):
  a) la semilla es la misma sección (o una idéntica en otra versión) y el caso pide lo mismo:
     citan las mismas líneas (Jaccard ≥ 0,5, sin contar la versión) o la respuesta es muy
     parecida (Jaccard de bigramas ≥ 0,4);
  b) la pregunta es casi igual (Jaccard de trigramas ≥ 0,5), salga de donde salga.
Que dos casos compartan sección no basta: con la misma sección se pregunta por aspectos distintos
(prod frente a stage, el flujo Feed frente al Restock), y esos casos se conservan.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from itertools import combinations

from src.fase1.tool import obtener_documentacion
from src.fase1.validate import check_example

JACCARD_LINEAS = 0.5             # regla a: mismas líneas citadas
JACCARD_RESPUESTA = 0.4          # regla a: respuesta muy parecida
JACCARD_PREGUNTA = 0.5           # regla b: casi la misma pregunta
CITA = re.compile(r"\[([^\[\]:]+):L(\d+)-L(\d+)\]")


def errores_estructura(r: dict, catalog: list[dict], restrictions: list[dict]) -> list[str]:
    conv, case = r["conversacion"], r["caso"]
    errors = check_example(conv, case, catalog, restrictions)
    by_id = {d["id"]: d for d in catalog}
    for p in case["procedencia"]:
        d = by_id.get(p["documento"])
        if d is None:
            errors.append(f"procedencia: {p['documento']} no está en el catálogo")
        elif d["sha256_canonico"] != p["sha256_canonico"]:
            errors.append(f"procedencia: el hash de {p['documento']} no coincide con el catálogo")
    args = (case["expected_tool"] or {}).get("arguments")
    tool_msgs = [m for m in conv["messages"] if m["role"] == "tool"]
    if args:
        actual = obtener_documentacion(args["software"], args["version"], catalog)
        if not tool_msgs or json.loads(tool_msgs[0]["content"]) != actual:
            errors.append("la salida de la herramienta no coincide con la que devuelve hoy el catálogo")
        if case["expected_document_ids"] != [d["id"] for d in actual["documentos"]]:
            errors.append("expected_document_ids no coincide con la salida de la herramienta")
    elif tool_msgs:
        errors.append("hay salida de la herramienta en un caso sin llamada")
    return errors


def software_del_caso(r: dict) -> str:
    args = (r["caso"]["expected_tool"] or {}).get("arguments")
    return args["software"] if args else r["semilla"]["documento"].split("/")[0]


def errores_aislamiento(r: dict, asignacion: dict[str, str]) -> list[str]:
    errors = []
    sw = software_del_caso(r)
    if asignacion.get(sw) != r["conjunto"]:
        errors.append(f"el software {sw} es de {asignacion.get(sw)}, no de {r['conjunto']}")
    for m in r["conversacion"]["messages"]:
        if m["role"] == "tool":
            for d in json.loads(m["content"])["documentos"]:
                if asignacion.get(d["software"]) != r["conjunto"]:
                    errors.append(f"el documento {d['id']} es de {asignacion.get(d['software'])}")
    return errors


def shingles(text: str, k: int = 3) -> set[tuple]:
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i:i + k]) for i in range(max(1, len(words) - k + 1))}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def huella_semilla(r: dict, sections: dict[str, dict]) -> str | None:
    """Hash del texto de la sección semilla: dos versiones con la misma sección dan la misma huella."""
    s = r["semilla"]
    if s["tipo_semilla"] != "seccion" or s.get("section_id") not in sections:
        return None
    return hashlib.sha256(sections[s["section_id"]]["text"].encode()).hexdigest()


def lineas_citadas(r: dict) -> set[tuple]:
    """Archivo (sin software ni versión) y rango de cada cita: la misma línea en dos versiones cuenta igual."""
    return {(doc.split("/", 2)[2], a, b) for doc, a, b in CITA.findall(r["caso"]["reference_answer"])}


def duplicados(rows: list[dict], sections: dict[str, dict]) -> dict[str, dict]:
    """{task_id eliminado: {"de": task_id conservado, "motivo": ...}}."""
    groups = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["task_id"]):
        groups[(r["conjunto"], r["situacion"])].append(r)
    out: dict[str, dict] = {}
    for rs in groups.values():
        q = {r["task_id"]: shingles(r["caso"]["pregunta"]) for r in rs}
        ans = {r["task_id"]: shingles(CITA.sub("", r["caso"]["reference_answer"]), 2) for r in rs}
        lines = {r["task_id"]: lineas_citadas(r) for r in rs}
        h = {r["task_id"]: huella_semilla(r, sections) for r in rs}
        for a, b in combinations(rs, 2):
            ia, ib = a["task_id"], b["task_id"]
            if ia in out or ib in out:
                continue
            jq = jaccard(q[ia], q[ib])
            jl = jaccard(lines[ia], lines[ib])
            ja = jaccard(ans[ia], ans[ib])
            if h[ia] is not None and h[ia] == h[ib] and (jl >= JACCARD_LINEAS or ja >= JACCARD_RESPUESTA):
                motivo = (f"misma sección y mismo contenido (líneas citadas {jl:.2f}, respuesta {ja:.2f})")
            elif jq >= JACCARD_PREGUNTA:
                motivo = f"pregunta casi igual (Jaccard {jq:.2f})"
            else:
                continue
            out[ib] = {"de": ia, "motivo": motivo}
    return out
