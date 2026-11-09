"""Fase 0, pasos 5 y 6: cola de revisión humana, etiqueta final y verificación de cobertura.

No llama a ningún LLM y es determinista. Tiene dos partes:

1. prepare_review() — la ejecuta src.fase0.run al final. Escribe
   data/fase0/human_review.csv con las secciones en las que A y B dan estados
   distintos (o en las que alguna respuesta no pasó la validación). Las copias
   heredadas de versiones idénticas no se incluyen: toman la decisión de su original.

2. main() — se ejecuta después de rellenar el CSV:
       python -m src.fase0.finalize
   Lee la columna `decision` (A o B) de cada fila. Las filas vacías se completan
   por defecto: gana el modelo que eligió `parcial`; si ninguno lo eligió, el que
   eligió `usable`. Después calcula la etiqueta final de cada sección, verifica la
   cobertura (paso 6) y escribe:
       data/fase0/section_status.jsonl  etiqueta final de cada sección
       data/fase0/gaps.jsonl            huecos de documentación
       reports/fase0/estadisticas.md    estadísticas principales de la fase 0

Reglas de la etiqueta final:
- A y B dan el mismo estado (y sus respuestas son válidas) -> estado y categoría de A.
- Estados distintos, o alguna respuesta inválida           -> estado y categoría del modelo
                                                             elegido en el CSV, o del elegido
                                                             por defecto.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter

from src.fase0.label import CATEGORIAS, ESTADOS, FASE0, ROOT, read_jsonl, write_jsonl

REVIEW_PATH = FASE0 / "human_review.csv"
CSV_COLUMNS = [
    "section_id", "software", "version", "archivo", "lineas", "titulo", "contenido",
    "estado_a", "categoria_a", "justificacion_a", "problemas_a",
    "estado_b", "categoria_b", "explicacion_b", "cita_b",
    "motivo_revision",
    "decision",
]
DECISIONES = ["A", "B"]


# ---------------------------------------------------------------------------
# Reglas
# ---------------------------------------------------------------------------

def review_reason(a: dict | None, b: dict | None) -> str | None:
    """Motivo por el que una sección necesita decisión, o None si A y B coinciden en el
    estado. Una diferencia solo de categoría no cuenta: se usa la categoría de A."""
    if a is None or not a["valida"]:
        return "la respuesta de A no pasó la validación"
    if b is None or not b["valida"]:
        return "la respuesta de B no pasó la validación"
    if b["estado"] != a["estado"]:
        return f"estados distintos: A={a['estado']} / B={b['estado']}"
    return None


def default_decision(a: dict | None, b: dict | None) -> str:
    """Decisión por defecto para una fila que la persona dejó vacía: gana el modelo que
    eligió `parcial`; si ninguno, el que eligió `usable`; si no, A. Si solo uno de los
    dos clasificó la sección, ese."""
    ea, eb = (a or {}).get("estado"), (b or {}).get("estado")
    if ea is None or eb is None:
        return "A" if ea is not None else "B"
    for preferred in ("parcial", "usable"):
        if ea == preferred:
            return "A"
        if eb == preferred:
            return "B"
    return "A"


def claims_of_a(a: dict | None) -> list[str]:
    return [p["cita"] for p in (a or {}).get("problemas", [])]


def claims_of_b(b: dict | None) -> list[str]:
    return [b["cita"]] if b and b.get("estado") == "parcial" and b.get("cita") else []


def final_label(section: dict, a: dict | None, b: dict | None,
                human: str | None, inherited_from: str | None = None) -> dict:
    """Etiqueta final de una sección. `human` es la decisión del CSV ('A', 'B' o None)."""
    reason = review_reason(a, b)
    if reason is None:
        estado, categoria, origen, decision = a["estado"], a["categoria"], "acuerdo_a_b", None
        # Si los dos la ven parcial, se excluyen las afirmaciones que cita cada uno.
        claims = claims_of_a(a) + [c for c in claims_of_b(b) if c not in claims_of_a(a)]
    else:
        if human:
            decision, origen = human, "decision_humana"
        else:
            decision, origen = default_decision(a, b), "decision_por_defecto"
        chosen = a if decision == "A" else b
        if not chosen or not chosen.get("estado"):
            raise SystemExit(f"[error] {section['section_id']}: se eligió {decision}, pero ese modelo no "
                             f"clasificó la sección. Elige el otro en {REVIEW_PATH.relative_to(ROOT)}.")
        estado, categoria = chosen["estado"], chosen["categoria"]
        claims = claims_of_a(a) if decision == "A" else claims_of_b(b)
    return {
        "section_id": section["section_id"], "unit": section["unit"],
        "software": section["software"], "version": section["version"],
        "file": section["file"], "line_start": section["line_start"], "line_end": section["line_end"],
        "estado": estado, "categoria": categoria, "origen": origen,
        "motivo_revision": reason, "decision": decision,
        "afirmaciones_excluidas": claims if estado == "parcial" else [],
        "a": None if a is None else {k: a[k] for k in ("estado", "categoria", "problemas", "justificacion", "valida")},
        "b": None if b is None else {k: b[k] for k in ("de_acuerdo", "estado", "categoria", "cita", "explicacion", "valida")},
        "heredada_de": inherited_from,
    }


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

def load_inputs() -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    needed = [FASE0 / n for n in ("sections.jsonl", "labels_a.jsonl", "labels_b.jsonl")]
    missing = [p for p in needed if not p.exists()]
    if missing:
        raise SystemExit("[error] Faltan " + ", ".join(str(p.relative_to(ROOT)) for p in missing)
                         + ". Ejecuta antes: python -m src.fase0.run")
    sections = read_jsonl(needed[0])
    labels_a = {l["section_id"]: l for l in read_jsonl(needed[1])}
    labels_b = {l["section_id"]: l for l in read_jsonl(needed[2])}
    return sections, labels_a, labels_b


def read_decisions(path=REVIEW_PATH) -> dict[str, str]:
    """Lee la columna `decision` ('A', 'B' o vacía). Falla si hay valores no permitidos."""
    if not path.exists():
        return {}
    decisions, problems = {}, []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            value = (row.get("decision") or "").strip().upper()
            if value and value not in DECISIONES:
                problems.append(f"fila {n} ({row['section_id']}): decision '{value}' debe ser A o B")
            elif value:
                decisions[row["section_id"]] = value
    if problems:
        raise SystemExit(f"[error] Valores no válidos en {path.relative_to(ROOT)}:\n  " + "\n  ".join(problems))
    return decisions


def csv_row(section: dict, a: dict | None, b: dict | None, reason: str, decision: str | None) -> dict:
    a, b = a or {}, b or {}
    problemas = "; ".join(f"{p['motivo']}: «{p['cita']}»" for p in a.get("problemas", []))
    return {
        "section_id": section["section_id"], "software": section["software"],
        "version": section["version"], "archivo": section["file"],
        "lineas": f"{section['line_start']}-{section['line_end']}", "titulo": section["title"],
        "contenido": section["text"],
        "estado_a": a.get("estado") or "", "categoria_a": a.get("categoria") or "",
        "justificacion_a": a.get("justificacion") or "", "problemas_a": problemas,
        "estado_b": b.get("estado") or "", "categoria_b": b.get("categoria") or "",
        "explicacion_b": b.get("explicacion") or "", "cita_b": b.get("cita") or "",
        "motivo_revision": reason, "decision": decision or "",
    }


# ---------------------------------------------------------------------------
# Parte 1: cola de revisión (la llama src.fase0.run)
# ---------------------------------------------------------------------------

def prepare_review() -> int:
    """Escribe human_review.csv. Conserva las decisiones que ya hubiera en el archivo.
    Devuelve el número de filas."""
    sections, labels_a, labels_b = load_inputs()
    decisions = read_decisions()
    rows = []
    for s in sections:
        sid = s["section_id"]
        a, b = labels_a.get(sid), labels_b.get(sid)
        reason = review_reason(a, b)
        # Las copias de versiones idénticas no se revisan: toman la decisión de su original.
        if reason is not None and not (a or {}).get("heredada_de"):
            rows.append(csv_row(s, a, b, reason, decisions.get(sid)))
    with REVIEW_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Parte 2: etiqueta final, cobertura y reporte
# ---------------------------------------------------------------------------

def final_gaps(gaps_a: list[dict], gaps_b: list[dict]) -> list[dict]:
    verdicts = {(g["unit"], g["hueco"]): g for g in gaps_b}
    out = []
    for g in gaps_a:
        v = verdicts.get((g["unit"], g["hueco"]), {})
        out.append({
            "unit": g["unit"], "section_id": g["section_id"], "descripcion": g["descripcion"],
            "evidencia": g["evidencia"],
            "confirmado": bool(g["valido"] and v.get("valido") and v.get("de_acuerdo")),
            "explicacion_b": v.get("explicacion", ""),
        })
    return out


def verify_coverage(sections: list[dict], statuses: list[dict]) -> list[str]:
    """Paso 6: cada sección tiene exactamente una etiqueta final con estado y categoría válidos."""
    errors = []
    expected = Counter(s["section_id"] for s in sections)
    got = Counter(s["section_id"] for s in statuses)
    missing = sorted(set(expected) - set(got))
    extra = sorted(set(got) - set(expected))
    dup = sorted(sid for sid, n in got.items() if n > 1)
    if missing:
        errors.append(f"{len(missing)} secciones sin etiqueta final: {missing[:5]}")
    if extra:
        errors.append(f"{len(extra)} etiquetas de secciones inexistentes: {extra[:5]}")
    if dup:
        errors.append(f"{len(dup)} secciones con más de una etiqueta: {dup[:5]}")
    for s in statuses:
        if s["estado"] not in ESTADOS:
            errors.append(f"{s['section_id']}: estado no válido {s['estado']!r}")
        if s["categoria"] not in CATEGORIAS:
            errors.append(f"{s['section_id']}: categoría no válida {s['categoria']!r}")
    return errors


def main() -> int:
    from src.fase0.report import write_report

    sections, labels_a, labels_b = load_inputs()
    if not REVIEW_PATH.exists():
        print(f"[error] Falta {REVIEW_PATH.relative_to(ROOT)}. Ejecuta antes: python -m src.fase0.run")
        return 1
    decisions = read_decisions()

    statuses = []
    for s in sections:
        sid = s["section_id"]
        a = labels_a.get(sid)
        source = (a or {}).get("heredada_de")
        # Una copia heredada usa la decisión de su sección original.
        human = decisions.get(source) if source else decisions.get(sid)
        statuses.append(final_label(s, a, labels_b.get(sid), human, source))

    errors = verify_coverage(sections, statuses)
    if errors:
        print("[error] La verificación de cobertura falló:")
        for e in errors:
            print(f"  - {e}")
        return 1

    gaps = final_gaps(read_jsonl(FASE0 / "gaps_a.jsonl"), read_jsonl(FASE0 / "gaps_b.jsonl"))
    write_jsonl(FASE0 / "section_status.jsonl", statuses)
    write_jsonl(FASE0 / "gaps.jsonl", gaps)
    report_path = write_report(sections, statuses, gaps)

    origen = Counter(s["origen"] for s in statuses)
    totals = Counter(s["estado"] for s in statuses)
    print(f"Cobertura verificada: {len(statuses)} de {len(sections)} secciones con etiqueta final.")
    print("Estado final: " + ", ".join(f"{e}={totals[e]}" for e in ESTADOS))
    print(f"Origen: A y B de acuerdo={origen['acuerdo_a_b']}, decisión humana={origen['decision_humana']}, "
          f"decisión por defecto={origen['decision_por_defecto']}")
    if origen["decision_por_defecto"]:
        print("  Las filas sin decisión en el CSV se completaron por defecto: gana el modelo que "
              "eligió 'parcial'; si ninguno, el que eligió 'usable'.")
    print(f"Huecos confirmados: {sum(g['confirmado'] for g in gaps)} de {len(gaps)}")
    print(f"Escrito data/fase0/section_status.jsonl, data/fase0/gaps.jsonl y {report_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
