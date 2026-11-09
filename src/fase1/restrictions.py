"""Fase 1, restricciones: traslada la auditoría de la fase 0 a líneas de cada documento.

La fase 0 decide DE QUÉ partes se pueden crear ejemplos, no qué ve el modelo: la
herramienta siempre devuelve el documento completo. Estas restricciones las usan el
generador, el verificador y la validación; nunca entran en la conversación.

Escribe en data/fase1/:
    restricciones.jsonl  una fila por documento del catálogo:
        secciones              cada sección de la fase 0 con sus líneas y su estado final
        no_citables            rangos que no pueden respaldar una respuesta:
                               secciones no_usable + líneas de afirmaciones excluidas.
                               En documentos idénticos (copias_identicas) es la unión
                               de las copias; no_citables_propias, lo de este documento
        afirmaciones_excluidas cada afirmación excluida de una sección parcial, con sus líneas
        conflictos             contradicciones e inconsistencias señaladas por A, con sus
                               líneas: fuente de la situación «contradicción», la única que
                               puede citar líneas no citables, y solo para señalar el conflicto
    huecos.jsonl         un hueco confirmado por fila, por software/versión, con las líneas
                         de su evidencia si está en un documento del catálogo

Las líneas coinciden con las del original porque el catálogo no mueve líneas.
"""

from __future__ import annotations

import re

from src.fase0.extract import DOCS_RAW, read_lines
from src.fase0.label import FASE0, read_jsonl, write_jsonl
from src.fase1.catalog import CATALOG_PATH, FASE1

RESTRICTIONS_PATH = FASE1 / "restricciones.jsonl"
GAPS_PATH = FASE1 / "huecos.jsonl"
CONFLICT_MOTIVOS = {"contradiccion", "inconsistencia"}


def locate(quote: str, lines: list[str], start: int, end: int) -> list[int] | None:
    """Líneas [inicio, fin] donde aparece la cita dentro de las líneas start..end
    (1-based), comparando con los espacios normalizados, como en la fase 0."""
    q = re.sub(r"\s+", " ", quote).strip()
    if not q:
        return None
    chars, owner = [], []                      # texto normalizado y línea de cada carácter
    for n in range(start, end + 1):
        for ch in lines[n - 1] + "\n":
            if ch.isspace():
                if chars and chars[-1] != " ":
                    chars.append(" ")
                    owner.append(n)
            else:
                chars.append(ch)
                owner.append(n)
    i = "".join(chars).find(q)
    if i < 0:
        return None
    return [owner[i], owner[i + len(q) - 1]]


def locate_in_doc(quote: str, doc_lines: tuple[list[str], list[str]], start: int, end: int) -> list[int] | None:
    """Busca primero en el original (donde citó la fase 0) y después en el canónico."""
    raw, canon = doc_lines
    return locate(quote, raw, start, end) or locate(quote, canon, start, end)


def merge(ranges: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def build(catalog: list[dict], statuses: list[dict], gaps: list[dict]) -> tuple[list[dict], list[dict]]:
    by_doc: dict[str, list[dict]] = {}
    for s in statuses:
        by_doc.setdefault(s["file"], []).append(s)
    lines_of = {d["id"]: (read_lines((DOCS_RAW / d["id"]).read_text(encoding="utf-8")), d["contenido"].split("\n"))
                for d in catalog}

    rows = []
    for doc in catalog:
        lines = lines_of[doc["id"]]
        secciones, no_citables, excluidas, conflictos = [], [], [], []
        for s in sorted(by_doc.get(doc["id"], []), key=lambda s: s["line_start"]):
            rng = [s["line_start"], s["line_end"]]
            secciones.append({"section_id": s["section_id"], "lineas": rng, "estado": s["estado"],
                              "categoria": s["categoria"]})
            if s["estado"] == "no_usable":
                no_citables.append(rng)
            for cita in s["afirmaciones_excluidas"]:
                where = locate_in_doc(cita, lines, *rng)
                excluidas.append({"section_id": s["section_id"], "cita": cita, "lineas": where})
                if where:
                    no_citables.append(where)
            for p in (s["a"] or {}).get("problemas", []):
                if p["motivo"] in CONFLICT_MOTIVOS:
                    conflictos.append({"section_id": s["section_id"], "estado_final": s["estado"],
                                       "motivo": p["motivo"], "cita": p["cita"],
                                       "lineas": locate_in_doc(p["cita"], lines, *rng),
                                       "otras_secciones": p["otras_secciones"],
                                       "explicacion": p["explicacion"]})
        rows.append({"id": doc["id"], "software": doc["software"], "version": doc["version"],
                     "secciones": secciones, "no_citables_propias": merge(no_citables),
                     "afirmaciones_excluidas": excluidas, "conflictos": conflictos})

    # Copias idénticas: la fase 0 auditó cada versión por separado y a veces marcó líneas
    # distintas en el mismo texto. Regla conservadora: una línea es no citable si lo es
    # en cualquiera de las copias, y los conflictos de una copia valen para todas.
    copies: dict[str, list[dict]] = {}
    for doc, row in zip(catalog, rows):
        copies.setdefault(doc["sha256_original"], []).append(row)
    for group in copies.values():
        union = merge([r for row in group for r in row["no_citables_propias"]])
        seen, conflicts = set(), []
        for row in group:
            for c in row["conflictos"]:
                key = (c["cita"], str(c["lineas"]))
                if key not in seen:
                    seen.add(key)
                    conflicts.append(c)
        for row in group:
            row["no_citables"] = union
            row["copias_identicas"] = [r["id"] for r in group if r is not row]
            row["conflictos"] = conflicts
    rows = [{k: r[k] for k in ("id", "software", "version", "copias_identicas", "secciones", "no_citables",
                                "no_citables_propias", "afirmaciones_excluidas", "conflictos")} for r in rows]

    sections = {s["section_id"]: s for s in statuses}
    gap_rows = []
    for g in gaps:
        if not g["confirmado"]:
            continue
        s = sections[g["section_id"]]
        in_catalog = s["file"] in lines_of
        where = locate_in_doc(g["evidencia"], lines_of[s["file"]], s["line_start"], s["line_end"]) if in_catalog else None
        software, version = g["unit"].split("/")
        gap_rows.append({"software": software, "version": version, "descripcion": g["descripcion"],
                         "evidencia": g["evidencia"], "section_id": g["section_id"],
                         "documento": s["file"] if in_catalog else None, "lineas": where})
    return rows, gap_rows


def main() -> int:
    catalog = read_jsonl(CATALOG_PATH)
    rows, gap_rows = build(catalog, read_jsonl(FASE0 / "section_status.jsonl"), read_jsonl(FASE0 / "gaps.jsonl"))
    write_jsonl(RESTRICTIONS_PATH, rows)
    write_jsonl(GAPS_PATH, gap_rows)
    missing = [(r["id"], e["cita"]) for r in rows for e in r["afirmaciones_excluidas"] if e["lineas"] is None]
    n_excl = sum(len(r["afirmaciones_excluidas"]) for r in rows)
    print(f"Restricciones: {len(rows)} documentos, {n_excl} afirmaciones excluidas "
          f"({n_excl - len(missing)} localizadas), {sum(len(r['conflictos']) for r in rows)} conflictos, "
          f"{len(gap_rows)} huecos")
    for doc_id, cita in missing:
        print(f"  [aviso] afirmación excluida no localizada en {doc_id}: «{cita[:80]}»")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
