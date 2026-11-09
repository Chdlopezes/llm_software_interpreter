"""Fase 0: ejecuta toda la auditoría hasta generar el CSV de revisión humana.

    python -m src.fase0.run

Pasos:
    1. Inventario, partición en secciones y chequeos automáticos (sin LLM).
    2-3. El LLM A clasifica cada sección; el código valida su respuesta.
    4. El LLM B valida cada clasificación de A; el código valida su respuesta.
    5. Escribe data/fase0/human_review.csv con las secciones en las que A y B
       dan estados distintos.

Después, rellena la columna `decision` del CSV (A o B) y ejecuta:

    python -m src.fase0.finalize

Las respuestas de los LLM se guardan en data/cache/fase0/. Si se vuelve a ejecutar
sin cambios, se reutilizan y no se llama a ningún LLM.
"""

import sys

from src.fase0 import extract, label
from src.fase0.finalize import REVIEW_PATH, prepare_review
from src.fase0.label import ROOT


def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def main() -> int:
    step("Paso 1: inventario, secciones y chequeos automáticos")
    if extract.main() != 0:
        return 1
    step("Pasos 2 y 3: el LLM A clasifica cada sección")
    if label.run("A") != 0:
        return 1
    label.STATS.update(cache=0, llm=0)
    step("Paso 4: el LLM B valida cada clasificación de A")
    if label.run("B") != 0:
        return 1
    step("Paso 5: cola de revisión humana")
    n = prepare_review()
    path = REVIEW_PATH.relative_to(ROOT)
    print(f"{n} secciones en las que A y B dan estados distintos, en {path}")
    print("\nSiguiente paso:")
    print(f"  1. Abre {path} y escribe A o B en la columna `decision` de cada fila.")
    print("     Las filas que dejes vacías se completan por defecto: gana el modelo que eligió")
    print("     'parcial'; si ninguno, el que eligió 'usable'.")
    print("  2. Ejecuta: python -m src.fase0.finalize")
    return 0


if __name__ == "__main__":
    sys.exit(main())
