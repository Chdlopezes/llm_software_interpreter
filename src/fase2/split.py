"""Fase 2: separación en entrenamiento, validación y prueba por software.

Determinista y sin LLM. Lee las salidas de las fases 0 y 1 y escribe
data/fase2/splits.json.

Criterio (ver docs/fase2.md). Lo importante es que en cada conjunto se puedan
plantear los mismos TIPOS de pregunta; cuántas de cada tipo se balancea en la fase 3.

1. Unidad: grupo de software. Software que comparten contenido (MIN_SHARED_LINES o
   más líneas largas iguales) forman un grupo y van juntos al mismo conjunto.
2. Perfil de cada grupo: secciones aprovechables (tamaño), tipos de contenido,
   varias versiones, versiones con contenido distinto, huecos y conflictos.
3. Mínimo obligatorio (REQUIRED_ALL en cada conjunto, REQUIRED_TEST en prueba).
   Un elemento presente en menos de 3 grupos no puede exigirse en los tres
   conjuntos y queda fuera del mínimo (se informa).
4. Objetivo: entre los repartos que cumplen el mínimo, el más cercano a TARGET en
   secciones aprovechables. Desempates: validación y prueba más parecidas; prueba
   más grande; orden alfabético de la asignación.
5. Búsqueda: con pocos grupos libres se prueban todas las combinaciones; con
   muchos, reparto voraz (cada grupo, de mayor a menor, al conjunto con más falta).
"""

from __future__ import annotations

import itertools
import json
from collections import Counter, defaultdict

from src.fase0.label import FASE0, ROOT, read_jsonl
from src.fase1.catalog import CATALOG_PATH
from src.fase1.reference_examples import REFERENCE_SOFTWARE
from src.fase1.restrictions import GAPS_PATH, RESTRICTIONS_PATH

FASE2 = ROOT / "data" / "fase2"
SPLITS_PATH = FASE2 / "splits.json"

SETS = ["train", "validation", "test"]
TARGET = {"train": 0.6, "validation": 0.2, "test": 0.2}
FORCED = {s: "train" for s in REFERENCE_SOFTWARE}       # conversaciones de referencia (fase 1)

# Elementos del perfil que habilitan un tipo de pregunta.
CONTENT_TYPES = ["tabla", "codigo", "diagrama", "especificacion", "formula"]
FEATURES = CONTENT_TYPES + ["huecos", "conflictos", "varias_versiones", "versiones_distintas"]
REQUIRED_ALL = ["tabla", "codigo", "diagrama", "especificacion", "formula", "huecos", "conflictos",
                "varias_versiones"]
REQUIRED_TEST = ["versiones_distintas"]
MIN_GROUPS_TO_REQUIRE = 3          # un elemento en menos grupos no puede estar en los tres conjuntos

MAX_EXHAUSTIVE = 12                # grupos libres; 3^12 ≈ 531.000 combinaciones
MIN_LINE_CHARS = 25                # línea «larga» para detectar contenido compartido
MIN_SHARED_LINES = 3


# ---------------------------------------------------------------------------
# Perfil de cada software y grupos
# ---------------------------------------------------------------------------

def long_lines(doc: dict) -> set[str]:
    return {l.strip() for l in doc["contenido"].split("\n") if len(l.strip()) > MIN_LINE_CHARS}


def software_groups(catalog: list[dict]) -> list[list[str]]:
    """Une los software que comparten MIN_SHARED_LINES o más líneas largas (componentes
    conexas). Con muchos documentos, esta comparación se sustituiría por MinHash/LSH."""
    lines: dict[str, set[str]] = defaultdict(set)
    for d in catalog:
        lines[d["software"]] |= long_lines(d)
    names = sorted(lines)
    parent = {n: n for n in names}

    def find(n):
        while parent[n] != n:
            n = parent[n]
        return n

    for a, b in itertools.combinations(names, 2):
        if len(lines[a] & lines[b]) >= MIN_SHARED_LINES:
            parent[find(b)] = find(a)
    groups: dict[str, list[str]] = defaultdict(list)
    for n in names:
        groups[find(n)].append(n)
    return sorted(groups.values())


def software_profiles(catalog: list[dict], statuses: list[dict], restrictions: list[dict],
                      gaps: list[dict]) -> dict[str, dict]:
    restr = {r["id"]: r for r in restrictions}
    profiles = {}
    for software in sorted({d["software"] for d in catalog}):
        docs = [d for d in catalog if d["software"] == software]
        by_version: dict[str, set] = defaultdict(set)
        for d in docs:
            by_version[d["version"]].add((d["id"].split("/", 2)[2], d["sha256_original"]))
        lines = Counter()
        seen = set()
        for d in docs:                                   # cada texto idéntico cuenta una vez
            if d["sha256_original"] in seen:
                continue
            seen.add(d["sha256_original"])
            for kind, ranges in d["tipos_evidencia"].items():
                lines[kind] += sum(e - s + 1 for s, e in ranges)
        conflicts = {(c["cita"], str(c["lineas"])) for d in docs for c in restr[d["id"]]["conflictos"]}
        profiles[software] = {
            "secciones": sum(1 for s in statuses if s["software"] == software
                             and not s["heredada_de"] and s["estado"] != "no_usable"),
            "versiones": sorted(by_version),
            "lineas_por_tipo": {k: lines[k] for k in CONTENT_TYPES if lines[k]},
            "huecos": sum(1 for g in gaps if g["software"] == software),
            "conflictos": len(conflicts),
            "varias_versiones": len(by_version) > 1,
            "versiones_distintas": len({frozenset(v) for v in by_version.values()}) > 1,
        }
    return profiles


def has(profile: dict, feature: str) -> bool:
    if feature in CONTENT_TYPES:
        return profile["lineas_por_tipo"].get(feature, 0) > 0
    value = profile[feature]
    return value > 0 if isinstance(value, int) and not isinstance(value, bool) else bool(value)


# ---------------------------------------------------------------------------
# Mínimo, objetivo y búsqueda
# ---------------------------------------------------------------------------

def requirements(groups: list[list[str]], profiles: dict) -> tuple[dict[str, list[str]], list[str]]:
    """Lo que se exige a cada conjunto y los elementos que no pueden exigirse (en pocos grupos)."""
    def n_groups(f):
        return sum(1 for g in groups if any(has(profiles[s], f) for s in g))
    excluded = [f for f in REQUIRED_ALL if n_groups(f) < MIN_GROUPS_TO_REQUIRE]
    common = [f for f in REQUIRED_ALL if f not in excluded]
    req = {"train": list(common), "validation": list(common), "test": common + REQUIRED_TEST}
    return req, excluded


def violations(assignment: dict[str, str], groups: list[list[str]], profiles: dict,
               req: dict[str, list[str]]) -> list[str]:
    """Incumplimientos del mínimo obligatorio. assignment: software → conjunto."""
    errors = []
    for software, target in FORCED.items():
        if software in assignment and assignment[software] != target:
            errors.append(f"{software} debe ir a {target}")
    for g in groups:
        if len({assignment[s] for s in g}) > 1:
            errors.append(f"el grupo {g} está repartido entre conjuntos")
    for name in SETS:
        members = [s for s, a in assignment.items() if a == name]
        if not members:
            errors.append(f"{name} está vacío")
            continue
        for f in req[name]:
            if not any(has(profiles[s], f) for s in members):
                errors.append(f"{name} no tiene «{f}»")
    return errors


def sizes(assignment: dict[str, str], profiles: dict) -> dict[str, int]:
    return {n: sum(profiles[s]["secciones"] for s, a in assignment.items() if a == n) for n in SETS}


def score(assignment: dict[str, str], profiles: dict) -> tuple:
    w = sizes(assignment, profiles)
    total = sum(w.values())
    deviation = sum(abs(w[n] / total - TARGET[n]) for n in SETS)
    order = tuple(assignment[s] for s in sorted(assignment))
    return (round(deviation, 9), abs(w["validation"] - w["test"]), -w["test"], order)


def expand(group_assignment: dict[int, str], groups: list[list[str]]) -> dict[str, str]:
    return {s: group_assignment[i] for i, g in enumerate(groups) for s in g}


def search(groups: list[list[str]], profiles: dict, req: dict) -> tuple[dict[str, str], dict]:
    fixed = {i: next(FORCED[s] for s in g if s in FORCED) for i, g in enumerate(groups)
             if any(s in FORCED for s in g)}
    free = [i for i in range(len(groups)) if i not in fixed]
    if len(free) <= MAX_EXHAUSTIVE:
        best, valid = None, 0
        for combo in itertools.product(SETS, repeat=len(free)):
            assignment = expand({**fixed, **dict(zip(free, combo))}, groups)
            if violations(assignment, groups, profiles, req):
                continue
            valid += 1
            key = score(assignment, profiles)
            if best is None or key < best[0]:
                best = (key, assignment)
        if best is None:
            raise SystemExit("[error] Ningún reparto cumple el mínimo obligatorio.")
        return best[1], {"metodo": "exhaustivo", "combinaciones": 3 ** len(free), "combinaciones_validas": valid}

    # Muchos grupos: reparto voraz por tamaño, hacia el conjunto con más falta.
    weight = {i: sum(profiles[s]["secciones"] for s in g) for i, g in enumerate(groups)}
    total = sum(weight.values())
    load = {n: sum(weight[i] for i, a in fixed.items() if a == n) for n in SETS}
    chosen = dict(fixed)
    for i in sorted(free, key=lambda i: (-weight[i], groups[i][0])):
        target = max(SETS, key=lambda n: (TARGET[n] * total - load[n], -SETS.index(n)))
        chosen[i] = target
        load[target] += weight[i]
    assignment = expand(chosen, groups)
    errors = violations(assignment, groups, profiles, req)
    if errors:
        raise SystemExit("[error] El reparto voraz no cumple el mínimo: " + "; ".join(errors))
    return assignment, {"metodo": "voraz", "combinaciones": None, "combinaciones_validas": None}


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------

def coverage(members: list[str], profiles: dict) -> dict:
    return {
        "secciones": sum(profiles[s]["secciones"] for s in members),
        "huecos": sum(profiles[s]["huecos"] for s in members),
        "conflictos": sum(profiles[s]["conflictos"] for s in members),
        "lineas_por_tipo": {k: sum(profiles[s]["lineas_por_tipo"].get(k, 0) for s in members)
                            for k in CONTENT_TYPES},
        "varias_versiones": [s for s in members if profiles[s]["varias_versiones"]],
        "versiones_distintas": [s for s in members if profiles[s]["versiones_distintas"]],
    }


def shared_lines_between_sets(catalog: list[dict], assignment: dict[str, str]) -> list[dict]:
    owners: dict[str, set] = defaultdict(set)
    for d in catalog:
        for line in long_lines(d):
            owners[line].add(assignment[d["software"]])
    return [{"linea": line, "conjuntos": sorted(sets)} for line, sets in sorted(owners.items()) if len(sets) > 1]


def build() -> dict:
    catalog = read_jsonl(CATALOG_PATH)
    profiles = software_profiles(catalog, read_jsonl(FASE0 / "section_status.jsonl"),
                                 read_jsonl(RESTRICTIONS_PATH), read_jsonl(GAPS_PATH))
    groups = software_groups(catalog)
    req, excluded = requirements(groups, profiles)
    assignment, method = search(groups, profiles, req)
    w = sizes(assignment, profiles)
    total = sum(w.values())
    sets = {}
    for name in SETS:
        members = sorted(s for s, a in assignment.items() if a == name)
        sets[name] = {
            "software": members,
            "proporcion": round(w[name] / total, 4),
            "cobertura": coverage(members, profiles),
            "documentos": [{"id": d["id"], "sha256_canonico": d["sha256_canonico"]}
                           for d in catalog if d["software"] in members],
        }
    return {
        "corpus_version": catalog[0]["corpus_version"],
        "criterio": {
            "objetivo": TARGET,
            "peso": "secciones aprovechables (usable + parcial, sin copias heredadas)",
            "obligatorio": req,
            "no_exigible_por_escaso": excluded,
            "forzados": FORCED,
            "desempates": ["validation y test lo más parecidos en tamaño", "test más grande",
                           "orden alfabético de la asignación"],
            **method,
        },
        "grupos": groups,
        "perfiles": profiles,
        "asignacion": dict(sorted(assignment.items())),
        "conjuntos": sets,
        "lineas_compartidas_entre_conjuntos": shared_lines_between_sets(catalog, assignment),
    }


def conjunto_de(software: str, splits: dict | None = None) -> str:
    """Conjunto al que pertenece una conversación sobre `software` (lo usará la fase 3)."""
    splits = splits or json.loads(SPLITS_PATH.read_text(encoding="utf-8"))
    return splits["asignacion"][software]


def main() -> int:
    result = build()
    FASE2.mkdir(parents=True, exist_ok=True)
    SPLITS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    c = result["criterio"]
    print(f"Separación ({c['metodo']}; {c['combinaciones_validas']} de {c['combinaciones']} repartos "
          f"cumplen el mínimo) → {SPLITS_PATH.relative_to(ROOT)}")
    for name, s in result["conjuntos"].items():
        print(f"  {name:<10} {s['proporcion']:.0%}  {', '.join(s['software'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
