"""Revisión humana de las variantes de calibración (data/fase6/calibracion/etiquetas.csv).

Para cada variante pendiente muestra la pregunta, la referencia, la variante, qué cambió el
corruptor y el texto de las líneas que cita la variante, y pide:
    c  confirmar: la variante tiene exactamente el error (o la corrección) que dice su tipo
    d  descartar: el corruptor no hizo lo que debía (pide el motivo)
    s  saltar · q  salir
Cada decisión se guarda al momento; se puede salir y retomar.

Uso: python -m src.fase6.calibracion --revisar   (o python -m src.fase6.revisar_calibracion)
"""

from __future__ import annotations

import csv
import os
import re
import sys

from src.fase0.label import read_jsonl
from src.fase1.catalog import CATALOG_PATH
from src.fase4.run import FASE4
from src.fase6 import calibracion as cal

CITA = re.compile(r"\[([^\[\]:]+):L(\d+)-L(\d+)\]")


def guardar(rows: list[dict]) -> None:
    tmp = cal.LABELS_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cal.LABEL_FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, cal.LABELS_PATH)


def mostrar(v: dict, row: dict, catalog: dict) -> None:
    caso = row["caso"]
    print("=" * 80)
    print(f"{v['id']}\nTipo: {v['tipo']} ({v['test']}) · el juez debería dar: {v['esperado']}")
    print("=" * 80)
    print("Pregunta:\n  " + caso["pregunta"])
    print("-" * 80)
    print("Referencia que verá el juez" + (" (CORROMPIDA a propósito):" if v["referencia"] else ":"))
    print("  " + (v["referencia"] or caso["reference_answer"]))
    print("-" * 80)
    print("Respuesta a juzgar:\n  " + v["respuesta"])
    print("-" * 80)
    print("Qué cambió: " + v["cambio"])
    cites = list(dict.fromkeys(CITA.findall(v["respuesta"] + " " + (v["referencia"] or ""))))
    if cites:
        print("-" * 80 + "\nLíneas citadas:")
        for doc, a, b in cites:
            lines = catalog[doc]["contenido"].split("\n")[int(a) - 1:int(b)] if doc in catalog else ["(no existe)"]
            print(f"  [{doc}:L{a}-L{b}]")
            for i, line in enumerate(lines[:8], int(a)):
                print(f"  {i:4d}| {line}")


def main() -> int:
    if not cal.LABELS_PATH.exists():
        print("[error] Falta etiquetas.csv. Ejecuta antes: python -m src.fase6.calibracion --variantes")
        return 1
    with cal.LABELS_PATH.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    vs = {v["id"]: v for v in read_jsonl(cal.CAL / "variantes.jsonl")}
    casos = {r["id"]: r for n in ("train", "validation") for r in read_jsonl(FASE4 / f"{n}.jsonl")}
    catalog = {d["id"]: d for d in read_jsonl(CATALOG_PATH)}
    pendientes = [r for r in rows if not r["decision"].strip()]
    for i, r in enumerate(pendientes, 1):
        v = vs[r["id"]]
        mostrar(v, casos[v["caso"]], catalog)
        print("=" * 80 + f"\nVariante {i} de {len(pendientes)} · [c] confirmar · [d] descartar · [s] saltar · [q] salir")
        try:
            op = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            op = "q"
        if op == "q":
            break
        if op == "c":
            r["decision"] = "confirmar"
        elif op == "d":
            motivo = input("Motivo (obligatorio): ").strip()
            if not motivo:
                continue
            r["decision"], r["comentario"] = "descartar", motivo
        else:
            continue
        guardar(rows)
    hechas = sum(bool(r["decision"].strip()) for r in rows)
    print(f"\nDecididas: {hechas}/{len(rows)}. Para recalcular: python -m src.fase6.calibracion --juzgar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
