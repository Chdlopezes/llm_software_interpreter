"""Estadísticas principales de la fase 0, en reports/fase0/estadisticas.md.

Lo genera src.fase0.finalize al terminar. Es determinista (no incluye fechas), así
que se puede comparar con la versión entregada con `git status`.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from src.fase0.label import CATEGORIAS, ESTADOS, FASE0, MOTIVOS, ROOT, read_jsonl

REPORT_PATH = ROOT / "reports" / "fase0" / "estadisticas.md"


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "—"


def table(header: list[str], rows: list[list], align_right_from: int = 1) -> list[str]:
    sep = ["---" if i < align_right_from else "---:" for i in range(len(header))]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def write_report(sections: list[dict], statuses: list[dict], gaps: list[dict]) -> Path:
    units = read_jsonl(FASE0 / "units.jsonl")
    inventory = read_jsonl(FASE0 / "inventory.jsonl")
    labels_a = read_jsonl(FASE0 / "labels_a.jsonl")
    labels_b = read_jsonl(FASE0 / "labels_b.jsonl")
    chars = {s["section_id"]: s["n_chars"] for s in sections}

    n = len(statuses)
    own = [s for s in statuses if not s["heredada_de"]]          # sin copias heredadas
    identical = [u for u in units if u["identica_a"]]
    out = ["# Fase 0 — Estadísticas", "",
           "Generado por `python -m src.fase0.finalize`. Las cifras salen de `data/fase0/`.", ""]

    # 1. Corpus
    out += ["## 1. Corpus auditado", ""]
    out += table(["Concepto", "Valor"], [
        ["Software distintos", len({u["software"] for u in units})],
        ["Versiones (software/versión)", len(units)],
        ["Versiones idénticas a otra (heredan etiquetas)", len(identical)],
        ["Archivos", len(inventory)],
        ["Tamaño total", f"{sum(r['bytes'] for r in inventory):,} bytes"],
        ["Secciones", n],
        ["Secciones con etiqueta final (cobertura verificada)", f"{n} ({pct(n, n)})"],
    ])
    if identical:
        out += [""] + [f"- `{u['unit']}` es idéntica a `{u['identica_a']}`." for u in identical]

    # 2. Chequeos deterministas
    checks = Counter(c["tipo"] for r in inventory for c in r["checks"])
    files_with = Counter(c["tipo"] for r in inventory for c in {c["tipo"]: c for c in r["checks"]}.values())
    out += ["", "## 2. Chequeos automáticos (paso 1)", ""]
    out += table(["Tipo", "Casos", "Archivos afectados"],
                 [[f"`{t}`", c, files_with[t]] for t, c in sorted(checks.items(), key=lambda x: -x[1])])

    # 3. LLM
    def llm_stats(labels: list[dict]) -> tuple[str, int, int, int]:
        processed = {l["unit"]: l["intentos"] for l in labels if not l["heredada_de"]}
        model = sorted({l["modelo"] for l in labels})
        return (", ".join(model), len(processed), sum(processed.values()),
                sum(1 for v in processed.values() if v > 1))

    ma, ua, ca, ra = llm_stats(labels_a)
    mb, ub, cb, rb = llm_stats(labels_b)
    out += ["", "## 3. Clasificación con LLM (pasos 2 a 4)", ""]
    out += table(["Concepto", "LLM A (clasifica)", "LLM B (valida)"], [
        ["Modelo", ma, mb],
        ["Versiones procesadas", ua, ub],
        ["Llamadas (incluidos reintentos)", ca, cb],
        ["Versiones que necesitaron reintento", ra, rb],
        ["Secciones con respuesta inválida tras el reintento",
         sum(not l["valida"] for l in labels_a), sum(not l["valida"] for l in labels_b)],
    ])

    # 4. Acuerdo A-B
    pairs = [(s["a"]["estado"], s["b"]["estado"]) for s in own if s["a"] and s["b"]]
    same_state = sum(a == b for a, b in pairs)
    same_cat = sum(1 for s in own if s["a"] and s["b"] and s["a"]["categoria"] == s["b"]["categoria"])
    out += ["", "## 4. Acuerdo entre A y B", "",
            f"Sobre {len(own)} secciones (sin contar las copias heredadas):", ""]
    out += table(["Medida", "Secciones", "%"], [
        ["Mismo estado", same_state, pct(same_state, len(own))],
        ["Misma categoría", same_cat, pct(same_cat, len(own))],
    ])
    matrix = Counter(pairs)
    out += ["", "Estado de A (filas) frente a estado de B (columnas):", ""]
    out += table(["A \\ B"] + ESTADOS, [[e] + [matrix[(e, f)] for f in ESTADOS] for e in ESTADOS])

    # 5. Revisión humana
    review = [s for s in own if s["motivo_revision"]]
    by = Counter((s["origen"], s["decision"]) for s in review)
    out += ["", "## 5. Revisión humana (paso 5)", "",
            f"Secciones con estados distintos entre A y B, o con alguna respuesta inválida: "
            f"**{len(review)}** filas en `data/fase0/human_review.csv`.", ""]
    out += table(["Decisión", "Eligió A", "Eligió B", "Total"], [
        ["Humana", by[("decision_humana", "A")], by[("decision_humana", "B")],
         by[("decision_humana", "A")] + by[("decision_humana", "B")]],
        ["Por defecto (fila vacía)", by[("decision_por_defecto", "A")], by[("decision_por_defecto", "B")],
         by[("decision_por_defecto", "A")] + by[("decision_por_defecto", "B")]],
    ])
    out += ["", "Regla por defecto: gana el modelo que eligió `parcial`; si ninguno, el que eligió `usable`."]

    # 6. Resultado final
    totals = Counter(s["estado"] for s in statuses)
    origen = Counter(s["origen"] for s in statuses)
    out += ["", "## 6. Etiqueta final", ""]
    out += table(["Estado", "Secciones", "%"], [[f"`{e}`", totals[e], pct(totals[e], n)] for e in ESTADOS])
    out += [""]
    out += table(["Origen de la etiqueta", "Secciones"], [
        ["A y B de acuerdo", origen["acuerdo_a_b"]],
        ["Decisión humana", origen["decision_humana"]],
        ["Decisión por defecto", origen["decision_por_defecto"]],
    ])

    by_unit: dict[str, Counter] = {}
    for s in statuses:
        by_unit.setdefault(s["unit"], Counter())[s["estado"]] += 1
    gaps_by_unit = Counter(g["unit"] for g in gaps if g["confirmado"])
    out += ["", "### Por software/versión", ""]
    out += table(["Software/versión"] + ESTADOS + ["Huecos confirmados"],
                 [[u] + [by_unit[u][e] for e in ESTADOS] + [gaps_by_unit[u]] for u in sorted(by_unit)])

    by_cat: dict[str, Counter] = {}
    for s in statuses:
        by_cat.setdefault(s["categoria"], Counter())[s["estado"]] += 1
    out += ["", "### Por categoría", ""]
    out += table(["Categoría"] + ESTADOS, [[c] + [by_cat[c][e] for e in ESTADOS] for c in CATEGORIAS if c in by_cat])

    # Motivos: se cuentan donde la etiqueta final es la de A (A trae los motivos detallados).
    motivos = Counter()
    for s in statuses:
        if s["estado"] != "usable" and (s["origen"] == "acuerdo_a_b" or s["decision"] == "A"):
            motivos.update({p["motivo"] for p in s["a"]["problemas"]})
    out += ["", "### Motivos de `parcial` y `no_usable`", "",
            "Según A, en las secciones cuya etiqueta final es la de A. Una sección puede tener varios motivos.", ""]
    out += table(["Motivo", "Secciones"], [[f"`{m}`", motivos[m]] for m in MOTIVOS if motivos[m]])

    # 7. Material disponible para generar datos
    usable_own = [s for s in own if s["estado"] in ("usable", "parcial")]
    usable_all = [s for s in statuses if s["estado"] in ("usable", "parcial")]
    out += ["", "## 7. Material disponible para generar datos", "",
            "Secciones `usable` y `parcial` (de las parciales se excluyen las afirmaciones citadas).", ""]
    out += table(["Concepto", "Secciones", "Caracteres"], [
        ["Todas las versiones", len(usable_all), f"{sum(chars[s['section_id']] for s in usable_all):,}"],
        ["Sin contar copias de versiones idénticas", len(usable_own),
         f"{sum(chars[s['section_id']] for s in usable_own):,}"],
    ])
    by_sw: dict[str, list] = {}
    for s in usable_own:
        by_sw.setdefault(s["software"], []).append(s)
    out += ["", "Por software (sin copias):", ""]
    out += table(["Software", "Versiones", "Secciones", "Caracteres"], [
        [sw, len({s["version"] for s in ss}), len(ss), f"{sum(chars[s['section_id']] for s in ss):,}"]
        for sw, ss in sorted(by_sw.items())])

    # 8. Huecos
    confirmed = [g for g in gaps if g["confirmado"]]
    out += ["", "## 8. Huecos de documentación", "",
            f"A listó {len(gaps)} huecos; B confirmó {len(confirmed)} ({pct(len(confirmed), len(gaps))}).", ""]
    for g in confirmed:
        out.append(f"- **{g['unit']}**: {g['descripcion']}")
    out.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(out), encoding="utf-8")
    return REPORT_PATH
