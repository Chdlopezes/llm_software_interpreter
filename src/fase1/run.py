"""Ejecuta toda la fase 1. Determinista: no llama a ningún LLM.

Uso, desde la raíz del repositorio (después de terminar la fase 0):
    python -m src.fase1.run

Pasos:
    1. catalog            data/fase1/catalogo.jsonl
    2. restrictions       data/fase1/restricciones.jsonl y huecos.jsonl
    3. tool               data/fase1/llamadas.jsonl
    4. reference_examples data/fase1/ejemplos_referencia.jsonl (validados contra el contrato)
    5. report             reports/fase1/estadisticas.md
"""

from __future__ import annotations

import sys

from src.fase0.label import FASE0, ROOT
from src.fase1 import catalog, reference_examples, report, restrictions, tool


def main() -> int:
    if not (FASE0 / "section_status.jsonl").exists():
        print("[error] Falta data/fase0/section_status.jsonl. Termina antes la fase 0 "
              "(python -m src.fase0.run y python -m src.fase0.finalize).")
        return 1
    for step in (catalog, restrictions, tool, reference_examples):
        step.main()
    report.write_report()
    print(f"Reporte → {report.REPORT_PATH.relative_to(ROOT)}")
    print("Fase 1 terminada. Para comprobar que el resultado es el entregado: git status --short data/ reports/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
