"""Fase 6, evaluación de las respuestas de un modelo (B0, E1 o E2).

Uso, desde la raíz del repositorio:
    python -m src.fase6.evaluar --predicciones runs/E1/predicciones_validation.jsonl --experimento E1
    python -m src.fase6.evaluar --predicciones ... --experimento E1 --conjunto test --final

Cada línea de predicciones es {"id": <caso>, "mensajes": [...]}: los mensajes que generó el modelo
después de la entrada de la fase 5, con las llamadas a la herramienta y sus salidas (las pone el
orquestador) y la respuesta final.

Para cada caso:
1. Controles por código (deterministas):
   - 8.1 llamada: si llamó a la herramienta cuando debía, con los argumentos esperados;
   - 8.2 documentos: si recibió los documentos esperados (se recalculan con el catálogo, no se
     toman de la predicción);
   - citas: formato, documento recibido, rango y líneas no citables (la misma regla del contrato).
2. Juez (LLM_JUEZ_*): juicio por criterio, por afirmación y por cita; la aprobación la decide
   `judge.veredicto`.
3. Métricas de la guía, con numerador y denominador, en total y por situación.

`test` solo se evalúa con --final: la configuración se elige con validation (fase 5).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from src.fase0.label import ROOT, read_jsonl, write_jsonl
from src.fase0.report import table
from src.fase1.catalog import CATALOG_PATH
from src.fase1.restrictions import RESTRICTIONS_PATH
from src.fase1.tool import TOOL_NAME, obtener_documentacion
from src.fase1.validate import errores_de_citas
from src.fase3.generate import TaskCache
from src.fase3.tasks import SITUACIONES
from src.fase4.run import FASE4
from src.fase5.run import load_config
from src.fase6 import judge
from src.llm import LLMError

FASE6 = ROOT / "data" / "fase6"
CACHE_JUEZ = FASE6 / "cache" / "juez"
INSUFICIENTES = {"sin_evidencia", "sin_documentos"}
RESPONDIBLES = {"version_explicita", "sin_version", "software_en_historial", "en_que_version",
                "comparacion_versiones", "contradiccion"}


def normalizar(args: dict) -> dict:
    """El parser de Qwen devuelve null como None, pero un modelo puede escribir el texto «null»."""
    return {k: (None if v in (None, "null") else v) for k, v in args.items()}


def analizar(mensajes: list[dict], caso: dict, catalog: list[dict], restrictions: list[dict],
             max_llamadas: int) -> dict:
    """Controles por código de una respuesta. Devuelve también lo que recibió el modelo, para el juez."""
    calls = [c["function"] for m in mensajes if m["role"] == "assistant" for c in m.get("tool_calls") or []]
    finales = [m for m in mensajes if m["role"] == "assistant" and not m.get("tool_calls")]
    respuesta = finales[-1]["content"] if finales else ""
    llamadas, docs = [], {}
    for c in calls:
        args = normalizar(c["arguments"]) if c["name"] == TOOL_NAME else c["arguments"]
        if c["name"] == TOOL_NAME and set(args) == {"software", "version"}:
            out = obtener_documentacion(args["software"], args["version"], catalog)
            for d in out["documentos"]:
                docs.setdefault(d["id"], d)
            status = out["status"]
        else:
            status = "llamada_invalida"
        llamadas.append({"name": c["name"], "arguments": args, "status": status})

    esperada = caso["expected_tool"]
    if esperada is None:
        llamada_ok = not llamadas
    else:
        llamada_ok = (0 < len(llamadas) <= max_llamadas and llamadas[0]["name"] == esperada["name"]
                      and llamadas[0]["arguments"] == esperada["arguments"])
    documentos_ok = sorted(docs) == sorted(caso["expected_document_ids"])
    citas = errores_de_citas(respuesta, set(docs), caso["situacion"], catalog, restrictions) if respuesta else \
        ["no hay respuesta final"]
    return {"respuesta": respuesta, "llamadas": llamadas, "documentos": list(docs.values()),
            "llamada_ok": llamada_ok, "documentos_ok": documentos_ok, "errores_citas": citas}


def juzgar(caso: dict, analisis: dict, restrictions: list[dict], cfg, solo_cache: bool, clave: str,
           referencia: str | None = None, orden: list[int] | None = None) -> tuple[dict, int]:
    """Una llamada al juez (con caché). Devuelve (juicio, llamadas nuevas)."""
    prompt = judge.prompt_juez(caso, analisis["respuesta"], analisis["llamadas"], analisis["documentos"],
                               restrictions, referencia=referencia, orden=orden)
    cache = TaskCache(clave, cache_dir=CACHE_JUEZ)
    e = cache.call("juez", judge.system_juez(), prompt, judge.JUEZ_SCHEMA, cfg, solo_cache)
    cache.save()
    errs = judge.errores_juicio(e["respuesta"], caso)
    if errs:
        raise LLMError("; ".join(errs))
    return e["respuesta"], cache.nuevas


def fraccion(num: int, den: int) -> dict:
    return {"num": num, "den": den, "valor": round(num / den, 4) if den else None}


def metricas(resultados: list[dict]) -> dict:
    """Métricas de la guía (fase 6). Los casos con incidencia de referencia quedan fuera de las del juez."""
    def calcular(rs: list[dict]) -> dict:
        jz = [r for r in rs if r["veredicto"]["estado"] != "incidencia_referencia"]
        checks = [c for r in jz for c in r["juicio"]["checks"]]
        tecnicas = [a for r in jz for a in r["juicio"]["afirmaciones"] if a["respaldo"] != "sin_verificar"]
        citadas = [a for a in tecnicas if a["cita"]]
        tool = [r for r in rs if r["caso"]["expected_tool"] is not None]
        con_citas = [r for r in rs if r["caso"]["situacion"] not in ("falta_software", "sin_documentos")]
        insuf = [r for r in jz if r["caso"]["situacion"] in INSUFICIENTES]
        resp = [r for r in jz if r["caso"]["situacion"] in RESPONDIBLES]
        parc = [r for r in jz if r["caso"]["situacion"] == "evidencia_parcial"]
        return {
            "llamada_correcta": fraccion(sum(r["llamada_ok"] for r in rs), len(rs)),
            "documentos_correctos": fraccion(sum(r["documentos_ok"] for r in tool), len(tool)),
            "citas_validas": fraccion(sum(not r["errores_citas"] for r in con_citas), len(con_citas)),
            "correccion_completitud": fraccion(sum(c["resultado"] == "cumple" for c in checks), len(checks)),
            "respaldo_citas": fraccion(sum(a["cita_respalda"] and a["respaldo"] == "respaldada" for a in citadas),
                                       len(citadas)),
            "cobertura_citas": fraccion(sum(a["cita_respalda"] and a["respaldo"] == "respaldada" for a in tecnicas),
                                        len(tecnicas)),
            "abstencion_correcta": fraccion(sum(r["juicio"]["abstencion"] == "correcta" and not any(
                a["respaldo"] in ("no_respaldada", "contradicha") for a in r["juicio"]["afirmaciones"])
                for r in insuf), len(insuf)),
            "abstencion_indebida": fraccion(sum(r["juicio"]["abstencion"] == "indebida" for r in resp), len(resp)),
            "parcial_correcta": fraccion(sum(r["veredicto"]["estado"] == "aprueba" for r in parc), len(parc)),
            "aprobados": fraccion(sum(r["veredicto"]["estado"] == "aprueba" and r["llamada_ok"] and not r["errores_citas"]
                                      for r in jz), len(jz)),
            "incidencias_referencia": len(rs) - len(jz),
        }
    by_sit = defaultdict(list)
    for r in resultados:
        by_sit[r["caso"]["situacion"]].append(r)
    etiquetas = defaultdict(int)
    for r in resultados:
        for t in r["juicio"]["etiquetas_error"]:
            etiquetas[t] += 1
    return {"total": calcular(resultados),
            "por_situacion": {s: calcular(by_sit[s]) for s in SITUACIONES if by_sit[s]},
            "etiquetas_error": dict(sorted(etiquetas.items(), key=lambda x: -x[1]))}


def fmt(m: dict) -> str:
    return "—" if m["valor"] is None else f"{m['valor']:.0%} ({m['num']}/{m['den']})"


def write_report(path: Path, experimento: str, conjunto: str, met: dict) -> None:
    nombres = ["llamada_correcta", "documentos_correctos", "citas_validas", "correccion_completitud",
               "respaldo_citas", "cobertura_citas", "abstencion_correcta", "abstencion_indebida",
               "parcial_correcta", "aprobados"]
    t = met["total"]
    out = [f"# Evaluación — {experimento} en `{conjunto}`", "",
           "Generado por `python -m src.fase6.evaluar`. Cada métrica con numerador y denominador; «—» = no aplica.",
           "", "## 1. Total", ""]
    out += table(["Métrica", "Valor"], [[n, fmt(t[n])] for n in nombres], align_right_from=1)
    out += ["", f"Casos con incidencia de referencia (fuera de las métricas del juez): **{t['incidencias_referencia']}**.",
            "", "## 2. Por situación", ""]
    cols = ["llamada_correcta", "documentos_correctos", "correccion_completitud", "cobertura_citas", "aprobados"]
    out += table(["Situación"] + cols, [[s] + [fmt(m[c]) for c in cols] for s, m in met["por_situacion"].items()],
                 align_right_from=1)
    if met["etiquetas_error"]:
        out += ["", "## 3. Etiquetas de error", ""]
        out += table(["Etiqueta", "Casos"], [[k, v] for k, v in met["etiquetas_error"].items()], align_right_from=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def evaluar(predicciones: list[dict], casos: dict, ctx: dict, experimento: str) -> tuple[list[dict], int]:
    resultados, nuevas = [], 0
    for p in predicciones:
        caso = casos[p["id"]]
        a = analizar(p["mensajes"], caso, ctx["catalog"], ctx["restrictions"], ctx["max_llamadas"])
        juicio, n = juzgar(caso, a, ctx["restrictions"], ctx["cfg"], ctx["solo_cache"], f"{experimento}/{p['id']}")
        nuevas += n
        resultados.append({"id": p["id"], "experimento": experimento, "caso": caso, **a,
                           "juicio": juicio, "veredicto": judge.veredicto(juicio)})
    return resultados, nuevas


def main() -> int:
    from src.llm import get_config
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--predicciones", required=True)
    p.add_argument("--experimento", required=True)
    p.add_argument("--conjunto", choices=["validation", "test"], default="validation")
    p.add_argument("--final", action="store_true", help="necesario para evaluar test (una sola vez, al cierre)")
    p.add_argument("--solo-cache", action="store_true")
    args = p.parse_args()
    if args.conjunto == "test" and not args.final:
        print("[error] test se evalúa una sola vez, con la configuración elegida en validation. Usa --final.")
        return 1
    casos = {r["id"]: r["caso"] for r in read_jsonl(FASE4 / f"{args.conjunto}.jsonl")}
    preds = read_jsonl(Path(args.predicciones))
    faltan = [x["id"] for x in preds if x["id"] not in casos]
    if faltan:
        print(f"[error] {len(faltan)} predicciones no son casos de {args.conjunto}: {faltan[:3]}")
        return 1
    ctx = {"catalog": read_jsonl(CATALOG_PATH), "restrictions": read_jsonl(RESTRICTIONS_PATH),
           "max_llamadas": load_config()["inferencia"]["max_llamadas_herramienta"],
           "cfg": None if args.solo_cache else get_config("juez"), "solo_cache": args.solo_cache}
    resultados, nuevas = evaluar(preds, casos, ctx, args.experimento)
    met = metricas(resultados)
    out = FASE6 / "evaluaciones" / args.experimento / args.conjunto
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "judgments.jsonl", [{k: v for k, v in r.items() if k not in ("caso", "documentos")}
                                         for r in resultados])
    (out / "metricas.json").write_text(json.dumps(met, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_report(ROOT / "data" / "reportes" / "fase6" / f"evaluacion_{args.experimento}_{args.conjunto}.md",
                 args.experimento, args.conjunto, met)
    print(f"{len(resultados)} casos evaluados · llamadas nuevas al juez: {nuevas} · "
          f"aprobados: {fmt(met['total']['aprobados'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
