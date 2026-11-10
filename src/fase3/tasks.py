"""Fase 3, plan de tareas: qué caso se genera, en qué conjunto y con qué argumentos.

Determinista y sin LLM. Para cada conjunto:
1. Tamaño N = CASOS_POR_SECCION × secciones aprovechables del conjunto.
2. N se reparte entre las situaciones según MEZCLA (igual en los tres conjuntos).
3. Cada tarea recibe una semilla real (una sección, un hueco o un conflicto) de un
   software del conjunto, y los argumentos de la llamada se deciden aquí, por la
   situación: el generador no los elige.

Las cuotas son un máximo: si se acaban las semillas, se generan menos tareas y la
diferencia queda en el reporte. No se inventan semillas.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict

from src.fase0.label import FASE0, read_jsonl
from src.fase1.catalog import CATALOG_PATH
from src.fase1.restrictions import GAPS_PATH, RESTRICTIONS_PATH
from src.fase2.split import SETS, SPLITS_PATH

CASOS_POR_SECCION = 2
MAX_USOS_SECCION = 2          # cada sección sirve de semilla como máximo dos veces por conjunto
PROPORCION_INGLES = 0.2

# Proporción de N por situación. Grupos: responder (45%), versiones (15%),
# falta información (20%), contradicción (8%), sin llamada o sin documentos (12%).
MEZCLA = {
    "version_explicita": 0.15, "sin_version": 0.15, "software_en_historial": 0.15,
    "en_que_version": 0.075, "comparacion_versiones": 0.075,
    "evidencia_parcial": 0.10, "sin_evidencia": 0.10,
    "contradiccion": 0.08,
    "falta_software": 0.06, "sin_documentos": 0.06,
}
SITUACIONES = list(MEZCLA)

# Versiones que no existen en el catálogo, para «sin_documentos» (se descartan las que sí existan).
VERSIONES_INEXISTENTES = ["2.0", "3.1.0", "1.0.0-beta", "9.4", "0.0.1-rc"]
TIPOS = ["tabla", "codigo", "diagrama", "especificacion", "formula", "texto"]


def cuotas(n: int) -> dict[str, int]:
    """Reparte n entre las situaciones por el método del mayor resto (suma exactamente n)."""
    exact = {s: n * p for s, p in MEZCLA.items()}
    base = {s: int(v) for s, v in exact.items()}
    rest = sorted(SITUACIONES, key=lambda s: (-(exact[s] - base[s]), SITUACIONES.index(s)))
    for s in rest[:n - sum(base.values())]:
        base[s] += 1
    return base


def idioma(task_id: str) -> str:
    h = int(hashlib.sha256(task_id.encode()).hexdigest()[:8], 16)
    return "en" if h % 100 < PROPORCION_INGLES * 100 else "es"


def tipo_principal(doc: dict, lineas: list[int]) -> str:
    """Tipo de evidencia no textual con más líneas dentro de la sección; si no hay, «texto»."""
    a, b = lineas
    counts = Counter()
    for kind, ranges in doc["tipos_evidencia"].items():
        if kind != "texto":
            counts[kind] += sum(max(0, min(b, e) - max(a, s) + 1) for s, e in ranges)
    counts = +counts
    if "formula" in counts:              # hay una sola fórmula en el corpus: que no se pierda
        return "formula"
    return min(counts, key=lambda k: (-counts[k], TIPOS.index(k))) if counts else "texto"


def intercalar(secciones: list[dict]) -> list[dict]:
    """Ordena las secciones alternando su tipo principal, para repartir los tipos de evidencia."""
    by_type = defaultdict(list)
    for s in sorted(secciones, key=lambda s: s["section_id"]):
        by_type[s["tipo"]].append(s)
    out, queues = [], [by_type[t] for t in TIPOS if by_type[t]]
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def ruta_relativa(doc_id: str) -> str:
    return doc_id.split("/", 2)[2]


def versiones_del_archivo(doc: dict, catalog: list[dict]) -> list[dict]:
    """El mismo archivo en las otras versiones del software, con su hash."""
    rel = ruta_relativa(doc["id"])
    return [{"version": d["version"], "documento": d["id"], "igual": d["sha256_original"] == doc["sha256_original"]}
            for d in catalog if d["software"] == doc["software"] and ruta_relativa(d["id"]) == rel]


def load_inputs() -> dict:
    return {
        "catalog": read_jsonl(CATALOG_PATH),
        "statuses": read_jsonl(FASE0 / "section_status.jsonl"),
        "restrictions": read_jsonl(RESTRICTIONS_PATH),
        "gaps": read_jsonl(GAPS_PATH),
        "splits": json.loads(SPLITS_PATH.read_text(encoding="utf-8")),
    }


def semillas(conjunto: str, inp: dict) -> dict[str, list[dict]]:
    """Secciones, huecos y conflictos de los software del conjunto, sin repetir copias idénticas."""
    software = set(inp["splits"]["conjuntos"][conjunto]["software"])
    by_id = {d["id"]: d for d in inp["catalog"]}
    versions = defaultdict(set)
    for d in inp["catalog"]:
        versions[d["software"]].add(d["version"])

    sections = []
    for s in inp["statuses"]:
        if (s["software"] in software and s["estado"] != "no_usable" and not s["heredada_de"]
                and s["file"] in by_id):
            doc = by_id[s["file"]]
            lineas = [s["line_start"], s["line_end"]]
            otras = versiones_del_archivo(doc, inp["catalog"])
            sections.append({"tipo_semilla": "seccion", "section_id": s["section_id"], "software": s["software"],
                             "version": s["version"], "documento": doc["id"], "lineas": lineas,
                             "tipo": tipo_principal(doc, lineas), "varias_versiones": len(versions[s["software"]]) > 1,
                             "difiere_entre_versiones": any(not o["igual"] for o in otras),
                             "otras_versiones": otras})

    gaps, seen = [], set()
    for g in sorted(inp["gaps"], key=lambda g: (g.get("documento") or "", g.get("lineas") or [], g["descripcion"])):
        if g["software"] not in software or not g.get("documento"):
            continue
        key = (by_id[g["documento"]]["sha256_original"], tuple(g["lineas"]), g["descripcion"])
        if key in seen:
            continue
        seen.add(key)
        gaps.append({"tipo_semilla": "hueco", "software": g["software"], "version": g["version"],
                     "documento": g["documento"], "lineas": g["lineas"], "descripcion": g["descripcion"],
                     "evidencia": g["evidencia"], "section_id": g["section_id"]})

    conflicts, seen = [], set()
    for r in sorted(inp["restrictions"], key=lambda r: r["id"]):
        doc = by_id[r["id"]]
        if doc["software"] not in software:
            continue
        for c in r["conflictos"]:
            if not c["lineas"]:
                continue
            key = (doc["sha256_original"], tuple(c["lineas"]), c["cita"])
            if key in seen:
                continue
            seen.add(key)
            conflicts.append({"tipo_semilla": "conflicto", "software": doc["software"], "version": doc["version"],
                              "documento": doc["id"], "lineas": c["lineas"], "motivo": c["motivo"],
                              "cita": c["cita"], "explicacion": c["explicacion"],
                              "otras_secciones": c["otras_secciones"], "section_id": c["section_id"]})
    return {"secciones": intercalar(sections), "huecos": gaps, "conflictos": conflicts}


def argumentos(situacion: str, semilla: dict, catalog_versions: dict[str, set]) -> dict | None:
    """Argumentos esperados de la llamada, decididos por la situación (reglas 1-3 del contrato)."""
    sw = semilla["software"]
    if situacion == "falta_software":
        return None
    if situacion in ("sin_version", "en_que_version", "comparacion_versiones"):
        return {"software": sw, "version": None}
    if situacion == "sin_documentos":
        h = int(hashlib.sha256(semilla.get("section_id", sw).encode()).hexdigest()[:8], 16)
        opciones = [v for v in VERSIONES_INEXISTENTES if v not in catalog_versions[sw]]
        return {"software": sw, "version": opciones[h % len(opciones)]}
    return {"software": sw, "version": semilla["version"]}


def build(inp: dict | None = None) -> list[dict]:
    inp = inp or load_inputs()
    catalog_versions = defaultdict(set)
    for d in inp["catalog"]:
        catalog_versions[d["software"]].add(d["version"])

    tasks = []
    for conjunto in SETS:
        n = CASOS_POR_SECCION * inp["splits"]["conjuntos"][conjunto]["cobertura"]["secciones"]
        quota = cuotas(n)
        seeds = semillas(conjunto, inp)
        uses = Counter()

        def tomar(pool: list[dict], k: int) -> list[dict]:
            """Primero secciones sin usar; solo después, las usadas una vez. Así dos situaciones
            no comparten semilla (y casi la misma pregunta) mientras queden secciones libres."""
            out, taken = [], set()
            for usos in range(MAX_USOS_SECCION):
                for s in pool:
                    if len(out) == k:
                        return out
                    if uses[s["section_id"]] == usos and s["section_id"] not in taken:
                        uses[s["section_id"]] += 1
                        taken.add(s["section_id"])
                        # En el segundo uso se pide otro aspecto de la sección (ver generador.md).
                        out.append(dict(s, segundo_uso=True) if usos else s)
            return out

        picked: dict[str, list[dict]] = {}
        sections = seeds["secciones"]
        multi = [s for s in sections if s["varias_versiones"]]
        # Primero lo que diferencia versiones, si existe.
        multi_cmp = sorted(multi, key=lambda s: not s["difiere_entre_versiones"])
        picked["comparacion_versiones"] = tomar(multi_cmp, quota["comparacion_versiones"])
        picked["en_que_version"] = tomar(multi_cmp, quota["en_que_version"])
        picked["contradiccion"] = seeds["conflictos"][:quota["contradiccion"]]

        # Huecos: sin_evidencia empieza donde termina evidencia_parcial, para que no compartan
        # hueco mientras haya; si no alcanzan, un hueco sirve a las dos. Si aun así faltan, se
        # completa con secciones: «dato ausente», verificado por el verificador.
        gaps = seeds["huecos"]
        offset = 0
        for situacion in ("evidencia_parcial", "sin_evidencia"):
            k = min(quota[situacion], len(gaps))
            got = [gaps[(offset + i) % len(gaps)] for i in range(k)] if gaps else []
            offset += k
            got += [dict(s, dato_ausente=True) for s in tomar(sections, quota[situacion] - len(got))]
            picked[situacion] = got
        for situacion in ("version_explicita", "sin_version", "software_en_historial",
                          "falta_software", "sin_documentos"):
            picked[situacion] = tomar(sections, quota[situacion])

        for situacion in SITUACIONES:
            for i, seed in enumerate(picked[situacion], 1):
                task_id = f"{conjunto}-{situacion}-{i:03d}"
                tasks.append({"task_id": task_id, "conjunto": conjunto, "situacion": situacion,
                              "idioma": idioma(task_id), "semilla": seed,
                              "args": argumentos(situacion, seed, catalog_versions),
                              "cuota": quota[situacion]})
    return tasks


def resumen(tasks: list[dict], inp: dict) -> dict:
    """Cuotas pedidas y tareas planificadas, por conjunto y situación."""
    out = {}
    for conjunto in SETS:
        quota = cuotas(CASOS_POR_SECCION * inp["splits"]["conjuntos"][conjunto]["cobertura"]["secciones"])
        ts = [t for t in tasks if t["conjunto"] == conjunto]
        out[conjunto] = {s: {"cuota": quota[s], "tareas": sum(t["situacion"] == s for t in ts)}
                         for s in SITUACIONES}
    return out
