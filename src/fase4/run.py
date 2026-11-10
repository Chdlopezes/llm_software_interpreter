"""Ejecuta la fase 4: valida los candidatos de la fase 3 y exporta los datasets finales.

Uso, desde la raíz del repositorio (después de la fase 3):
    python -m src.fase4.run

Pasos, todos deterministas (sin LLM):
1. Estructura: contrato de la fase 1 y referencias resueltas hasta el catálogo.
2. Aislamiento: el caso y sus documentos son de software de su conjunto.
3. Tokens: render con la plantilla de Qwen3.5, presupuesto y máscara de pérdida.
4. Duplicados dentro de cada conjunto.
5. Revisión humana: aplica las decisiones de data/fase4/revision_humana.csv (el archivo se crea
   la primera vez con los casos de validation y test, y se conservan las decisiones al regenerarlo).
6. Exporta train/validation/test.jsonl, rejected.jsonl, dataset_report.json y
   dataset_manifest.json, y escribe reports/fase4/estadisticas.md.

Cada candidato termina en exactamente un estado: aceptado (en su conjunto) o rechazado (con su motivo).
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from collections import Counter

from src.fase0.label import FASE0, ROOT, read_jsonl, write_jsonl
from src.fase0.report import table
from src.fase1.catalog import CATALOG_PATH, FASE1
from src.fase1.restrictions import RESTRICTIONS_PATH
from src.fase1.validate import CONTRACT
from src.fase2.split import SETS, SPLITS_PATH
from src.fase3.generate import FASE3, PROMPTS
from src.fase3.tasks import SITUACIONES
from src.fase4 import checks, tokens

FASE4 = ROOT / "data" / "fase4"
REVIEW_PATH = FASE4 / "revision_humana.csv"
REVIEW_FIELDS = ["task_id", "conjunto", "situacion", "idioma", "pregunta", "decision", "comentario"]
REVIEW_SETS = ("validation", "test")
SFT_DIR = FASE4 / "sft"
SFT_SETS = ("train", "validation")       # test no se usa al entrenar: solo en la evaluación final
DECISIONES = {"": "pendiente", "aprobar": "aprobado", "rechazar": "rechazado"}


def sha256_file(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_review() -> dict[str, dict]:
    if not REVIEW_PATH.exists():
        return {}
    with REVIEW_PATH.open(encoding="utf-8", newline="") as f:
        return {row["task_id"]: row for row in csv.DictReader(f)}


def write_review(rows: list[dict], previous: dict[str, dict]) -> None:
    """Una fila por caso de validation y test que pasó los controles automáticos. Se conservan
    las decisiones ya escritas."""
    FASE4.mkdir(parents=True, exist_ok=True)
    with REVIEW_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        w.writeheader()
        for r in rows:
            old = previous.get(r["task_id"], {})
            w.writerow({"task_id": r["task_id"], "conjunto": r["conjunto"], "situacion": r["situacion"],
                        "idioma": r["idioma"], "pregunta": r["caso"]["pregunta"],
                        "decision": old.get("decision", ""), "comentario": old.get("comentario", "")})


def exported_row(r: dict, medida: dict, revision: str) -> dict:
    return {"id": r["task_id"], "conjunto": r["conjunto"], "situacion": r["situacion"], "idioma": r["idioma"],
            "messages": r["conversacion"]["messages"], "tools": r["conversacion"]["tools"],
            "caso": r["caso"], "tokens": medida["tokens"], "tokens_supervisados": medida["tokens_supervisados"],
            "revision_humana": revision}


def sft_row(r: dict) -> dict:
    """Fila para TRL: `messages` + `tools` (formato conversacional con herramientas) y
    `chat_template_kwargs`, que TRL pasa a la plantilla en cada fila. `version: null` va como el
    texto «null» (ver tokens.para_qwen). `situacion` permite filtrar la ablación E2."""
    return {"id": r["task_id"], "situacion": r["situacion"], "messages": tokens.para_qwen(r["conversacion"]["messages"]),
            "tools": r["conversacion"]["tools"], "chat_template_kwargs": {"enable_thinking": False}}


def stats(values: list[int]) -> dict:
    if not values:
        return {}
    v = sorted(values)
    return {"min": v[0], "mediana": int(statistics.median(v)), "p95": v[int(0.95 * (len(v) - 1))], "max": v[-1],
            "total": sum(v)}


def main() -> int:
    if not (FASE3 / "candidatos.jsonl").exists():
        print("[error] Falta data/fase3/candidatos.jsonl. Ejecuta antes la fase 3: python -m src.fase3.run")
        return 1
    candidates = read_jsonl(FASE3 / "candidatos.jsonl")
    coverage3 = json.loads((FASE3 / "coverage_report.json").read_text(encoding="utf-8"))
    catalog = read_jsonl(CATALOG_PATH)
    restrictions = read_jsonl(RESTRICTIONS_PATH)
    splits = json.loads(SPLITS_PATH.read_text(encoding="utf-8"))
    sections = {s["section_id"]: s for s in read_jsonl(FASE0 / "sections.jsonl")}
    tok = tokens.load_tokenizer()

    rejected: dict[str, dict] = {}

    def reject(r: dict, etapa: str, motivo: str) -> None:
        rejected.setdefault(r["task_id"], {"task_id": r["task_id"], "conjunto": r["conjunto"],
                                           "situacion": r["situacion"], "etapa": etapa, "motivo": motivo})

    # 1-3. Controles por caso.
    medidas = {}
    for r in candidates:
        errs = checks.errores_estructura(r, catalog, restrictions)
        if errs:
            reject(r, "estructura", " | ".join(errs))
            continue
        errs = checks.errores_aislamiento(r, splits["asignacion"])
        if errs:
            reject(r, "aislamiento", " | ".join(errs))
            continue
        medidas[r["task_id"]] = m = tokens.medir(tok, r["conversacion"])
        if m["errores"]:
            reject(r, "tokens", " | ".join(m["errores"]))

    # 4. Duplicados, entre los que pasaron los controles.
    ok = [r for r in candidates if r["task_id"] not in rejected]
    dups = checks.duplicados(ok, sections)
    for r in ok:
        if r["task_id"] in dups:
            d = dups[r["task_id"]]
            reject(r, "duplicado", f"duplicado de {d['de']}: {d['motivo']}")

    # 5. Revisión humana de validation y test.
    previous = load_review()
    ok = [r for r in candidates if r["task_id"] not in rejected]
    write_review([r for r in ok if r["conjunto"] in REVIEW_SETS], previous)
    revision = {}
    for r in ok:
        decision = previous.get(r["task_id"], {}).get("decision", "").strip().lower()
        if decision not in DECISIONES:
            print(f"[error] Decisión «{decision}» no válida para {r['task_id']} en {REVIEW_PATH.name}. "
                  f"Usa: aprobar, rechazar o vacío.")
            return 1
        if r["conjunto"] not in REVIEW_SETS and not decision:
            revision[r["task_id"]] = "no_aplica"
        else:
            revision[r["task_id"]] = DECISIONES[decision]
        if decision == "rechazar":
            reject(r, "revision_humana", previous[r["task_id"]].get("comentario", "").strip() or "rechazado en la revisión")

    # 6. Exportación.
    accepted = [r for r in candidates if r["task_id"] not in rejected]
    FASE4.mkdir(parents=True, exist_ok=True)
    files = {}
    for n in SETS:
        path = FASE4 / f"{n}.jsonl"
        write_jsonl(path, [exported_row(r, medidas[r["task_id"]], revision[r["task_id"]])
                           for r in accepted if r["conjunto"] == n])
        files[n] = path
    # Versión lista para el SFTTrainer de TRL: solo las columnas que lee, con los dos ajustes de render.
    for n in SFT_SETS:
        path = SFT_DIR / f"{n}.jsonl"
        SFT_DIR.mkdir(parents=True, exist_ok=True)
        write_jsonl(path, [sft_row(r) for r in accepted if r["conjunto"] == n])
        files[f"sft_{n}"] = path
    rejected_rows = ([{"task_id": o["task_id"], "conjunto": o["task_id"].split("-")[0],
                       "situacion": o["task_id"].split("-")[1], "etapa": "fase3", "motivo": o["motivo"]}
                      for o in coverage3["omitidos"] + coverage3["errores"]]
                     + sorted(rejected.values(), key=lambda x: x["task_id"]))
    write_jsonl(FASE4 / "rejected.jsonl", rejected_rows)
    files["rejected"] = FASE4 / "rejected.jsonl"

    report = build_report(candidates, accepted, rejected_rows, medidas, revision, coverage3)
    (FASE4 / "dataset_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    manifest = build_manifest(files, report, catalog)
    (FASE4 / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                                 encoding="utf-8")
    write_markdown(ROOT / "reports" / "fase4" / "estadisticas.md", report)

    c = report["contabilidad"]
    print(f"Tareas: {c['tareas']} · aceptados: {c['aceptados']} · rechazados: {c['rechazados']} "
          f"({', '.join(f'{k}: {v}' for k, v in c['rechazados_por_etapa'].items())})")
    for n in SETS:
        print(f"  {n}: {report['por_conjunto'][n]['aceptados']}")
    pend = report["revision_humana"]["pendiente"]
    if pend:
        print(f"Revisión humana: {pend} casos de validation/test pendientes en {REVIEW_PATH.relative_to(ROOT)}")
    print(f"Datasets → {FASE4.relative_to(ROOT)}/ · Reporte → reports/fase4/estadisticas.md")
    if c["tareas"] != c["aceptados"] + c["rechazados"]:
        print("[error] La contabilidad no cuadra.")
        return 1
    return 0


def build_report(candidates, accepted, rejected_rows, medidas, revision, coverage3) -> dict:
    tareas = len(candidates) + len(coverage3["omitidos"]) + len(coverage3["errores"])
    by_set = {}
    for n in SETS:
        acc = [r for r in accepted if r["conjunto"] == n]
        by_set[n] = {
            "aceptados": len(acc),
            "rechazados": sum(1 for x in rejected_rows if x["conjunto"] == n),
            "situaciones": {s: sum(r["situacion"] == s for r in acc) for s in SITUACIONES},
            "idiomas": dict(sorted(Counter(r["idioma"] for r in acc).items())),
            "tipo_evidencia": dict(sorted(Counter(t for r in acc for t in r["caso"]["tipo_evidencia"]).items())),
            "software": dict(sorted(Counter(checks.software_del_caso(r) for r in acc).items())),
            "tokens": stats([medidas[r["task_id"]]["tokens"] for r in acc]),
            "tokens_supervisados": stats([medidas[r["task_id"]]["tokens_supervisados"] for r in acc]),
        }
    return {
        "contabilidad": {"tareas": tareas, "candidatos_fase3": len(candidates), "aceptados": len(accepted),
                         "rechazados": len(rejected_rows),
                         "rechazados_por_etapa": dict(sorted(Counter(x["etapa"] for x in rejected_rows).items()))},
        "por_conjunto": by_set,
        "revision_humana": {e: sum(1 for r in accepted if revision[r["task_id"]] == e)
                            for e in ("aprobado", "pendiente", "no_aplica")}
                           | {"rechazado": sum(1 for x in rejected_rows if x["etapa"] == "revision_humana")},
        "duplicados": [x for x in rejected_rows if x["etapa"] == "duplicado"],
        "reglas": {"modelo": tokens.MODELO, "revision_tokenizer": tokens.REVISION, "max_tokens": tokens.MAX_TOKENS,
                   "jaccard_lineas": checks.JACCARD_LINEAS, "jaccard_respuesta": checks.JACCARD_RESPUESTA,
                   "jaccard_pregunta": checks.JACCARD_PREGUNTA},
    }


def build_manifest(files: dict, report: dict, catalog: list[dict]) -> dict:
    import transformers
    log = read_jsonl(FASE3 / "generation_log.jsonl")
    modelos = {t: sorted({f"{l['backend']}:{l['modelo']}" for l in log if l["tarea"] == t})
               for t in ("generador", "verificador")}
    prompts = {p.relative_to(ROOT).as_posix(): sha256_file(p)
               for p in [CONTRACT / "system_prompt.md", CONTRACT / "reglas.md",
                         CONTRACT / "conversation_schema.json", CONTRACT / "eval_case_schema.json",
                         PROMPTS / "generador.md", PROMPTS / "verificador.md"]}
    return {
        "corpus_version": catalog[0]["corpus_version"],
        "archivos": {k: {"ruta": p.relative_to(ROOT).as_posix(), "sha256": sha256_file(p),
                         "filas": sum(1 for _ in p.open(encoding="utf-8"))} for k, p in files.items()},
        "entradas": {p.relative_to(ROOT).as_posix(): sha256_file(p)
                     for p in [CATALOG_PATH, FASE1 / "restricciones.jsonl", SPLITS_PATH,
                               FASE3 / "candidatos.jsonl", REVIEW_PATH]},
        "prompts_y_contrato": prompts,
        "modelos_fase3": modelos,
        "render": {"modelo": tokens.MODELO, "revision_tokenizer": tokens.REVISION,
                   "transformers": transformers.__version__, "enable_thinking": False,
                   "max_tokens": tokens.MAX_TOKENS},
        "contabilidad": report["contabilidad"],
    }


def write_markdown(path, report: dict) -> None:
    c = report["contabilidad"]
    out = ["# Fase 4 — Estadísticas", "",
           "Generado por `python -m src.fase4.run`. Las cifras salen de `dataset_report.json`.", "",
           "## 1. Contabilidad", "",
           f"- Tareas planificadas en la fase 3: **{c['tareas']}**; candidatos: **{c['candidatos_fase3']}**.",
           f"- Aceptados: **{c['aceptados']}**; rechazados: **{c['rechazados']}**. Cada tarea tiene un solo estado final.",
           ""]
    out += table(["Etapa del rechazo", "Casos"], [[k, v] for k, v in c["rechazados_por_etapa"].items()],
                 align_right_from=1)
    out += ["", "## 2. Aceptados por conjunto y situación", ""]
    out += table(["Situación"] + [f"`{n}`" for n in SETS],
                 [[s] + [report["por_conjunto"][n]["situaciones"][s] for n in SETS] for s in SITUACIONES]
                 + [["**Total**"] + [f"**{report['por_conjunto'][n]['aceptados']}**" for n in SETS]],
                 align_right_from=1)
    out += ["", "## 3. Idioma, tipo de evidencia y software", ""]
    tipos = ["texto", "tabla", "codigo", "diagrama", "especificacion", "formula"]
    out += table(["Conjunto", "es", "en"] + tipos,
                 [[f"`{n}`"] + [report["por_conjunto"][n]["idiomas"].get(i, 0) for i in ("es", "en")]
                  + [report["por_conjunto"][n]["tipo_evidencia"].get(t, 0) for t in tipos] for n in SETS],
                 align_right_from=1)
    out += [""]
    for n in SETS:
        sw = report["por_conjunto"][n]["software"]
        out += [f"- `{n}`: " + ", ".join(f"{k} ({v})" for k, v in sw.items())]
    r = report["reglas"]
    out += ["", f"## 4. Longitud en tokens ({r['modelo']}, presupuesto {r['max_tokens']})", ""]
    out += table(["Conjunto", "Mediana", "p95", "Máximo", "Supervisados (mediana)", "Tokens totales"],
                 [[f"`{n}`", (t := report["por_conjunto"][n]["tokens"]).get("mediana"), t.get("p95"), t.get("max"),
                   report["por_conjunto"][n]["tokens_supervisados"].get("mediana"), t.get("total")] for n in SETS],
                 align_right_from=1)
    h = report["revision_humana"]
    out += ["", "## 5. Revisión humana", "",
            f"- Validation y test: **{h['aprobado']}** aprobados, **{h['rechazado']}** rechazados, "
            f"**{h['pendiente']}** pendientes.",
            "- Train no se revisa por completo; `no_aplica` significa que no tiene revisión humana.", ""]
    if report["duplicados"]:
        out += ["## 6. Duplicados eliminados", ""]
        out += [f"- `{d['task_id']}`: {d['motivo']}" for d in report["duplicados"]]
        out += [""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
