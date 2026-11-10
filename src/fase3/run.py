"""Ejecuta la fase 3: genera y verifica los candidatos de los tres conjuntos.

Uso, desde la raíz del repositorio (después de la fase 2):
    python -m src.fase3.run --piloto        # 1 caso por situación de train → data/fase3/piloto/
    python -m src.fase3.run                 # todas las tareas → data/fase3/
    python -m src.fase3.run --solo-cache    # reproduce desde la caché, sin llamar a ningún LLM

Opciones para pruebas (escriben en data/fase3/parcial/): --conjunto, --situacion, --limite.
Las llamadas ya hechas se reutilizan desde data/fase3/cache/, así que el piloto no se
repite en la corrida completa.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.fase0.label import ROOT, read_jsonl, write_jsonl
from src.fase2.split import SETS, SPLITS_PATH
from src.fase3 import generate, report, tasks
from src.llm import LLMConfig, LLMError, get_config


def select(all_tasks: list[dict], args) -> tuple[list[dict], str]:
    if args.piloto:
        return [t for t in all_tasks if t["conjunto"] == "train" and t["task_id"].endswith("-001")], "piloto"
    sel = [t for t in all_tasks
           if (not args.conjunto or t["conjunto"] == args.conjunto)
           and (not args.situacion or t["situacion"] == args.situacion)]
    if args.limite:
        sel = sel[:args.limite]
    partial = args.conjunto or args.situacion or args.limite
    return sel, ("parcial" if partial else "")


def configs(solo_cache: bool):
    """Modelos del generador y del verificador. Con --solo-cache se usan los que produjeron las
    salidas entregadas (registrados en generation_log.jsonl), no los del .env: la clave de la
    caché incluye el modelo, y así se reproduce sin depender de la configuración local."""
    if solo_cache:
        log_path = generate.FASE3 / "generation_log.jsonl"
        if not log_path.exists():
            raise SystemExit("[error] --solo-cache necesita data/fase3/generation_log.jsonl.")
        used = {l["tarea"]: l for l in read_jsonl(log_path)}
        return tuple(LLMConfig(tarea=t, backend=used[t]["backend"], model=used[t]["modelo"])
                     for t in ("generador", "verificador"))
    try:
        gen, ver = get_config("generador"), get_config("verificador")
    except LLMError as e:
        raise SystemExit(f"[error] {e}")
    if (gen.backend, gen.model) == (ver.backend, ver.model):
        raise SystemExit("[error] El verificador debe ser un modelo distinto del generador "
                         "(LLM_GENERADOR_* y LLM_VERIFICADOR_* en .env).")
    return gen, ver


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--piloto", action="store_true")
    p.add_argument("--conjunto", choices=SETS)
    p.add_argument("--situacion", choices=tasks.SITUACIONES)
    p.add_argument("--limite", type=int)
    p.add_argument("--workers", type=int, default=4, help="llamadas en paralelo (por defecto 4)")
    p.add_argument("--solo-cache", action="store_true", help="falla si falta alguna llamada en la caché")
    args = p.parse_args()

    if not SPLITS_PATH.exists():
        print("[error] Falta data/fase2/splits.json. Ejecuta antes la fase 2: python -m src.fase2.run")
        return 1
    inp = tasks.load_inputs()
    all_tasks = tasks.build(inp)
    selected, sub = select(all_tasks, args)
    cfg_gen, cfg_ver = configs(args.solo_cache)
    if cfg_gen:
        print(f"Generador: {cfg_gen.label} · Verificador: {cfg_ver.label}")
    ctx = generate.load_context(cfg_gen, cfg_ver, args.solo_cache)
    print(f"Tareas: {len(selected)} de {len(all_tasks)} · {args.workers} en paralelo")

    out = generate.run_tasks(selected, ctx, args.workers)
    results, log = out["resultados"], out["log"]
    for r in results:
        if r["estado"] not in ("verificado", "revisar"):
            print(f"  {r['task_id']}: {r['estado']} — {r['motivo'][:160]}")
    plan = tasks.resumen(selected, inp)
    cov = report.coverage(results, log, plan)
    verifications = [l["veredicto"] for l in log if l["tarea"] == "verificador"]

    out_dir = generate.FASE3 / sub if sub else generate.FASE3
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = [r for r in results if r["estado"] in ("verificado", "revisar")]
    write_jsonl(out_dir / "candidatos.jsonl", candidates)
    write_jsonl(out_dir / "generation_log.jsonl", log)
    (out_dir / "coverage_report.json").write_text(json.dumps(cov, ensure_ascii=False, indent=1) + "\n",
                                                  encoding="utf-8")
    report_path = ROOT / "reports" / "fase3" / (f"{sub}.md" if sub else "estadisticas.md")
    report.write_report(report_path, results, cov, verifications)

    nuevas = out["nuevas"]
    estados = {e: sum(r["estado"] == e for r in results) for e in report.ESTADOS}
    print(f"Llamadas nuevas al LLM: {nuevas} · " + ", ".join(f"{k}: {v}" for k, v in estados.items()))
    print(f"Candidatos → {(out_dir / 'candidatos.jsonl').relative_to(ROOT)} · Reporte → {report_path.relative_to(ROOT)}")
    return 1 if estados["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
