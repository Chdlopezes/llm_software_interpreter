"""Estadísticas de la fase 1, en reports/fase1/estadisticas.md. Determinista (sin fechas)."""

from __future__ import annotations

from collections import Counter
from itertools import combinations

from src.fase0.label import FASE0, ROOT, read_jsonl
from src.fase0.report import table
from src.fase1.catalog import CATALOG_PATH, NAV_FILES
from src.fase1.reference_examples import REFERENCE_PATH, REFERENCE_SOFTWARE
from src.fase1.restrictions import GAPS_PATH, RESTRICTIONS_PATH
from src.fase1.tool import CALLS_PATH, CHARS_PER_TOKEN, MAX_CONTEXT_TOKENS, RESERVED_TOKENS

REPORT_PATH = ROOT / "reports" / "fase1" / "estadisticas.md"
TYPES = ["texto", "tabla", "codigo", "diagrama", "especificacion", "formula"]


def n_lines(ranges: list[list[int]]) -> int:
    return sum(e - s + 1 for s, e in ranges)


def consistency(copies: list[list[str]], restr: dict[str, dict]) -> list[str]:
    """Consistencia de la fase 0 entre copias idénticas: el mismo texto auditado más de
    una vez en llamadas independientes. Se excluyen las copias heredadas (versiones
    idénticas completas), cuyas etiquetas son iguales por construcción."""
    inherited = {s["section_id"] for s in read_jsonl(FASE0 / "section_status.jsonl") if s["heredada_de"]}
    pairs, diffs = 0, []
    for ids in copies:
        own = [i for i in ids if restr[i]["secciones"]
               and not any(s["section_id"] in inherited for s in restr[i]["secciones"])]
        for x, y in combinations(own, 2):
            for a, b in zip(restr[x]["secciones"], restr[y]["secciones"]):
                pairs += 1
                if a["estado"] != b["estado"]:
                    diffs.append([f"`{x}`", f"{a['lineas'][0]}-{a['lineas'][1]}",
                                  f"{x.split('/')[1]}: `{a['estado']}`", f"{y.split('/')[1]}: `{b['estado']}`"])
    if not pairs:
        return []
    out = ["### Consistencia de la fase 0 entre copias idénticas", "",
           "Los documentos idénticos de versiones que la fase 0 auditó por separado permiten medir cuánto varía "
           "su etiqueta cuando se audita el mismo texto en llamadas independientes al LLM.", "",
           f"Pares de secciones idénticas: **{pairs}**. Mismo estado final: **{pairs - len(diffs)}** "
           f"({100 * (pairs - len(diffs)) / pairs:.1f}%). Distinto: **{len(diffs)}**.", ""]
    if diffs:
        out += table(["Documento", "Líneas", "Estado en una copia", "Estado en la otra"], diffs, align_right_from=4)
        out += ["", "Las líneas no citables de estas copias se unen (regla conservadora); el estado de cada "
                "sección se conserva tal como lo dejó la fase 0.", ""]
    return out


def write_report() -> None:
    docs = read_jsonl(CATALOG_PATH)
    restr = {r["id"]: r for r in read_jsonl(RESTRICTIONS_PATH)}
    gaps = read_jsonl(GAPS_PATH)
    calls = read_jsonl(CALLS_PATH)
    refs = read_jsonl(REFERENCE_PATH)
    out = ["# Fase 1 — Estadísticas", "",
           "Generado por `python -m src.fase1.run`. Las cifras salen de `data/fase1/`.", ""]

    # 1. Catálogo
    out += ["## 1. Catálogo", "",
            f"- Versión del corpus: `{docs[0]['corpus_version']}`.",
            f"- Documentos: **{len(docs)}** (archivos de `docs_raw` sin los de navegación: "
            + ", ".join(f"`{n}`" for n in sorted(NAV_FILES)) + ").",
            f"- Líneas: {sum(d['n_lineas'] for d in docs):,}; caracteres: {sum(len(d['contenido']) for d in docs):,}.", ""]
    by_unit: dict[tuple, list] = {}
    for d in docs:
        by_unit.setdefault((d["software"], d["version"]), []).append(d)
    out += table(["Software", "Versión", "Documentos", "Líneas", "Caracteres"],
                 [[s, v, len(ds), sum(d["n_lineas"] for d in ds), f"{sum(len(d['contenido']) for d in ds):,}"]
                  for (s, v), ds in sorted(by_unit.items())], align_right_from=2)

    same: dict[str, list[str]] = {}
    for d in docs:
        same.setdefault(d["sha256_original"], []).append(d["id"])
    copies = [ids for ids in same.values() if len(ids) > 1]
    out += ["", f"Documentos idénticos byte a byte entre versiones: **{len(copies)} grupos**. "
            "La fase 2 debe mantener cada grupo en el mismo conjunto.", ""]
    differing = [ids for ids in copies if len({str(restr[i]["no_citables_propias"]) for i in ids}) > 1]
    if differing:
        out += [f"En **{len(differing)} grupos** la fase 0 marcó líneas no citables distintas en el mismo texto "
                "(cada versión se auditó por separado). Se aplica la regla conservadora: una línea es no citable "
                "si lo es en cualquiera de las copias.", ""]
        out += table(["Documentos idénticos", "No citables propias", "No citables aplicadas"],
                     [["<br>".join(f"`{i}`" for i in ids),
                       "<br>".join(str(restr[i]["no_citables_propias"]) for i in ids),
                       str(restr[ids[0]]["no_citables"])] for ids in differing], align_right_from=3)
        out += [""]
    out += consistency(copies, restr)

    # 2. Normalización
    kinds = Counter(t for d in docs for ch in d["transformaciones"] for t in ch["tipos"])
    secrets = Counter(s for d in docs for ch in d["transformaciones"] for s in ch.get("secretos", []))
    out += ["## 2. Normalización (sin mover líneas)", ""]
    out += table(["Transformación", "Líneas", "Documentos"],
                 [[f"`{k}`", n, sum(1 for d in docs if any(k in ch["tipos"] for ch in d["transformaciones"]))]
                  for k, n in sorted(kinds.items(), key=lambda x: -x[1])])
    out += ["", "Secretos redactados por tipo: "
            + (", ".join(f"`{k}` {n}" for k, n in sorted(secrets.items())) or "ninguno") + ".", ""]

    # 3. Tipos de evidencia
    out += ["## 3. Tipos de evidencia", ""]
    out += table(["Tipo", "Documentos", "Líneas"],
                 [[f"`{t}`", sum(1 for d in docs if t in d["tipos_evidencia"]),
                   sum(n_lines(d["tipos_evidencia"].get(t, [])) for d in docs)] for t in TYPES])

    # 4. Restricciones
    rs = list(restr.values())
    estados = Counter()
    for r in rs:
        for s in r["secciones"]:
            estados[s["estado"]] += s["lineas"][1] - s["lineas"][0] + 1
    out += ["", "## 4. Restricciones de la fase 0", "",
            "La herramienta devuelve los documentos completos; estas restricciones solo limitan de qué partes "
            "se crean ejemplos.", ""]
    out += table(["Concepto", "Valor"], [
        ["Líneas en secciones `usable`", estados["usable"]],
        ["Líneas en secciones `parcial`", estados["parcial"]],
        ["Líneas en secciones `no_usable`", estados["no_usable"]],
        ["Líneas no citables (no_usable + afirmaciones excluidas)", sum(n_lines(r["no_citables"]) for r in rs)],
        ["Afirmaciones excluidas (localizadas / total)",
         f"{sum(1 for r in rs for e in r['afirmaciones_excluidas'] if e['lineas'])} / "
         f"{sum(len(r['afirmaciones_excluidas']) for r in rs)}"],
        ["Conflictos (contradicción / inconsistencia)",
         f"{sum(1 for r in rs for c in r['conflictos'] if c['motivo'] == 'contradiccion')} / "
         f"{sum(1 for r in rs for c in r['conflictos'] if c['motivo'] == 'inconsistencia')}"],
        ["Huecos confirmados (con documento y líneas / total)",
         f"{sum(1 for g in gaps if g['lineas'])} / {len(gaps)}"],
    ])
    out += ["", "Las cifras incluyen las copias de versiones idénticas.", ""]

    # 5. Llamadas y contexto
    out += ["## 5. Llamadas posibles y ventana de contexto", "",
            f"Estimación: {CHARS_PER_TOKEN} caracteres por token sobre el JSON que devuelve la herramienta. "
            f"Límite: {MAX_CONTEXT_TOKENS:,} tokens, reservando {RESERVED_TOKENS:,} para sistema, pregunta y "
            "respuesta. La medición exacta se hace con el tokenizador del modelo al exportar.", ""]
    out += table(["Software", "version", "Documentos", "Tokens estimados", "Cabe"],
                 [[c["software"], "null" if c["version"] is None else c["version"], len(c["ids"]),
                   f"{c['tokens_estimados']:,}", "sí" if c["cabe_en_contexto"] else "**no**"] for c in calls],
                 align_right_from=2)

    # 6. Situaciones disponibles
    multi = sorted(s for s in {d["software"] for d in docs} if len({v for (sw, v) in by_unit if sw == s}) > 1)
    out += ["", "## 6. Material para cada situación", ""]
    out += table(["Situación", "Material disponible"], [
        ["version_explicita", f"{len(by_unit)} versiones"],
        ["sin_version", f"{len({d['software'] for d in docs})} software"],
        ["en_que_version, comparacion_versiones", f"{len(multi)} software con varias versiones: "
         + ", ".join(multi)],
        ["evidencia_parcial, sin_evidencia", f"{len(gaps)} huecos confirmados"],
        ["contradiccion", f"{sum(len(r['conflictos']) for r in rs)} conflictos localizados"],
        ["falta_software, software_en_historial, sin_documentos", "siempre"],
    ], align_right_from=2)

    # 7. Ejemplos de referencia
    out += ["", "## 7. Ejemplos de referencia", "",
            f"{len(refs)} conversaciones, una por situación, validadas contra el contrato. Usan solo "
            + ", ".join(f"`{s}`" for s in REFERENCE_SOFTWARE) + ", que deben quedar en entrenamiento en la fase 2.", ""]
    out += table(["Caso", "Situación", "Idioma", "Llamada", "Documentos", "Tipo de evidencia"],
                 [[f"`{r['caso']['case_id']}`", r["caso"]["situacion"], r["caso"]["idioma"],
                   "—" if r["caso"]["expected_tool"] is None else
                   f"`{r['caso']['expected_tool']['arguments']['software']}`, "
                   f"`{r['caso']['expected_tool']['arguments']['version']}`",
                   len(r["caso"]["expected_document_ids"]), ", ".join(r["caso"]["tipo_evidencia"]) or "—"]
                  for r in refs], align_right_from=6)
    out.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(out), encoding="utf-8")
