"""Muestra una sección de la documentación al azar, con el veredicto de un LLM.

El filtro (--llm y --veredicto) se aplica sobre el LLM elegido. Para la sección
elegida muestra:
- el software, la versión, el archivo y las líneas de origen;
- el contenido original;
- el veredicto (estado y categoría) del LLM elegido y su justificación;
- el veredicto del otro LLM, si ya existe, para comparar.

Uso, desde la raíz del repositorio:
    python -m src.utils.show_section --llm A
    python -m src.utils.show_section --llm A --veredicto parcial
    python -m src.utils.show_section --llm B --veredicto no_usable --seed 7
    python -m src.utils.show_section --llm A --id price-engine-api/latest/guide/general.md#0

Opciones:
    --llm        A (clasificador) o B (validador). Obligatorio.
    --veredicto  usable, parcial, no_usable o todo (por defecto: todo).
    --seed       semilla opcional, para obtener siempre la misma sección.
    --id         muestra esa sección concreta en lugar de una al azar (útil para
                 revisar las filas de human_review.csv).

Lee data/fase0/labels_<a|b>.jsonl. Si ese archivo no existe todavía (por ejemplo,
porque solo se ejecutó el LLM sobre una versión), usa los archivos de prueba
data/fase0/labels_<a|b>_<versión>.jsonl.
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FASE0 = ROOT / "data" / "fase0"
VEREDICTOS = ["usable", "parcial", "no_usable", "todo"]
RULE = "=" * 80


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_labels(llm: str) -> list[dict]:
    r = llm.lower()
    full = FASE0 / f"labels_{r}.jsonl"
    paths = [full] if full.exists() else sorted(FASE0.glob(f"labels_{r}_*.jsonl"))
    return [row for p in paths for row in read_jsonl(p)]


def show_section(section: dict) -> None:
    print(RULE)
    print(f"Software:  {section['software']}")
    print(f"Versión:   {section['version']}")
    print(f"Sección:   {section['section_id']}")
    print(f"Archivo:   docs_raw/{section['file']} (líneas {section['line_start']}-{section['line_end']})")
    if section["title"]:
        print(f"Título:    {section['title']}")
    print(RULE)
    print(section["text"])


def show_verdict(label: dict | None, llm: str, chosen: bool) -> None:
    role = "clasificador" if llm == "A" else "validador"
    print(RULE)
    if label is None:
        print(f"LLM {llm} ({role}): sin veredicto disponible para esta sección todavía.")
        return
    tag = " — modelo elegido" if chosen else " — para comparar"
    print(f"LLM {llm} ({role}, {label.get('modelo', '?')}){tag}")
    print(f"Veredicto: {label['estado']}")
    print(f"Categoría: {label['categoria']}")
    if label.get("heredada_de"):
        print(f"Heredado de: {label['heredada_de']} (versión idéntica)")
    if llm == "A":
        print(f"Justificación: {label['justificacion']}")
        for p in label["problemas"]:
            print(f"  - {p['motivo']}: «{p['cita']}»")
            print(f"    {p['explicacion']}")
            if p["otras_secciones"]:
                print(f"    Otras secciones: {', '.join(p['otras_secciones'])}")
    else:
        print(f"¿De acuerdo con A?: {'sí' if label['de_acuerdo'] else 'no'}")
        print(f"Justificación: {label['explicacion']}")
        if label["cita"]:
            print(f"  Cita: «{label['cita']}»")
    if not label["valida"]:
        print(f"[aviso] Esta respuesta no pasó la validación por código: {'; '.join(label['errores'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--llm", required=True, type=str.upper, choices=["A", "B"])
    parser.add_argument("--veredicto", default="todo", choices=VEREDICTOS)
    parser.add_argument("--seed", type=int, help="semilla para obtener siempre la misma sección")
    parser.add_argument("--id", help="section_id concreto a mostrar (ignora --veredicto y --seed)")
    args = parser.parse_args()

    labels = load_labels(args.llm)
    if not labels:
        print(f"[error] No hay resultados del LLM {args.llm} en data/fase0/. "
              f"Ejecuta antes: python -m src.fase0.label --role {args.llm}")
        return 1
    if args.id:
        labels = [l for l in labels if l["section_id"] == args.id]
        if not labels:
            print(f"[error] El LLM {args.llm} no tiene veredicto para la sección {args.id}.")
            return 1
    elif args.veredicto != "todo":
        labels = [l for l in labels if l["estado"] == args.veredicto]
        if not labels:
            print(f"No hay secciones con veredicto '{args.veredicto}' para el LLM {args.llm}.")
            return 0

    sections = {s["section_id"]: s for s in read_jsonl(FASE0 / "sections.jsonl")}
    label = random.Random(args.seed).choice(labels)
    other = "B" if args.llm == "A" else "A"
    other_label = next((l for l in load_labels(other) if l["section_id"] == label["section_id"]), None)

    show_section(sections[label["section_id"]])
    show_verdict(label, args.llm, chosen=True)
    show_verdict(other_label, other, chosen=False)
    print(RULE)
    if other_label is not None:
        same = other_label["estado"] == label["estado"]
        print(f"Comparación: {'coinciden' if same else 'NO coinciden'} en el veredicto "
              f"({args.llm}: {label['estado']}, {other}: {other_label['estado']})")
    if not args.id:
        print(f"({len(labels)} secciones con veredicto '{args.veredicto}' para el LLM {args.llm}; "
              f"se mostró una al azar)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
