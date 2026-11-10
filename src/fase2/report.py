"""Estadísticas de la fase 2, en data/reportes/fase2/estadisticas.md. Determinista (sin fechas)."""

from __future__ import annotations

from src.fase0.label import ROOT
from src.fase0.report import table
from src.fase2.split import CONTENT_TYPES, SETS, TARGET

REPORT_PATH = ROOT / "data" / "reportes" / "fase2" / "estadisticas.md"

# Qué hace falta en un conjunto para poder plantear cada tipo de pregunta.
SITUATION_NEEDS = [
    ("version_explicita, sin_version", None),
    ("falta_software, software_en_historial, sin_documentos", None),
    ("en_que_version", "varias_versiones"),
    ("comparacion_versiones (con diferencias reales)", "versiones_distintas"),
    ("comparacion_versiones (versiones idénticas: «no cambia»)", "varias_versiones"),
    ("evidencia_parcial, sin_evidencia", "huecos"),
    ("contradiccion", "conflictos"),
]
TYPE_NAMES = {"tabla": "tablas", "codigo": "código", "diagrama": "diagramas",
              "especificacion": "OpenAPI", "formula": "fórmulas"}


def available(cov: dict, need: str | None) -> bool:
    if need is None:
        return True
    if need in ("varias_versiones", "versiones_distintas"):
        return bool(cov[need])
    return cov[need] > 0


def write_report(splits: dict) -> None:
    c, sets, prof = splits["criterio"], splits["conjuntos"], splits["perfiles"]
    out = ["# Fase 2 — Estadísticas", "",
           "Generado por `python -m src.fase2.run`. Las cifras salen de `data/fase2/splits.json`.", ""]

    out += ["## 1. Reparto", ""]
    out += table(["Conjunto", "Software", "Secciones", "Proporción", "Objetivo"],
                 [[f"`{n}`", ", ".join(sets[n]["software"]), sets[n]["cobertura"]["secciones"],
                   f"{sets[n]['proporcion']:.1%}", f"{TARGET[n]:.0%}"] for n in SETS], align_right_from=2)
    out += ["", f"- Método: **{c['metodo']}**"
            + (f": {c['combinaciones_validas']:,} de {c['combinaciones']:,} repartos cumplen el mínimo obligatorio; "
               "se elige el más cercano al objetivo." if c["metodo"] == "exhaustivo" else "."),
            "- Peso: " + c["peso"] + ".",
            "- Forzados a `train` (conversaciones de referencia de la fase 1): "
            + ", ".join(f"`{s}`" for s in c["forzados"]) + ".",
            "- Desempates: " + "; ".join(c["desempates"]) + ".",
            "- Grupos de software con contenido compartido: "
            + (", ".join(" + ".join(g) for g in splits["grupos"] if len(g) > 1) or "ninguno (cada software es su propio grupo)")
            + ".", ""]

    out += ["## 2. Tipos de pregunta que permite cada conjunto", "",
            "Lo importante es que en cada conjunto se puedan plantear los mismos tipos de pregunta; cuántas "
            "de cada tipo se balancea en la fase 3.", ""]
    rows = [[s] + ["sí" if available(sets[n]["cobertura"], need) else "**no**" for n in SETS]
            for s, need in SITUATION_NEEDS]
    rows += [[f"preguntas sobre {TYPE_NAMES[t]}"]
             + ["sí" if sets[n]["cobertura"]["lineas_por_tipo"][t] else "**no**" for n in SETS]
             for t in CONTENT_TYPES]
    out += table(["Tipo de pregunta"] + [f"`{n}`" for n in SETS], rows, align_right_from=4)
    if c["no_exigible_por_escaso"]:
        out += ["", "No se exige en todos los conjuntos (aparece en menos de 3 software): "
                + ", ".join(f"`{f}`" for f in c["no_exigible_por_escaso"]) + "."]
    out += [""]

    out += ["## 3. Cobertura por conjunto", ""]
    rows = [["Huecos"] + [sets[n]["cobertura"]["huecos"] for n in SETS],
            ["Conflictos"] + [sets[n]["cobertura"]["conflictos"] for n in SETS]]
    rows += [[f"Líneas de {TYPE_NAMES[t]}"] + [sets[n]["cobertura"]["lineas_por_tipo"][t] for n in SETS]
             for t in CONTENT_TYPES]
    rows += [["Varias versiones"] + [", ".join(sets[n]["cobertura"]["varias_versiones"]) or "—" for n in SETS],
             ["Versiones con contenido distinto"]
             + [", ".join(sets[n]["cobertura"]["versiones_distintas"]) or "—" for n in SETS],
             ["Documentos"] + [len(sets[n]["documentos"]) for n in SETS]]
    out += table(["Concepto"] + [f"`{n}`" for n in SETS], rows, align_right_from=4)

    out += ["", "## 4. Perfil de cada software", ""]
    out += table(["Software", "Conjunto", "Secciones", "Versiones", "Difieren", "Huecos", "Conflictos", "Contenido"],
                 [[s, splits["asignacion"][s], p["secciones"], len(p["versiones"]),
                   "sí" if p["versiones_distintas"] else "no", p["huecos"], p["conflictos"],
                   ", ".join(f"{TYPE_NAMES[k]} {v}" for k, v in p["lineas_por_tipo"].items())]
                  for s, p in sorted(prof.items(), key=lambda x: (SETS.index(splits["asignacion"][x[0]]), x[0]))],
                 align_right_from=2)

    shared = splits["lineas_compartidas_entre_conjuntos"]
    out += ["", "## 5. Fugas entre conjuntos", "",
            f"Líneas de más de 25 caracteres que aparecen en más de un conjunto: **{len(shared)}**.", ""]
    out += [f"- `{s['linea']}` ({', '.join(s['conjuntos'])})" for s in shared]
    by_hash: dict[str, set] = {}
    for n in SETS:
        for d in sets[n]["documentos"]:
            by_hash.setdefault(d["sha256_canonico"], set()).add(n)
    crossing = sum(1 for v in by_hash.values() if len(v) > 1)
    out += ["", f"Documentos idénticos (mismo hash) en más de un conjunto: **{crossing}**.", ""]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(out), encoding="utf-8")
