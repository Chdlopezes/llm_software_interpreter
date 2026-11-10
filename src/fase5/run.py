"""Ejecuta la fase 5: comprueba el diseño del experimento y prepara las entradas de inferencia.

Uso, desde la raíz del repositorio (después de la fase 4):
    python -m src.fase5.run

No entrena ningún modelo. Hace, de forma determinista:
1. Entradas de inferencia de validation y test: cada conversación cortada justo después de la
   pregunta del usuario (sistema, historial y pregunta). Es lo único que verán B0, E1 y E2; la
   llamada a la herramienta la tiene que hacer el modelo, y su salida la pone el orquestador.
2. Datos y presupuesto de cada experimento: qué conversaciones de train usa, cuántos pasos,
   cuántos ejemplos y tokens ve. E2 tiene menos conversaciones y, con los mismos pasos que E1,
   más épocas: el reporte lo hace explícito.
3. Controles del diseño (T5.1 paridad, T5.2 contrato de entrada, T5.4 presupuesto, T5.5 test
   reservado). Si alguno falla, el script termina con error.

Salidas: data/fase5/entradas_validation.jsonl, entradas_test.jsonl, experimentos.json y
data/reportes/fase5/estadisticas.md.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

import yaml

from src.fase0.label import ROOT, read_jsonl, write_jsonl
from src.fase0.report import table
from src.fase1.validate import CONTRACT
from src.fase3.tasks import SITUACIONES
from src.fase4.run import FASE4

FASE5 = ROOT / "data" / "fase5"
CONFIG_PATH = Path(__file__).parent / "experimento.yaml"
EVAL_SETS = ("validation", "test")
# Lo que nunca debe llegar al modelo en inferencia (T5.2).
PROHIBIDO = ("reference_answer", "answer_checks", "expected_tool", "expected_document_ids", "procedencia",
             "restricciones", "situacion")


def load_config(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def entrada(row: dict) -> dict:
    """La conversación hasta la última pregunta del usuario, inclusive."""
    msgs = row["messages"]
    last_user = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    return {"id": row["id"], "conjunto": row["conjunto"], "messages": msgs[:last_user + 1], "tools": row["tools"]}


def errores_entrada(e: dict, row: dict) -> list[str]:
    """T5.2: contexto y pregunta presentes; referencia, etiquetas y criterios ausentes."""
    errors = []
    msgs = e["messages"]
    if msgs[0]["role"] != "system" or msgs[0]["content"] != (CONTRACT / "system_prompt.md").read_text(encoding="utf-8").strip():
        errors.append("el primer mensaje no es el prompt de sistema del contrato")
    if msgs[-1]["role"] != "user" or msgs[-1]["content"] != row["caso"]["pregunta"]:
        errors.append("el último mensaje no es la pregunta del caso")
    if any(m["role"] == "tool" or m.get("tool_calls") for m in msgs):
        errors.append("la entrada incluye una llamada o una salida de la herramienta")
    if msgs != row["messages"][:len(msgs)]:
        errors.append("la entrada no es un prefijo de la conversación de referencia")
    texto = json.dumps(e, ensure_ascii=False)
    if row["caso"]["reference_answer"] in texto:
        errors.append("la entrada contiene la respuesta de referencia")
    if any(c in texto for c in row["caso"]["answer_checks"]):
        errors.append("la entrada contiene un answer_check")
    if set(e) - {"id", "conjunto", "messages", "tools"} or any(k in texto for k in (f'"{p}"' for p in PROHIBIDO)):
        errors.append("la entrada contiene metadatos del caso")
    return errors


def presupuesto(cfg: dict, train: list[dict]) -> dict:
    """Datos, pasos, épocas, ejemplos y tokens supervisados de cada experimento con entrenamiento."""
    t = cfg["entrenamiento"]
    batch = t["batch_por_dispositivo"] * t["acumulacion_gradiente"]
    out = {}
    for name, exp in cfg["experimentos"].items():
        if not exp["entrenamiento"]:
            out[name] = None
            continue
        excl = set(exp["entrenamiento"]["situaciones_excluidas"])
        rows = [r for r in train if r["situacion"] not in excl]
        out[name] = {"conversaciones": len(rows), "ids": [r["id"] for r in rows],
                     "situaciones": {s: sum(r["situacion"] == s for r in rows) for s in SITUACIONES},
                     "tokens_supervisados_por_conversacion": sum(r["tokens_supervisados"] for r in rows) / len(rows),
                     "tokens_por_conversacion": sum(r["tokens"] for r in rows) / len(rows)}
    e1 = out["E1"]
    e1["epocas"] = t["epocas_E1"]
    e1["ejemplos_vistos"] = e1["conversaciones"] * e1["epocas"]
    for name, v in out.items():
        if v is None:
            continue
        if name != "E1":
            # «mismos_pasos»: ve el mismo número de ejemplos que E1, repartido en más épocas.
            v["ejemplos_vistos"] = e1["ejemplos_vistos"]
            v["epocas"] = round(v["ejemplos_vistos"] / v["conversaciones"], 2)
        v["batch_efectivo"] = batch
        v["pasos"] = math.ceil(v["ejemplos_vistos"] / batch)
        v["tokens_supervisados_vistos"] = round(v["tokens_supervisados_por_conversacion"] * v["ejemplos_vistos"])
        v["tokens_vistos"] = round(v["tokens_por_conversacion"] * v["ejemplos_vistos"])
    return out


def errores_diseno(cfg: dict, budget: dict, train: list[dict]) -> list[str]:
    errors = []
    # T5.1: la inferencia es un único bloque compartido; ningún experimento la redefine.
    for name, exp in cfg["experimentos"].items():
        if set(exp) - {"descripcion", "entrenamiento"}:
            errors.append(f"T5.1: {name} redefine algo más que su entrenamiento: {sorted(set(exp) - {'descripcion', 'entrenamiento'})}")
    # T5.4: E2 solo cambia los datos; el resto del entrenamiento es el mismo bloque.
    if budget["E2"]["pasos"] != budget["E1"]["pasos"]:
        errors.append("T5.4: E2 no tiene los mismos pasos que E1")
    if max(r["tokens"] for r in train) > cfg["entrenamiento"]["longitud_maxima"]:
        errors.append("la conversación más larga de train no cabe en la longitud máxima de entrenamiento")
    # T5.5: se elige con validation; test solo al cierre.
    if cfg["seleccion"]["conjunto"] != "validation":
        errors.append("T5.5: la selección debe hacerse con validation")
    return errors


def main() -> int:
    if not all((FASE4 / f"{n}.jsonl").exists() for n in ("train",) + EVAL_SETS):
        print("[error] Faltan los datasets de la fase 4. Ejecuta antes: python -m src.fase4.run")
        return 1
    cfg = load_config()
    data = {n: read_jsonl(FASE4 / f"{n}.jsonl") for n in ("train",) + EVAL_SETS}

    errors = []
    FASE5.mkdir(parents=True, exist_ok=True)
    for n in EVAL_SETS:
        entries = [entrada(r) for r in data[n]]
        for e, r in zip(entries, data[n]):
            errors += [f"T5.2 {r['id']}: {x}" for x in errores_entrada(e, r)]
        write_jsonl(FASE5 / f"entradas_{n}.jsonl", entries)

    budget = presupuesto(cfg, data["train"])
    errors += errores_diseno(cfg, budget, data["train"])
    (FASE5 / "experimentos.json").write_text(json.dumps({"config": cfg, "presupuesto": budget},
                                                        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_report(ROOT / "data" / "reportes" / "fase5" / "estadisticas.md", cfg, budget, data)

    for name in ("E1", "E2"):
        b = budget[name]
        print(f"{name}: {b['conversaciones']} conversaciones · {b['epocas']} épocas · {b['pasos']} pasos · "
              f"{b['tokens_supervisados_vistos']} tokens supervisados vistos")
    print(f"Entradas de inferencia → data/fase5/entradas_validation.jsonl ({len(data['validation'])}), "
          f"entradas_test.jsonl ({len(data['test'])}) · Reporte → data/reportes/fase5/estadisticas.md")
    if errors:
        print("[error] El diseño no pasa los controles:")
        print("\n".join(f"  - {e}" for e in errors))
        return 1
    print("Controles del diseño (T5.1, T5.2, T5.4, T5.5): ok")
    return 0


def write_report(path: Path, cfg: dict, budget: dict, data: dict) -> None:
    out = ["# Fase 5 — Estadísticas del diseño", "",
           "Generado por `python -m src.fase5.run`. No se ha entrenado ningún modelo: las cifras describen "
           "los datos y el presupuesto de cada experimento.", "",
           "## 1. Experimentos", ""]
    rows = []
    for name in ("B0", "E1", "E2"):
        b = budget[name]
        if b is None:
            rows.append([name, "—", "—", "—", "—", "—"])
        else:
            rows.append([name, b["conversaciones"], b["epocas"], b["pasos"], b["ejemplos_vistos"],
                         b["tokens_supervisados_vistos"]])
    out += table(["Experimento", "Conversaciones", "Épocas", "Pasos", "Ejemplos vistos", "Tokens supervisados vistos"],
                 rows, align_right_from=1)
    out += ["", "## 2. Situaciones en el entrenamiento", ""]
    out += table(["Situación", "E1", "E2"], [[s, budget["E1"]["situaciones"][s], budget["E2"]["situaciones"][s]]
                                             for s in SITUACIONES], align_right_from=1)
    out += ["", "## 3. Entradas de inferencia", ""]
    for n in EVAL_SETS:
        c = Counter(len(entrada(r)["messages"]) for r in data[n])
        out += [f"- `{n}`: {len(data[n])} entradas ({', '.join(f'{v} con {k} mensajes' for k, v in sorted(c.items()))})."]
    out += ["", "Cada entrada termina en la pregunta del usuario. No incluye la llamada esperada, los documentos "
            "esperados, la respuesta de referencia ni los `answer_checks`.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
