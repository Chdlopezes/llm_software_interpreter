"""Fase 0, pasos 2 a 4: el LLM A clasifica cada sección y el LLM B valida cada
clasificación de A.

Cada LLM usa un único prompt fijo (prompts/clasificador_a.md y
prompts/validador_b.md). Por cada software/versión se envían todas sus secciones
y los chequeos del paso 1. La respuesta se valida por código y se escribe en:

    A: data/fase0/labels_a.jsonl (una línea por sección) y gaps_a.jsonl (huecos)
    B: data/fase0/labels_b.jsonl (una línea por sección) y gaps_b.jsonl (huecos)

Cada respuesta de un LLM se guarda en data/cache/fase0/<a|b>/. Si el prompt, el
modelo y el contenido no cambian, se reutiliza la respuesta guardada en lugar de
llamar al LLM: así el resultado se reproduce exactamente.

Uso, desde la raíz del repositorio:
    python -m src.fase0.label --role A                                 # todas las versiones
    python -m src.fase0.label --role B
    python -m src.fase0.label --role A --unit price-engine-api/latest  # solo una
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from src.llm import LLMError, generate, get_config

ROOT = Path(__file__).resolve().parents[2]
FASE0 = ROOT / "data" / "fase0"
CACHE_DIR = ROOT / "data" / "cache" / "fase0"
PROMPTS = Path(__file__).parent / "prompts"

ESTADOS = ["usable", "parcial", "no_usable"]
MOTIVOS = ["contradiccion", "inconsistencia", "incompleto", "roto", "vacio", "sin_contenido_tecnico"]
CATEGORIAS = ["endpoint_api", "modelo_datos", "configuracion", "procedimiento", "arquitectura",
              "troubleshooting", "descripcion_general", "navegacion_metadatos", "otro"]

SCHEMA_A = {
    "type": "object",
    "properties": {
        "secciones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_id": {"type": "string"},
                    "categoria": {"type": "string", "enum": CATEGORIAS},
                    "estado": {"type": "string", "enum": ESTADOS},
                    "problemas": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "motivo": {"type": "string", "enum": MOTIVOS},
                                "cita": {"type": "string"},
                                "otras_secciones": {"type": "array", "items": {"type": "string"}},
                                "explicacion": {"type": "string"},
                            },
                            "required": ["motivo", "cita", "otras_secciones", "explicacion"],
                            "additionalProperties": False,
                        },
                    },
                    "justificacion": {"type": "string"},
                },
                "required": ["section_id", "categoria", "estado", "problemas", "justificacion"],
                "additionalProperties": False,
            },
        },
        "huecos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string"},
                    "evidencia": {"type": "string"},
                    "section_id": {"type": "string"},
                },
                "required": ["descripcion", "evidencia", "section_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["secciones", "huecos"],
    "additionalProperties": False,
}


SCHEMA_B = {
    "type": "object",
    "properties": {
        "secciones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_id": {"type": "string"},
                    "de_acuerdo": {"type": "boolean"},
                    "estado": {"type": "string", "enum": ESTADOS},
                    "categoria": {"type": "string", "enum": CATEGORIAS},
                    "cita": {"type": "string"},
                    "explicacion": {"type": "string"},
                },
                "required": ["section_id", "de_acuerdo", "estado", "categoria", "cita", "explicacion"],
                "additionalProperties": False,
            },
        },
        "huecos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hueco": {"type": "integer"},
                    "de_acuerdo": {"type": "boolean"},
                    "explicacion": {"type": "string"},
                },
                "required": ["hueco", "de_acuerdo", "explicacion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["secciones", "huecos"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Datos del paso 1
# ---------------------------------------------------------------------------

def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_step1() -> tuple[list[dict], dict[str, list[dict]], dict[str, list[dict]]]:
    """Devuelve (unidades, secciones por unidad, archivos por unidad)."""
    if not (FASE0 / "sections.jsonl").exists():
        raise SystemExit("[error] Falta data/fase0/sections.jsonl: ejecuta antes `python -m src.fase0.extract`.")
    units = read_jsonl(FASE0 / "units.jsonl")
    sections: dict[str, list[dict]] = {}
    for s in read_jsonl(FASE0 / "sections.jsonl"):
        sections.setdefault(s["unit"], []).append(s)
    files: dict[str, list[dict]] = {}
    for r in read_jsonl(FASE0 / "inventory.jsonl"):
        files.setdefault(r["unit"], []).append(r)
    return units, sections, files


# ---------------------------------------------------------------------------
# Mensaje con la documentación de una versión (igual para A y B)
# ---------------------------------------------------------------------------

def document_message(unit: dict, sections: list[dict], files: list[dict]) -> str:
    prefix = unit["unit"] + "/"
    out = [f"Software: {unit['software']}", f"Versión: {unit['version']}", "",
           "## Chequeos automáticos (comprobados por código)"]
    checks = [(r["path"][len(prefix):], c) for r in files for c in r["checks"]]
    if checks:
        for path, c in checks:
            where = f"{path}, línea {c['linea']}" if c["linea"] else path
            out.append(f"- [{where}] {c['tipo']}: {c['detalle']}")
    else:
        out.append("- (ninguno)")
    out += ["", f"## Secciones ({len(sections)})", ""]
    for s in sections:
        out.append(f'<seccion id="{s["section_id"]}" archivo="{s["file"][len(prefix):]}" '
                   f'lineas="{s["line_start"]}-{s["line_end"]}" tipo="{s["kind"]}">')
        out.append(s["text"])
        out.append("</seccion>")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Validación por código
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def quote_in(quote: str, text: str) -> bool:
    q = normalize(quote)
    return bool(q) and q in normalize(text)


def validate_a(resp: dict, sections: list[dict]) -> dict[str, list[str]]:
    """Errores por section_id. Una sección sin errores tiene lista vacía.
    La clave '_huecos' recoge los errores de los huecos."""
    by_id = {s["section_id"]: s for s in sections}
    errors: dict[str, list[str]] = {sid: [] for sid in by_id}
    errors["_huecos"] = []
    seen: dict[str, int] = {}
    for item in resp.get("secciones", []):
        sid = item.get("section_id")
        if sid not in by_id:
            errors["_huecos"].append(f"section_id inexistente en la respuesta: {sid}")
            continue
        seen[sid] = seen.get(sid, 0) + 1
        if item["estado"] == "usable" and item["problemas"]:
            errors[sid].append("estado usable con problemas")
        if item["estado"] != "usable" and not item["problemas"]:
            errors[sid].append(f"estado {item['estado']} sin problemas citados")
        for p in item["problemas"]:
            if not quote_in(p["cita"], by_id[sid]["text"]):
                errors[sid].append(f"cita no encontrada en la sección: {p['cita'][:80]!r}")
            for other in p["otras_secciones"]:
                if other not in by_id:
                    errors[sid].append(f"otra sección inexistente: {other}")
    for sid in by_id:
        if seen.get(sid, 0) == 0:
            errors[sid].append("sección no clasificada")
        elif seen[sid] > 1:
            errors[sid].append("sección clasificada más de una vez")
    for h in resp.get("huecos", []):
        if h["section_id"] not in by_id:
            errors["_huecos"].append(f"hueco con section_id inexistente: {h['section_id']}")
        elif not quote_in(h["evidencia"], by_id[h["section_id"]]["text"]):
            errors["_huecos"].append(f"evidencia no encontrada: {h['evidencia'][:80]!r}")
    return errors


def validate_b(resp: dict, sections: list[dict], labels_a: list[dict], n_gaps: int) -> dict[str, list[str]]:
    """Errores por section_id en la respuesta de B; '_huecos' para los huecos."""
    by_id = {s["section_id"]: s for s in sections}
    a_by_id = {l["section_id"]: l for l in labels_a}
    errors: dict[str, list[str]] = {sid: [] for sid in by_id}
    errors["_huecos"] = []
    seen: dict[str, int] = {}
    for item in resp.get("secciones", []):
        sid = item.get("section_id")
        if sid not in by_id:
            errors["_huecos"].append(f"section_id inexistente en la respuesta: {sid}")
            continue
        seen[sid] = seen.get(sid, 0) + 1
        a = a_by_id.get(sid, {})
        if item["de_acuerdo"] and (item["estado"], item["categoria"]) != (a.get("estado"), a.get("categoria")):
            errors[sid].append("de_acuerdo=true pero el estado o la categoría no coinciden con los de A")
        if item["estado"] != "usable" and not quote_in(item["cita"], by_id[sid]["text"]):
            errors[sid].append(f"cita no encontrada en la sección: {item['cita'][:80]!r}")
    for sid in by_id:
        if seen.get(sid, 0) == 0:
            errors[sid].append("sección sin veredicto")
        elif seen[sid] > 1:
            errors[sid].append("sección con más de un veredicto")
    got = sorted(h["hueco"] for h in resp.get("huecos", []))
    if got != list(range(1, n_gaps + 1)):
        errors["_huecos"].append(f"se esperaban veredictos para los huecos 1..{n_gaps}, llegaron {got}")
    return errors


def labels_message(labels_a: list[dict], gaps_a: list[dict]) -> str:
    """Clasificación de A tal como la ve B."""
    secciones = [{k: l[k] for k in ("section_id", "estado", "categoria", "problemas", "justificacion")}
                 for l in labels_a]
    huecos = [{"hueco": i, "descripcion": g["descripcion"], "evidencia": g["evidencia"],
               "section_id": g["section_id"]} for i, g in enumerate(gaps_a, start=1)]
    return ("## Clasificación del auditor A\n\n" + json.dumps(
        {"secciones": secciones, "huecos": huecos}, ensure_ascii=False, indent=1))


def retry_message(errors: dict[str, list[str]]) -> str:
    lines = ["Tu respuesta anterior tiene estos errores. Devuelve de nuevo tu respuesta "
             "completa, para todas las secciones, corrigiéndolos:"]
    for sid, errs in errors.items():
        for e in errs:
            lines.append(f"- {sid}: {e}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Caché de respuestas
# ---------------------------------------------------------------------------

# Contadores para informar si las respuestas vinieron del caché o de llamadas reales.
STATS = {"cache": 0, "llm": 0}


def cache_path(role: str, unit: str) -> Path:
    return CACHE_DIR / role.lower() / (unit.replace("/", "__") + ".json")


def call_cached(role: str, unit: str, system: str, messages: list[str], schema: dict,
                attempt: int, cfg) -> dict:
    """Devuelve la respuesta del intento `attempt`. La clave del caché depende del
    prompt, el modelo, el esquema y todos los mensajes; si cambia algo, se vuelve a
    llamar al LLM."""
    key = hashlib.sha256(json.dumps(
        [system, messages, schema, cfg.model], ensure_ascii=False).encode()).hexdigest()
    path = cache_path(role, unit)
    cached = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    attempts = cached.get("intentos", [])
    hit = next((a for a in attempts if a["clave"] == key), None)
    if hit:
        STATS["cache"] += 1
        return hit["respuesta"]
    STATS["llm"] += 1
    # Los mensajes se unen en uno: los cuatro backends reciben un único prompt.
    resp = generate(cfg, system, "\n\n".join(messages), schema)
    attempts = [a for a in attempts if a["intento"] < attempt] + [
        {"intento": attempt, "clave": key, "modelo": cfg.model, "backend": cfg.backend,
         "respuesta": resp}]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"unit": unit, "intentos": attempts}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return resp


# ---------------------------------------------------------------------------
# Llamada con validación y un reintento (igual para A y B)
# ---------------------------------------------------------------------------

def ask(role: str, unit: str, messages: list[str], schema: dict, validate, cfg) -> tuple[dict, dict, int]:
    """Llama al LLM, valida y, si hay errores, reintenta una vez mostrándole sus
    errores. Devuelve (respuesta, errores por sección, número de intentos)."""
    system = (PROMPTS / PROMPT_FILES[role]).read_text(encoding="utf-8")
    resp = call_cached(role, unit, system, messages, schema, 1, cfg)
    errors = validate(resp)
    if not any(errors.values()):
        return resp, errors, 1
    messages = messages + ["Tu respuesta anterior:\n" + json.dumps(resp, ensure_ascii=False),
                           retry_message(errors)]
    resp = call_cached(role, unit, system, messages, schema, 2, cfg)
    return resp, validate(resp), 2


PROMPT_FILES = {"A": "clasificador_a.md", "B": "validador_b.md"}
# Configuración de .env de cada rol: LLM_CLASIFICADOR_* y LLM_VALIDADOR_*.
TAREA = {"A": "clasificador", "B": "validador"}


def label_unit_a(unit: dict, sections: list[dict], files: list[dict], cfg) -> tuple[list[dict], list[dict]]:
    """Paso 2: A clasifica cada sección y lista los huecos."""
    messages = [document_message(unit, sections, files)]
    resp, errors, attempts = ask("A", unit["unit"], messages, SCHEMA_A,
                                 lambda r: validate_a(r, sections), cfg)
    by_id = {}
    for item in resp["secciones"]:
        by_id.setdefault(item["section_id"], item)
    texts = {s["section_id"]: s["text"] for s in sections}
    labels = []
    for s in sections:
        sid = s["section_id"]
        item = by_id.get(sid)
        labels.append({
            "section_id": sid, "unit": unit["unit"],
            "estado": item["estado"] if item else None,
            "categoria": item["categoria"] if item else None,
            "problemas": item["problemas"] if item else [],
            "justificacion": item["justificacion"] if item else "",
            "valida": not errors[sid], "errores": errors[sid],
            "intentos": attempts, "modelo": cfg.model, "heredada_de": None,
        })
    gaps = [{"unit": unit["unit"], "hueco": i, **h,
             "valido": quote_in(h["evidencia"], texts.get(h["section_id"], ""))}
            for i, h in enumerate(resp["huecos"], start=1)]
    return labels, gaps


def label_unit_b(unit: dict, sections: list[dict], files: list[dict], labels_a: list[dict],
                 gaps_a: list[dict], cfg) -> tuple[list[dict], list[dict]]:
    """Paso 4: B emite un veredicto sobre cada clasificación de A y cada hueco."""
    messages = [document_message(unit, sections, files), labels_message(labels_a, gaps_a)]
    resp, errors, attempts = ask("B", unit["unit"], messages, SCHEMA_B,
                                 lambda r: validate_b(r, sections, labels_a, len(gaps_a)), cfg)
    by_id = {}
    for item in resp["secciones"]:
        by_id.setdefault(item["section_id"], item)
    labels = []
    for s in sections:
        sid = s["section_id"]
        item = by_id.get(sid)
        labels.append({
            "section_id": sid, "unit": unit["unit"],
            "de_acuerdo": item["de_acuerdo"] if item else None,
            "estado": item["estado"] if item else None,
            "categoria": item["categoria"] if item else None,
            "cita": item["cita"] if item else "",
            "explicacion": item["explicacion"] if item else "",
            "valida": not errors[sid], "errores": errors[sid],
            "intentos": attempts, "modelo": cfg.model, "heredada_de": None,
        })
    verdicts = {h["hueco"]: h for h in resp["huecos"]}
    gaps = [{"unit": unit["unit"], "hueco": g["hueco"],
             "de_acuerdo": verdicts.get(g["hueco"], {}).get("de_acuerdo"),
             "explicacion": verdicts.get(g["hueco"], {}).get("explicacion", ""),
             "valido": g["hueco"] in verdicts}
            for g in gaps_a]
    return labels, gaps


def inherit(labels: list[dict], gaps: list[dict], unit: dict, source: str) -> tuple[list[dict], list[dict]]:
    """Copia las etiquetas de una versión idéntica, cambiando solo los identificadores."""
    old, new = source + "/", unit["unit"] + "/"

    def move(sid: str) -> str:
        return new + sid[len(old):] if sid.startswith(old) else sid

    out_labels = []
    for l in labels:
        if l["unit"] != source:
            continue
        row = {**l, "section_id": move(l["section_id"]), "unit": unit["unit"],
               "heredada_de": l["section_id"]}
        if "problemas" in l:
            row["problemas"] = [{**p, "otras_secciones": [move(o) for o in p["otras_secciones"]]}
                                for p in l["problemas"]]
        out_labels.append(row)
    out_gaps = [{**g, "unit": unit["unit"], **({"section_id": move(g["section_id"])} if "section_id" in g else {})}
                for g in gaps if g["unit"] == source]
    return out_labels, out_gaps


def run(role: str, unit_name: str | None = None) -> int:
    """Ejecuta el LLM `role` ('A' o 'B') sobre todas las versiones, o solo sobre `unit_name`."""
    args = argparse.Namespace(role=role, unit=unit_name)

    units, sections, files = load_step1()
    if args.unit:
        selected = [u for u in units if u["unit"] == args.unit]
        if not selected:
            print(f"[error] No existe la versión {args.unit}. Opciones: {', '.join(u['unit'] for u in units)}")
            return 1
        if selected[0]["identica_a"]:
            selected = [u for u in units if u["unit"] == selected[0]["identica_a"]] + selected
    else:
        selected = units
    suffix = "" if not args.unit else "_" + args.unit.replace("/", "__")

    if role == "B":
        a_path = FASE0 / f"labels_a{suffix}.jsonl"
        if not a_path.exists():
            print(f"[error] Falta {a_path.relative_to(ROOT)}: ejecuta antes el paso de A con los mismos argumentos.")
            return 1
        all_labels_a = read_jsonl(a_path)
        all_gaps_a = read_jsonl(FASE0 / f"gaps_a{suffix}.jsonl")

    try:
        cfg = get_config(TAREA[role])
    except LLMError as e:
        print(f"[error] {e}")
        return 1

    labels, gaps = [], []
    for unit in selected:
        name = unit["unit"]
        if unit["identica_a"]:
            l, g = inherit(labels, gaps, unit, unit["identica_a"])
            print(f"{name}: hereda de {unit['identica_a']} ({len(l)} secciones)")
        else:
            verb = "clasificando" if role == "A" else "validando"
            print(f"{name}: {verb} {len(sections[name])} secciones con {cfg.label}...", flush=True)
            try:
                if role == "A":
                    l, g = label_unit_a(unit, sections[name], files[name], cfg)
                else:
                    la = [x for x in all_labels_a if x["unit"] == name]
                    ga = [x for x in all_gaps_a if x["unit"] == name]
                    l, g = label_unit_b(unit, sections[name], files[name], la, ga, cfg)
            except LLMError as e:
                print(f"[error] {name}: {e}")
                return 1
            n_bad = sum(not x["valida"] for x in l)
            if role == "A":
                counts = {e: sum(x["estado"] == e for x in l) for e in ESTADOS}
                print(f"  {counts}, huecos: {len(g)}, inválidas: {n_bad}")
            else:
                n_dis = sum(x["de_acuerdo"] is False for x in l)
                print(f"  de acuerdo con A: {len(l) - n_dis - n_bad}, en desacuerdo: {n_dis}, "
                      f"inválidas: {n_bad}, huecos confirmados: {sum(x['de_acuerdo'] is True for x in g)}/{len(g)}")
        labels += l
        gaps += g

    print(f"Respuestas: {STATS['cache']} desde el caché, {STATS['llm']} con llamadas al LLM")
    r = role.lower()
    write_jsonl(FASE0 / f"labels_{r}{suffix}.jsonl", labels)
    write_jsonl(FASE0 / f"gaps_{r}{suffix}.jsonl", gaps)
    print(f"Escrito data/fase0/labels_{r}{suffix}.jsonl y gaps_{r}{suffix}.jsonl")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--role", required=True, choices=["A", "B"], help="A clasifica; B valida a A")
    parser.add_argument("--unit", help="procesa solo esta versión, p. ej. price-engine-api/latest")
    args = parser.parse_args()
    return run(args.role, args.unit)


if __name__ == "__main__":
    sys.exit(main())
