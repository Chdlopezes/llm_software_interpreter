"""Fase 6, calibración del juez con respuestas de etiqueta conocida.

Uso, desde la raíz del repositorio:
    python -m src.fase6.calibracion --variantes            # 1. escribe las variantes (LLM_CORRUPTOR_*)
    python -m src.fase6.calibracion --revisar              # 2. una persona confirma cada variante
    python -m src.fase6.calibracion --juzgar               # 3. el juez evalúa cada variante (LLM_JUEZ_*)
    python -m src.fase6.calibracion --juzgar --estabilidad # además, repite con los criterios en otro orden (T6.8)
    python -m src.fase6.calibracion --juzgar --verificador # además, pasa las variantes por el verificador (T4.2-T4.5)
    python -m src.fase6.calibracion --piloto ...           # solo los dos primeros casos

Material: casos de validation y, para mezclar versiones, de train (validation no tiene versiones con
contenido distinto). Nunca de test. Para cada caso, varias respuestas cuya etiqueta se conoce por
construcción (tabla TIPOS). La referencia y la respuesta sin citas se construyen con código; el
resto las escribe el corruptor y una persona confirma que cada una tiene el error que debe tener
(data/fase6/calibracion/etiquetas.csv). El reporte da los resultados con todas las variantes y
solo con las confirmadas.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.fase0.label import ROOT, read_jsonl, write_jsonl
from src.fase0.report import table
from src.fase1.catalog import CATALOG_PATH
from src.fase1.restrictions import RESTRICTIONS_PATH
from src.fase1.tool import TOOL_NAME, obtener_documentacion
from src.fase1.validate import errores_de_citas
from src.fase3.generate import TaskCache, render_docs
from src.fase4.run import FASE4
from src.fase6 import judge
from src.fase6.evaluar import FASE6, juzgar
from src.llm import LLMError

CAL = FASE6 / "calibracion"
CACHE = FASE6 / "cache"
LABELS_PATH = CAL / "etiquetas.csv"
LABEL_FIELDS = ["id", "caso", "tipo", "esperado", "cambio", "decision", "comentario"]
PROMPTS = Path(__file__).parent / "prompts"
CITA = re.compile(r"\s*\[[^\[\]\s]+?:L\d+-L\d+\]")

# tipo → (veredicto esperado del programa, etiqueta de error esperada, test de la guía)
TIPOS = {
    "referencia": ("aprueba", None, "control"),
    "parafrasis": ("aprueba", None, "T6.1"),
    "hecho_falso": ("falla", "contradiccion_con_fuente", "T4.2 / T6.3"),
    "irrelevante": ("falla", "no_responde", "T4.3 / T6.2"),
    "abstencion_excesiva": ("falla", "abstencion_indebida", "T4.4 / T6.4"),
    "version_mezclada": ("falla", "version_incorrecta", "T4.5"),
    "sin_citas": ("falla", "falta_cita", "T6.6"),
    "inventa_faltante": ("falla", "afirmacion_sin_respaldo", "T6.5"),
    "elige_una": ("falla", "conflicto_no_senalado", "conflictos"),
    "referencia_defectuosa": ("incidencia_referencia", None, "T6.7"),
}
POR_SITUACION = {
    "version_explicita": ["referencia", "parafrasis", "hecho_falso", "irrelevante", "abstencion_excesiva", "sin_citas",
                          "referencia_defectuosa"],
    "sin_version": ["referencia", "parafrasis", "hecho_falso", "abstencion_excesiva", "sin_citas"],
    "software_en_historial": ["referencia", "parafrasis", "irrelevante", "abstencion_excesiva"],
    "en_que_version": ["referencia", "parafrasis", "hecho_falso"],
    "comparacion_versiones": ["referencia", "parafrasis", "hecho_falso"],
    "evidencia_parcial": ["referencia", "parafrasis", "inventa_faltante", "abstencion_excesiva", "sin_citas"],
    "sin_evidencia": ["referencia", "parafrasis", "inventa_faltante"],
    "contradiccion": ["referencia", "parafrasis", "elige_una", "referencia_defectuosa"],
}
# Casos por situación. Los de «version» salen de train (software con versiones distintas).
CUPO = {"version_explicita": 2, "sin_version": 1, "software_en_historial": 1, "en_que_version": 1,
        "comparacion_versiones": 1, "evidencia_parcial": 2, "sin_evidencia": 2, "contradiccion": 2}
CUPO_VERSIONES = 2

CORRUPTOR_SCHEMA = {"type": "object", "properties": {"respuesta": {"type": "string"}, "cambio": {"type": "string"}},
                    "required": ["respuesta", "cambio"], "additionalProperties": False}


def orden_estable(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: hashlib.sha256(r["id"].encode()).hexdigest())


def difiere(r: dict, catalog: list[dict]) -> bool:
    """La respuesta cita al menos dos versiones de un archivo cuyo contenido cambia entre ellas."""
    by_id = {d["id"]: d for d in catalog}
    docs = {d for d, _, _ in re.findall(r"\[([^\]:]+):L(\d+)-L(\d+)\]", r["caso"]["reference_answer"])}
    rutas = defaultdict(set)
    for d in docs:
        if d in by_id:
            rutas[d.split("/", 2)[2]].add(by_id[d]["sha256_original"])
    return any(len(h) > 1 for h in rutas.values())


def seleccionar(catalog: list[dict]) -> list[tuple[dict, list[str]]]:
    """[(fila de la fase 4, tipos de variante)]. Determinista."""
    val = orden_estable(read_jsonl(FASE4 / "validation.jsonl"))
    out = []
    for sit, k in CUPO.items():
        rows = [r for r in val if r["situacion"] == sit][:k]
        out += [(r, POR_SITUACION[sit]) for r in rows]
    train = orden_estable(read_jsonl(FASE4 / "train.jsonl"))
    versiones = [r for r in train if r["situacion"] in ("sin_version", "comparacion_versiones") and difiere(r, catalog)]
    out += [(r, ["referencia", "version_mezclada"]) for r in versiones[:CUPO_VERSIONES]]
    return out


def prompt_corruptor(row: dict, tipo: str, restrictions: list[dict], catalog: list[dict]) -> str:
    caso = row["caso"]
    restr = {r["id"]: r for r in restrictions}
    args = caso["expected_tool"]["arguments"]
    docs = obtener_documentacion(args["software"], args["version"], catalog)["documentos"]
    return "\n\n".join([
        f"# Transformación: {tipo}",
        "## Pregunta\n" + caso["pregunta"],
        "## Restricciones del caso\n" + ("\n".join(f"- {x['tipo']}: {x.get('descripcion', '')}"
                                                  for x in caso["restricciones"]) or "ninguna"),
        "## Respuesta de referencia\n" + caso["reference_answer"],
        "## Documentos que recibió el asistente\n" + render_docs(docs, restr),
    ])


def una_variante(row: dict, tipo: str, ctx: dict, system: str) -> tuple[dict, int]:
    ref = row["caso"]["reference_answer"]
    vid = f"{row['id']}__{tipo}"
    esperado, etiqueta, test = TIPOS[tipo]
    v = {"id": vid, "caso": row["id"], "tipo": tipo, "esperado": esperado, "etiqueta_esperada": etiqueta,
         "test": test, "respuesta": ref, "referencia": None, "cambio": ""}
    if tipo == "referencia":
        v["cambio"] = "la respuesta de referencia, sin cambios"
        return v, 0
    if tipo == "sin_citas":
        v["respuesta"] = CITA.sub("", ref)
        v["cambio"] = "la referencia sin ninguna cita"
        return v, 0
    cache = TaskCache("corruptor/" + vid, cache_dir=CACHE)
    e = cache.call("corruptor", system, prompt_corruptor(row, tipo, ctx["restrictions"], ctx["catalog"]),
                   CORRUPTOR_SCHEMA, ctx["cfg_corruptor"], ctx["solo_cache"])
    cache.save()
    if tipo == "referencia_defectuosa":
        v["referencia"] = e["respuesta"]["respuesta"]       # la respuesta evaluada es la correcta
    else:
        v["respuesta"] = e["respuesta"]["respuesta"]
    v["cambio"] = e["respuesta"]["cambio"]
    return v, cache.nuevas


def variantes(seleccion, ctx: dict, piloto: bool, workers: int = 4) -> tuple[list[dict], int]:
    system = (PROMPTS / "corruptor.md").read_text(encoding="utf-8")
    trabajo = [(row, tipo) for row, tipos in (seleccion[:2] if piloto else seleccion) for tipo in tipos]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        res = list(pool.map(lambda x: una_variante(x[0], x[1], ctx, system), trabajo))
    return [v for v, _ in res], sum(n for _, n in res)


def load_labels() -> dict[str, dict]:
    if not LABELS_PATH.exists():
        return {}
    with LABELS_PATH.open(encoding="utf-8-sig", newline="") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def write_labels(vs: list[dict]) -> None:
    prev = load_labels()
    CAL.mkdir(parents=True, exist_ok=True)
    with LABELS_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_FIELDS)
        w.writeheader()
        for v in vs:
            old = prev.get(v["id"], {})
            # Las construidas con código no necesitan confirmación.
            auto = "confirmar" if v["tipo"] in ("referencia", "sin_citas") else ""
            w.writerow({"id": v["id"], "caso": v["caso"], "tipo": v["tipo"], "esperado": v["esperado"],
                        "cambio": v["cambio"], "decision": old.get("decision", auto),
                        "comentario": old.get("comentario", "")})


def analisis_esperado(row: dict, respuesta: str, ctx: dict) -> dict:
    """Lo que habría recibido un modelo que llamó bien a la herramienta: la calibración solo varía la respuesta."""
    caso = row["caso"]
    args = caso["expected_tool"]["arguments"]
    out = obtener_documentacion(args["software"], args["version"], ctx["catalog"])
    return {"respuesta": respuesta, "documentos": out["documentos"],
            "llamadas": [{"name": TOOL_NAME, "arguments": args, "status": out["status"]}],
            "errores_citas": errores_de_citas(respuesta, {d["id"] for d in out["documentos"]}, caso["situacion"],
                                              ctx["catalog"], ctx["restrictions"])}


def juzgar_una(v: dict, rows: dict, ctx: dict, estabilidad: bool) -> tuple[dict, int]:
    row = rows[v["caso"]]
    a = analisis_esperado(row, v["respuesta"], ctx)
    r = {"id": v["id"], "tipo": v["tipo"], "esperado": v["esperado"], "etiqueta_esperada": v["etiqueta_esperada"],
         "errores_citas": a["errores_citas"]}
    nuevas = 0
    try:
        j, n = juzgar(row["caso"], a, ctx["restrictions"], ctx["cfg_juez"], ctx["solo_cache"],
                      "calibracion/" + v["id"], referencia=v["referencia"])
        nuevas += n
        r.update({"juicio": j, "obtenido": judge.veredicto(j)["estado"]})
        if estabilidad:
            orden = list(reversed(range(len(row["caso"]["answer_checks"]))))
            j2, n = juzgar(row["caso"], a, ctx["restrictions"], ctx["cfg_juez"], ctx["solo_cache"],
                           "calibracion_orden/" + v["id"], referencia=v["referencia"], orden=orden)
            nuevas += n
            r["obtenido_orden_inverso"] = judge.veredicto(j2)["estado"]
    except LLMError as err:
        r.update({"juicio": None, "obtenido": "error", "error": str(err)})
    return r, nuevas


def juzgar_variantes(vs: list[dict], rows: dict, ctx: dict, estabilidad: bool, workers: int = 4) -> tuple[list[dict], int]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        res = list(pool.map(lambda v: juzgar_una(v, rows, ctx, estabilidad), vs))
    return [r for r, _ in res], sum(n for _, n in res)


def verificar_variantes(vs: list[dict], ctx: dict) -> tuple[dict[str, str], int]:
    """T4.2-T4.5: el verificador de la fase 3 sobre las mismas variantes, como si fueran referencias candidatas.
    Grupos del mismo software, ordenados por tipo, para que en un grupo haya casos distintos."""
    from src.fase3 import generate, tasks
    plan = {t["task_id"]: t for t in tasks.build()}
    cfg = ctx["cfg_verificador"]
    if cfg is None:
        # --solo-cache: el nombre del archivo de caché depende del modelo; se usa el que quedó registrado.
        modelos = {e["modelo"] for f in (CACHE / "verificador").glob("*.json")
                   for e in json.loads(f.read_text(encoding="utf-8"))["llamadas"]}
        if len(modelos) == 1:
            from types import SimpleNamespace
            cfg = SimpleNamespace(model=modelos.pop(), backend="cache", label="cache")
    gctx = generate.load_context(None, cfg, ctx["solo_cache"])
    cands = {r["task_id"]: r for r in read_jsonl(generate.FASE3 / "candidatos.jsonl")}
    items = []
    for v in vs:
        if v["tipo"] == "referencia_defectuosa":
            continue                       # su respuesta es la correcta; no prueba nada del verificador
        task = dict(plan[v["caso"]], task_id=v["id"])
        case = dict(cands[v["caso"]]["caso"], reference_answer=v["respuesta"])
        items.append((task, {"caso": case}))
    grupos = generate.agrupar(sorted(items, key=lambda x: (x[0]["task_id"].split("__")[1], x[0]["task_id"])))
    out, nuevas = {}, 0
    for g in grupos:
        _, vers, n = generate.verificar(g, gctx, cache_dir=CACHE)     # caché propia, no la de la fase 3
        nuevas += n
        out.update({tid: generate.estado_verificacion(ver) for tid, ver in vers.items()})
    return out, nuevas


CLASES = ["aprueba", "falla", "incidencia_referencia"]


def fr(num: int, den: int) -> dict:
    return {"num": num, "den": den, "valor": round(num / den, 4) if den else None}


def resumen(juicios: list[dict], labels: dict, verif: dict | None) -> dict:
    def calcular(rs):
        ok = [r for r in rs if r["obtenido"] != "error"]
        falsos_aprobados = [r["id"] for r in ok if r["esperado"] != "aprueba" and r["obtenido"] == "aprueba"]
        falsos_rechazos = [r["id"] for r in ok if r["esperado"] == "aprueba" and r["obtenido"] != "aprueba"]
        por_tipo = {}
        for t in TIPOS:
            tr = [r for r in ok if r["tipo"] == t]
            if tr:
                por_tipo[t] = {"aciertos": sum(r["obtenido"] == r["esperado"] for r in tr), "total": len(tr),
                               "etiqueta": (sum(TIPOS[t][1] in (r["juicio"]["etiquetas_error"] or []) for r in tr)
                                            if TIPOS[t][1] else None)}
        estab = [r for r in ok if "obtenido_orden_inverso" in r]
        matriz = {e: {o: sum(r["esperado"] == e and r["obtenido"] == o for r in ok) for o in CLASES} for e in CLASES}
        con_error = [r for r in ok if r["esperado"] == "falla"]
        correctas = [r for r in ok if r["esperado"] == "aprueba"]
        aprobadas = [r for r in ok if r["obtenido"] == "aprueba"]
        binario = {
            # ¿Detecta las respuestas con error? (positivo = tiene error)
            "sensibilidad": fr(sum(r["obtenido"] == "falla" for r in con_error), len(con_error)),
            # ¿Aprueba las respuestas correctas?
            "especificidad": fr(sum(r["obtenido"] == "aprueba" for r in correctas), len(correctas)),
            # De lo que aprueba, ¿cuánto es correcto de verdad?
            "precision_aprobados": fr(sum(r["esperado"] == "aprueba" for r in aprobadas), len(aprobadas)),
        }
        return {"variantes": len(rs), "errores": len(rs) - len(ok), "matriz": matriz, "binario": binario,
                "aciertos": sum(r["obtenido"] == r["esperado"] for r in ok),
                "falsos_aprobados": falsos_aprobados, "falsos_rechazos": falsos_rechazos, "por_tipo": por_tipo,
                "estabilidad": ({"iguales": sum(r["obtenido"] == r["obtenido_orden_inverso"] for r in estab),
                                 "total": len(estab)} if estab else None)}
    confirmadas = [r for r in juicios if labels.get(r["id"], {}).get("decision", "").strip().lower() == "confirmar"]
    out = {"todas": calcular(juicios), "confirmadas": calcular(confirmadas),
           "etiquetas": dict(Counter(labels.get(r["id"], {}).get("decision", "").strip().lower() or "pendiente"
                                     for r in juicios))}
    if verif is not None:
        rs = [r for r in juicios if r["id"] in verif]
        esperado = lambda r: "verificado" if r["esperado"] == "aprueba" else "rechazado"
        out["verificador"] = {"aciertos": sum(verif[r["id"]] == esperado(r) or (esperado(r) == "verificado" and
                                                                                  verif[r["id"]] == "revisar")
                                              for r in rs), "total": len(rs),
                              "falsos_aprobados": [r["id"] for r in rs if esperado(r) == "rechazado"
                                                   and verif[r["id"]] != "rechazado"],
                              "por_tipo": {t: {"aciertos": sum(verif[r["id"]] == esperado(r) for r in rs if r["tipo"] == t),
                                               "total": sum(r["tipo"] == t for r in rs)}
                                           for t in TIPOS if any(r["tipo"] == t for r in rs)}}
    return out


# Rampa secuencial azul de la paleta de referencia (skill dataviz): de «casi cero» a «máximo».
RAMPA_CLARA = ["#f0efec", "#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
RAMPA_OSCURA = ["#2c2c2a", "#104281", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef", "#b7d3f6"]
NOMBRES = {"aprueba": "Aprueba", "falla": "Falla", "incidencia_referencia": "Incidencia ref."}


def write_matrix_svg(path: Path, matriz: dict, titulo: str) -> None:
    """Matriz de confusión como SVG sin dependencias, con modo claro y oscuro. Cada celda se colorea
    por la parte de su fila (así la diagonal se lee como tasa de acierto por clase) y lleva el número."""
    filas = [e for e in CLASES if sum(matriz[e].values())]
    cell, gap, left, top = 112, 2, 150, 92
    w, h = left + len(CLASES) * (cell + gap) + 16, top + len(filas) * (cell + gap) + 44
    css = ["svg{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif}",
           ".bg{fill:#fcfcfb}.t1{fill:#0b0b0b}.t2{fill:#52514e}.t3{fill:#898781}.on{fill:#ffffff}.off{fill:#0b0b0b}"]
    css += [f".c{i}{{fill:{c}}}" for i, c in enumerate(RAMPA_CLARA)]
    dark = [".bg{fill:#1a1a19}.t1{fill:#f0efec}.t2{fill:#c3c2b7}.on{fill:#0b0b0b}.off{fill:#f0efec}"]
    dark += [f".c{i}{{fill:{c}}}" for i, c in enumerate(RAMPA_OSCURA)]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
           f'aria-label="Matriz de confusión del juez ({titulo})">',
           "<style>" + "".join(css) + "@media (prefers-color-scheme: dark){" + "".join(dark) + "}</style>",
           f'<rect class="bg" width="{w}" height="{h}" rx="8"/>',
           f'<text class="t1" x="16" y="28" font-size="16" font-weight="600">Juez: lo que debía decir frente a lo que dijo ({titulo})</text>',
           f'<text class="t3" x="{left + len(CLASES) * (cell + gap) / 2}" y="{top - 30}" font-size="12" text-anchor="middle">Lo que dijo el juez</text>']
    cy = top + len(filas) * (cell + gap) / 2
    out.append(f'<text class="t3" x="22" y="{cy}" font-size="12" text-anchor="middle" '
               f'transform="rotate(-90 22 {cy})">Lo que debía decir</text>')
    for j, o in enumerate(CLASES):
        out.append(f'<text class="t2" x="{left + j * (cell + gap) + cell / 2}" y="{top - 10}" font-size="13" '
                   f'text-anchor="middle">{NOMBRES[o]}</text>')
    for i, e in enumerate(filas):
        y = top + i * (cell + gap)
        total = sum(matriz[e].values())
        out.append(f'<text class="t2" x="{left - 12}" y="{y + cell / 2 + 4}" font-size="13" text-anchor="end">{NOMBRES[e]}</text>')
        for j, o in enumerate(CLASES):
            n = matriz[e][o]
            share = n / total if total else 0
            k = 0 if n == 0 else 1 + min(5, int(share * 6))
            x = left + j * (cell + gap)
            ink = "on" if k >= 4 else "off"
            out.append(f'<rect class="c{k}" x="{x}" y="{y}" width="{cell}" height="{cell}" rx="4">'
                       f'<title>Debía: {NOMBRES[e]} · dijo: {NOMBRES[o]} · {n} de {total} ({share:.0%})</title></rect>')
            out.append(f'<text class="{ink}" x="{x + cell / 2}" y="{y + cell / 2}" font-size="22" font-weight="600" '
                       f'text-anchor="middle">{n}</text>')
            out.append(f'<text class="{ink}" x="{x + cell / 2}" y="{y + cell / 2 + 20}" font-size="12" '
                       f'text-anchor="middle">{share:.0%}</text>')
    out.append(f'<text class="t3" x="16" y="{h - 16}" font-size="12">Filas: lo que debía decir. Color: parte de la fila. '
               f'La diagonal son los aciertos.</text>')
    out.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def write_report(path: Path, res: dict) -> None:
    out = ["# Fase 6 — Calibración del juez", "",
           "Generado por `python -m src.fase6.calibracion --juzgar`. Cada variante tiene una etiqueta conocida por "
           "construcción; «confirmadas» son las que una persona confirmó en `etiquetas.csv`.", "",
           f"Etiquetas humanas: {', '.join(f'{k}: {v}' for k, v in res['etiquetas'].items())}.", ""]
    for nombre in ("todas", "confirmadas"):
        r = res[nombre]
        out += [f"## Juez — {nombre} ({r['variantes']} variantes)", ""]
        if not r["variantes"]:
            out += ["Ninguna variante en este grupo.", ""]
            continue
        out += [f"- Aciertos: **{r['aciertos']}/{r['variantes'] - r['errores']}**"
                + (f" ({r['errores']} con error del juez)" if r["errores"] else "") + ".",
                f"- Falsos aprobados (el error más grave): **{len(r['falsos_aprobados'])}**"
                + (f": {', '.join(f'`{x}`' for x in r['falsos_aprobados'])}" if r["falsos_aprobados"] else "") + ".",
                f"- Falsos rechazos: **{len(r['falsos_rechazos'])}**"
                + (f": {', '.join(f'`{x}`' for x in r['falsos_rechazos'])}" if r["falsos_rechazos"] else "") + "."]
        if r["estabilidad"]:
            e = r["estabilidad"]
            out += [f"- Estabilidad con los criterios en orden inverso (T6.8): **{e['iguales']}/{e['total']}** "
                    "con el mismo veredicto."]
        b = r["binario"]
        pct = lambda m: "—" if m["valor"] is None else f"{m['valor']:.0%} ({m['num']}/{m['den']})"
        out += [f"- Sensibilidad (respuestas con error que rechaza): **{pct(b['sensibilidad'])}**.",
                f"- Especificidad (respuestas correctas que aprueba): **{pct(b['especificidad'])}**.",
                f"- Precisión de los aprobados (de lo que aprueba, lo que es correcto): **{pct(b['precision_aprobados'])}**.",
                "", f"![Matriz de confusión — {nombre}]({path.stem}_matriz_{nombre}.svg)", "",
                "Matriz de confusión (filas: lo que debía decir; columnas: lo que dijo el juez):", ""]
        out += table(["Debía \\ Dijo"] + CLASES, [[e] + [r["matriz"][e][o] for o in CLASES] for e in CLASES],
                     align_right_from=1)
        write_matrix_svg(path.parent / f"{path.stem}_matriz_{nombre}.svg", r["matriz"], nombre)
        out += [""]
        out += table(["Tipo", "Test", "Esperado", "Aciertos", "Con la etiqueta esperada"],
                     [[t, TIPOS[t][2], TIPOS[t][0], f"{v['aciertos']}/{v['total']}",
                       "—" if v["etiqueta"] is None else f"{v['etiqueta']}/{v['total']}"]
                      for t, v in r["por_tipo"].items()], align_right_from=3)
        out += [""]
    if "verificador" in res:
        v = res["verificador"]
        out += ["## Verificador de la fase 3 (T4.2–T4.5)", "",
                f"- Aciertos: **{v['aciertos']}/{v['total']}**. Falsos aprobados: **{len(v['falsos_aprobados'])}**"
                + (f": {', '.join(f'`{x}`' for x in v['falsos_aprobados'])}" if v["falsos_aprobados"] else "") + ".", ""]
        out += table(["Tipo", "Aciertos"], [[t, f"{x['aciertos']}/{x['total']}"] for t, x in v["por_tipo"].items()],
                     align_right_from=1)
        out += [""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    from src.llm import get_config
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--variantes", action="store_true")
    p.add_argument("--revisar", action="store_true")
    p.add_argument("--juzgar", action="store_true")
    p.add_argument("--estabilidad", action="store_true")
    p.add_argument("--verificador", action="store_true")
    p.add_argument("--piloto", action="store_true")
    p.add_argument("--solo-cache", action="store_true")
    args = p.parse_args()
    ctx = {"catalog": read_jsonl(CATALOG_PATH), "restrictions": read_jsonl(RESTRICTIONS_PATH),
           "solo_cache": args.solo_cache}
    cfg = (lambda t: None) if args.solo_cache else get_config
    sub = "piloto" if args.piloto else ""
    var_path = CAL / sub / "variantes.jsonl" if sub else CAL / "variantes.jsonl"

    if args.variantes:
        ctx["cfg_corruptor"] = cfg("corruptor")
        vs, nuevas = variantes(seleccionar(ctx["catalog"]), ctx, args.piloto)
        var_path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(var_path, vs)
        if not args.piloto:
            write_labels(vs)
        print(f"{len(vs)} variantes de {len({v['caso'] for v in vs})} casos · llamadas nuevas al corruptor: {nuevas}"
              f" → {var_path.relative_to(ROOT)}" + ("" if args.piloto else f" · etiquetas → {LABELS_PATH.relative_to(ROOT)}"))
    if args.revisar:
        from src.fase6.revisar_calibracion import main as revisar
        return revisar()
    if args.juzgar:
        if not var_path.exists():
            print("[error] Faltan las variantes. Ejecuta antes: python -m src.fase6.calibracion --variantes")
            return 1
        ctx["cfg_juez"] = cfg("juez")
        vs = read_jsonl(var_path)
        rows = {r["id"]: r for n in ("train", "validation") for r in read_jsonl(FASE4 / f"{n}.jsonl")}
        juicios, nuevas = juzgar_variantes(vs, rows, ctx, args.estabilidad)
        verif = None
        if args.verificador:
            ctx["cfg_verificador"] = cfg("verificador")
            verif, n = verificar_variantes(vs, ctx)
            nuevas += n
        res = resumen(juicios, load_labels(), verif)
        write_jsonl(var_path.parent / "juicios.jsonl", juicios)
        (var_path.parent / "resumen.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n",
                                                     encoding="utf-8")
        report = ROOT / "data" / "reportes" / "fase6" / (f"calibracion_{sub}.md" if sub else "calibracion.md")
        write_report(report, res)
        t = res["todas"]
        print(f"Juez: {t['aciertos']}/{t['variantes'] - t['errores']} aciertos · falsos aprobados: "
              f"{len(t['falsos_aprobados'])} · falsos rechazos: {len(t['falsos_rechazos'])} · llamadas nuevas: {nuevas}"
              f" · reporte → {report.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
