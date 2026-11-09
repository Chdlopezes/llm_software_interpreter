"""Ejecuta toda la fase 2. Determinista: no llama a ningún LLM.

Uso, desde la raíz del repositorio (después de la fase 1):
    python -m src.fase2.run

Escribe data/fase2/splits.json y reports/fase2/estadisticas.md.
"""

from __future__ import annotations

import sys

from src.fase0.label import ROOT
from src.fase1.catalog import CATALOG_PATH
from src.fase2 import report, split


def main() -> int:
    if not CATALOG_PATH.exists():
        print("[error] Falta data/fase1/catalogo.jsonl. Ejecuta antes la fase 1: python -m src.fase1.run")
        return 1
    split.main()
    report.write_report(split.build())
    print(f"Reporte → {report.REPORT_PATH.relative_to(ROOT)}")
    print("Fase 2 terminada. Para comprobar que el resultado es el entregado: git status --short data/ reports/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
