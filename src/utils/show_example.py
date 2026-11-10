"""Muestra ejemplos candidatos de la fase 3 al azar, con sus citas resueltas.

Para cada ejemplo muestra:
- la conversación completa: historial, pregunta, llamada a la herramienta (argumentos y
  documentos devueltos) y respuesta de referencia;
- el texto de cada cita, sacado del documento, para comprobar que respalda lo afirmado;
- los answer_checks, el veredicto del verificador y, si el caso necesitó más de una ronda,
  los rechazos anteriores.

Uso, desde la raíz del repositorio:
    python -m src.utils.show_example --conjunto test
    python -m src.utils.show_example --conjunto train --situacion contradiccion -n 3
    python -m src.utils.show_example --idioma en --tipo tabla --seed 7
    python -m src.utils.show_example --rechazados            # casos aprobados tras un rechazo
    python -m src.utils.show_example --id test-sin_evidencia-001 --criterios

Filtros (se combinan entre sí):
    --conjunto    train, validation o test.
    --situacion   una de las 10 situaciones (version_explicita, sin_version, ...).
    --idioma      es o en.
    --software    nombre del software, o parte del nombre (por ejemplo, traffic).
    --tipo        tipo de evidencia citada: texto, tabla, codigo, diagrama, especificacion, formula.
    --rechazados  solo los casos que el verificador rechazó al menos una vez.
    --buscar      texto que aparezca en la pregunta o en la respuesta (sin distinguir mayúsculas).
    --id          un caso concreto (ignora los demás filtros).

Otras opciones:
    -n            cuántos ejemplos mostrar (por defecto 1).
    --seed        semilla, para obtener siempre los mismos ejemplos.
    --criterios   muestra la justificación del verificador para cada criterio.
    --omitidos    en lugar de candidatos, lista las tareas omitidas y su motivo.

Lee data/fase3/candidatos.jsonl, generation_log.jsonl y coverage_report.json, y el
catálogo de la fase 1 para resolver las citas.
"""

import argparse
import json
import random
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FASE3 = ROOT / "data" / "fase3"
CATALOG = ROOT / "data" / "fase1" / "catalogo.jsonl"
SETS = ["train", "validation", "test"]
SITUACIONES = ["version_explicita", "sin_version", "software_en_historial", "en_que_version",
               "comparacion_versiones", "evidencia_parcial", "sin_evidencia", "contradiccion",
               "falta_software", "sin_documentos"]
TIPOS = ["texto", "tabla", "codigo", "diagrama", "especificacion", "formula"]
CITA = re.compile(r"\[([^\[\]:]+):L(\d+)-L(\d+)\]")
RULE = "=" * 80
SUB = "-" * 80


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def software_de(r: dict) -> str:
    args = (r["caso"]["expected_tool"] or {}).get("arguments") or {}
    return args.get("software") or r["semilla"]["documento"].split("/")[0]


def indent(text: str, prefix: str = "    ") -> str:
    return textwrap.indent(text, prefix)


def show_conversation(r: dict) -> None:
    for m in r["conversacion"]["messages"]:
        role = m["role"]
        if role == "system":
            continue
        if role == "tool":
            out = json.loads(m["content"])
            docs = out.get("documentos", [])
            print(f"[herramienta] status: {out['status']} · {len(docs)} documentos")
            for d in docs:
                print(f"    - {d['id']} ({len(d['contenido'].splitlines())} líneas)")
        elif m.get("tool_calls"):
            for c in m["tool_calls"]:
                f = c["function"]
                print(f"[asistente → herramienta] {f['name']}({json.dumps(f['arguments'], ensure_ascii=False)})")
        else:
            print(f"[{'usuario' if role == 'user' else 'asistente'}]")
            print(indent(m["content"]))
        print()
    if r["caso"]["expected_action"] == "clarification":
        print("(sin llamada a la herramienta: el asistente pide aclarar el software)\n")


def show_citations(r: dict, catalog: dict) -> None:
    cites = list(dict.fromkeys(CITA.findall(r["caso"]["reference_answer"])))
    if not cites:
        return
    print(SUB)
    print(f"Citas ({len(cites)}), con el texto del documento:")
    for doc, a, b in cites:
        a, b = int(a), int(b)
        lines = catalog[doc]["contenido"].split("\n")[a - 1:b] if doc in catalog else ["(documento no encontrado)"]
        print(f"\n  [{doc}:L{a}-L{b}]")
        shown = lines[:12]
        for i, line in enumerate(shown, a):
            print(f"  {i:4d}| {line}")
        if len(lines) > len(shown):
            print(f"        … {len(lines) - len(shown)} líneas más")


def show_case(r: dict, log: list[dict], criterios: bool) -> None:
    c = r["caso"]
    print(SUB)
    print("answer_checks (para el juez de la evaluación):")
    for ch in c["answer_checks"]:
        print(f"  - {ch}")
    print(f"Documentos esperados: {len(c['expected_document_ids'])} · Tipo de evidencia: "
          f"{', '.join(c['tipo_evidencia']) or '—'}")
    if c["restricciones"]:
        for x in c["restricciones"]:
            print(f"Restricción: {x['tipo']}" + (f" — {x['descripcion']}" if x.get("descripcion") else ""))

    print(SUB)
    v = r["verificacion"]
    malos = {k: x for k, x in v["criterios"].items() if x["resultado"] not in ("cumple", "no_aplica")}
    na = [k for k, x in v["criterios"].items() if x["resultado"] == "no_aplica"]
    print(f"Verificador: {r['estado']} en la ronda {r['intentos']}"
          + (f" · no aplica: {', '.join(na)}" if na else ""))
    if v["motivo"]:
        print(f"Motivo: {v['motivo']}")
    for k, x in (v["criterios"].items() if criterios else malos.items()):
        print(f"  - {k}: {x['resultado']} — {x['justificacion']}")

    rechazos = [l for l in log if l["task_id"] == r["task_id"] and l["tarea"] == "verificador"
                and l["resultado"].startswith("rechazado")]
    errores = [l for l in log if l["task_id"] == r["task_id"] and l["tarea"] == "generador"
               and l["resultado"].startswith("errores")]
    if rechazos or errores:
        print(SUB)
        print("Historia del caso:")
        for l in sorted(errores + rechazos, key=lambda l: (l["intento"], l["tarea"] == "verificador", l["correccion"])):
            quien = "código" if l["tarea"] == "generador" else "verificador"
            print(f"  ronda {l['intento']}, {quien}: {l['resultado'][:300]}")


def show(r: dict, log: list[dict], catalog: dict, criterios: bool) -> None:
    print(RULE)
    print(f"{r['task_id']} · conjunto {r['conjunto']} · {r['situacion']} · idioma {r['idioma']} · "
          f"software {software_de(r)}")
    s = r["semilla"]
    origen = f"{s['documento']}" + (f" L{s['lineas'][0]}-L{s['lineas'][1]}" if s.get("lineas") else "")
    print(f"Semilla: {s['tipo_semilla']}{' (dato ausente)' if s.get('dato_ausente') else ''} · {origen}")
    print(RULE)
    show_conversation(r)
    show_citations(r, catalog)
    show_case(r, log, criterios)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--conjunto", choices=SETS)
    p.add_argument("--situacion", choices=SITUACIONES)
    p.add_argument("--idioma", choices=["es", "en"])
    p.add_argument("--software")
    p.add_argument("--tipo", choices=TIPOS)
    p.add_argument("--rechazados", action="store_true")
    p.add_argument("--buscar")
    p.add_argument("--id")
    p.add_argument("-n", type=int, default=1)
    p.add_argument("--seed", type=int)
    p.add_argument("--criterios", action="store_true")
    p.add_argument("--omitidos", action="store_true")
    args = p.parse_args()

    if not (FASE3 / "candidatos.jsonl").exists():
        print("[error] Falta data/fase3/candidatos.jsonl. Ejecuta antes: python -m src.fase3.run")
        return 1

    if args.omitidos:
        cov = json.loads((FASE3 / "coverage_report.json").read_text(encoding="utf-8"))
        rows = [o for o in cov["omitidos"] + cov["errores"]
                if (not args.conjunto or o["task_id"].startswith(args.conjunto + "-"))
                and (not args.situacion or f"-{args.situacion}-" in o["task_id"])]
        for o in rows:
            print(f"- {o['task_id']}\n{indent(textwrap.fill(o['motivo'], 76))}\n")
        print(f"({len(rows)} {'tarea omitida' if len(rows) == 1 else 'tareas omitidas'})")
        return 0

    rows = read_jsonl(FASE3 / "candidatos.jsonl")
    log = read_jsonl(FASE3 / "generation_log.jsonl")
    if args.id:
        rows = [r for r in rows if r["task_id"] == args.id]
        if not rows:
            print(f"[error] No hay ningún candidato {args.id} (¿está omitido? prueba --omitidos).")
            return 1
    else:
        rechazados = {l["task_id"] for l in log if l["tarea"] == "verificador" and l["resultado"].startswith("rechazado")}
        q = (args.buscar or "").lower()
        rows = [r for r in rows
                if (not args.conjunto or r["conjunto"] == args.conjunto)
                and (not args.situacion or r["situacion"] == args.situacion)
                and (not args.idioma or r["idioma"] == args.idioma)
                and (not args.software or args.software.lower() in software_de(r).lower())
                and (not args.tipo or args.tipo in r["caso"]["tipo_evidencia"])
                and (not args.rechazados or r["task_id"] in rechazados)
                and (not q or q in r["caso"]["pregunta"].lower() or q in r["caso"]["reference_answer"].lower())]
        if not rows:
            print("No hay candidatos con esos filtros.")
            return 0

    catalog = {d["id"]: d for d in read_jsonl(CATALOG)}
    total = len(rows)
    picked = random.Random(args.seed).sample(rows, min(args.n, total))
    for r in picked:
        show(r, log, catalog, args.criterios)
    print(RULE)
    if not args.id:
        print(f"Se mostraron {len(picked)} de {total} candidatos que cumplen los filtros.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
