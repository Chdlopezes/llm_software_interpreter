"""Revisión humana interactiva de data/fase4/revision_humana.csv.

Muestra cada caso pendiente (la conversación, el texto de cada cita, los answer_checks y el
veredicto del verificador) y pide una decisión:

    a  aprobar
    r  rechazar (pide un comentario con el motivo)
    s  saltar (queda pendiente)
    v  ver otra vez el caso con la justificación de todos los criterios del verificador
    q  salir

Cada decisión se guarda en el CSV en el momento, así que se puede salir cuando se quiera y
retomar después: la siguiente vez empieza por el primer caso pendiente.

Uso, desde la raíz del repositorio (después de python -m src.fase4.run):
    python -m src.fase4.revisar --conjunto test
    python -m src.fase4.revisar --conjunto validation --situacion sin_evidencia
    python -m src.fase4.revisar --id test-contradiccion-002      # revisar (o cambiar) un caso concreto
    python -m src.fase4.revisar --todos                          # también los ya decididos

Al terminar, python -m src.fase4.run aplica las decisiones a los datasets.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter

from src.fase0.label import read_jsonl
from src.fase1.catalog import CATALOG_PATH
from src.fase3.generate import FASE3
from src.fase3.tasks import SITUACIONES
from src.fase4.run import REVIEW_FIELDS, REVIEW_PATH, REVIEW_SETS
from src.utils.show_example import show

OPCIONES = "[a] aprobar · [r] rechazar · [s] saltar · [v] ver todos los criterios · [q] salir"


def load_rows(path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def save_rows(rows: list[dict], path) -> None:
    """Escribe en un archivo temporal y lo reemplaza: si se corta a mitad, el CSV no queda roto."""
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in REVIEW_FIELDS} for r in rows)
    os.replace(tmp, path)


def decidir(rows: list[dict], task_id: str, decision: str, comentario: str = "") -> None:
    row = next(r for r in rows if r["task_id"] == task_id)
    row["decision"], row["comentario"] = decision, comentario.strip()


def seleccion(rows: list[dict], conjunto: str | None, situacion: str | None, task_id: str | None,
              todos: bool) -> list[dict]:
    if task_id:
        return [r for r in rows if r["task_id"] == task_id]
    return [r for r in rows
            if (not conjunto or r["conjunto"] == conjunto)
            and (not situacion or r["situacion"] == situacion)
            and (todos or not r["decision"].strip())]


def resumen(rows: list[dict]) -> str:
    c = Counter(r["decision"].strip().lower() or "pendiente" for r in rows)
    return f"aprobados: {c['aprobar']} · rechazados: {c['rechazar']} · pendientes: {c['pendiente']}"


def limpiar() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--conjunto", choices=REVIEW_SETS)
    p.add_argument("--situacion", choices=SITUACIONES)
    p.add_argument("--id", help="un caso concreto, aunque ya tenga decisión")
    p.add_argument("--todos", action="store_true", help="incluye los casos ya decididos, para cambiarlos")
    args = p.parse_args()

    if not REVIEW_PATH.exists():
        print("[error] Falta data/fase4/revision_humana.csv. Ejecuta antes: python -m src.fase4.run")
        return 1
    rows = load_rows(REVIEW_PATH)
    todo = seleccion(rows, args.conjunto, args.situacion, args.id, args.todos)
    if not todo:
        print("No hay casos que revisar con esos filtros. " + resumen(rows))
        return 0

    candidates = {r["task_id"]: r for r in read_jsonl(FASE3 / "candidatos.jsonl")}
    log = read_jsonl(FASE3 / "generation_log.jsonl")
    catalog = {d["id"]: d for d in read_jsonl(CATALOG_PATH)}

    for i, row in enumerate(todo, 1):
        criterios = False
        while True:
            limpiar()
            show(candidates[row["task_id"]], log, catalog, criterios)
            actual = row["decision"].strip() or "pendiente"
            print("=" * 80)
            print(f"Caso {i} de {len(todo)} · decisión actual: {actual}"
                  + (f" ({row['comentario']})" if row["comentario"] else ""))
            print(OPCIONES)
            try:
                op = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                op = "q"
            if op == "v":
                criterios = True
                continue
            if op == "a":
                decidir(rows, row["task_id"], "aprobar")
            elif op == "r":
                comentario = ""
                while not comentario.strip():
                    try:
                        comentario = input("Motivo del rechazo (obligatorio): ")
                    except (EOFError, KeyboardInterrupt):
                        comentario = ""
                        break
                if not comentario.strip():
                    print("Sin motivo no se rechaza; el caso sigue igual.")
                    continue
                decidir(rows, row["task_id"], "rechazar", comentario)
            elif op == "s":
                break
            elif op == "q":
                print("\nDecisiones guardadas. " + resumen(rows))
                print("Para aplicarlas a los datasets: python -m src.fase4.run")
                return 0
            else:
                continue
            save_rows(rows, REVIEW_PATH)
            break

    print("\nNo quedan casos en esta selección. " + resumen(rows))
    print("Para aplicar las decisiones a los datasets: python -m src.fase4.run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
