"""Fase 3, cobertura y estadísticas. Deterministas: solo dependen de los resultados."""

from __future__ import annotations

from collections import Counter

from src.fase0.report import table
from src.fase2.split import SETS
from src.fase3.generate import CRITERIOS
from src.fase3.tasks import SITUACIONES

ESTADOS = ["verificado", "revisar", "omitido", "error"]


def coverage(results: list[dict], log: list[dict], plan: dict) -> dict:
    by_set = {}
    for n in SETS:
        rs = [r for r in results if r["conjunto"] == n]
        by_set[n] = {
            "situaciones": {s: {"cuota": plan[n][s]["cuota"], "tareas": plan[n][s]["tareas"],
                                **{e: sum(r["situacion"] == s and r["estado"] == e for r in rs) for e in ESTADOS}}
                            for s in SITUACIONES},
            "idiomas": dict(Counter(r["idioma"] for r in rs if r["estado"] in ("verificado", "revisar"))),
        }
    sections: dict[str, dict] = {}
    for r in results:
        sid = r["semilla"].get("section_id")
        if sid:
            s = sections.setdefault(sid, {"conjunto": r["conjunto"], "casos": []})
            s["casos"].append({"task_id": r["task_id"], "estado": r["estado"], "motivo": r["motivo"]})
    gen = [l for l in log if l["tarea"] == "generador"]
    ver = [l for l in log if l["tarea"] == "verificador"]
    return {
        "por_conjunto": by_set,
        "llamadas": {"generador": len(gen), "verificador": len({l["clave"] for l in ver}),
                     "verificaciones": len(ver),
                     "correcciones_por_codigo": sum(1 for l in gen if l["correccion"] > 0),
                     "rechazos_del_verificador": sum(1 for l in ver if l["resultado"].startswith("rechazado"))},
        "omitidos": [{"task_id": r["task_id"], "motivo": r["motivo"]} for r in results if r["estado"] == "omitido"],
        "errores": [{"task_id": r["task_id"], "motivo": r["motivo"]} for r in results if r["estado"] == "error"],
        "secciones": dict(sorted(sections.items())),
    }


def write_report(path, results: list[dict], cov: dict, verifications: list[dict]) -> None:
    out = ["# Fase 3 — Estadísticas", "",
           "Generado por `python -m src.fase3.run`. Las cifras salen de `candidatos.jsonl`, "
           "`generation_log.jsonl` y `coverage_report.json`.", ""]

    out += ["## 1. Resultado por conjunto", ""]
    rows = []
    for n in SETS:
        sits = cov["por_conjunto"][n]["situaciones"]
        rows.append([f"`{n}`", sum(v["cuota"] for v in sits.values()), sum(v["tareas"] for v in sits.values())]
                    + [sum(v[e] for v in sits.values()) for e in ESTADOS])
    out += table(["Conjunto", "Cuota", "Tareas ejecutadas"] + ESTADOS, rows, align_right_from=1)

    out += ["", "## 2. Candidatos (verificados + revisar) / tareas ejecutadas / cuota, por situación", ""]
    rows = [[s] + [f"{(v := cov['por_conjunto'][n]['situaciones'][s])['verificado'] + v['revisar']} / "
                   f"{v['tareas']} / {v['cuota']}" for n in SETS] for s in SITUACIONES]
    out += table(["Situación"] + [f"`{n}`" for n in SETS], rows, align_right_from=1)

    out += ["", "## 3. Idioma y tipo de evidencia de los candidatos", ""]
    ok = [r for r in results if r["estado"] in ("verificado", "revisar")]
    rows = [[f"`{n}`", cov["por_conjunto"][n]["idiomas"].get("es", 0), cov["por_conjunto"][n]["idiomas"].get("en", 0)]
            + [sum(1 for r in ok if r["conjunto"] == n and t in r["caso"]["tipo_evidencia"])
               for t in ("texto", "tabla", "codigo", "diagrama", "especificacion", "formula")] for n in SETS]
    out += table(["Conjunto", "es", "en", "texto", "tabla", "código", "diagrama", "OpenAPI", "fórmula"],
                 rows, align_right_from=1)

    c = cov["llamadas"]
    out += ["", "## 4. Calidad del generador", "",
            f"- Llamadas al generador: **{c['generador']}**; de ellas, correcciones por errores de código: "
            f"**{c['correcciones_por_codigo']}**.",
            f"- Llamadas al verificador: **{c['verificador']}** (por grupos de casos del mismo software), "
            f"con **{c['verificaciones']}** verificaciones; rechazos: **{c['rechazos_del_verificador']}**"
            + (f" ({c['rechazos_del_verificador'] / c['verificaciones']:.0%})." if c["verificaciones"] else "."), ""]
    fails = Counter(k for v in verifications for k, x in v["criterios"].items() if x["resultado"] in ("parcial", "no_cumple"))
    if fails:
        out += ["Criterios que motivaron rechazos (una verificación puede fallar en varios):", ""]
        out += table(["Criterio", "Veces"], [[k, fails[k]] for k in CRITERIOS if fails[k]], align_right_from=1)
        out += [""]

    if cov["omitidos"] or cov["errores"]:
        out += ["## 5. Omitidos y errores", ""]
        out += [f"- `{o['task_id']}`: {o['motivo']}" for o in cov["omitidos"] + cov["errores"]]
        out += [""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
