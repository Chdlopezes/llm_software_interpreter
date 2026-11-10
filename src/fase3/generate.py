"""Fase 3, generación de candidatos, por rondas.

    programa: argumentos decididos en tasks.py → ejecuta la herramienta real
    ronda r (máx. MAX_INTENTOS):
      generador (LLM_GENERADOR_*), por tarea: pregunta + respuesta con citas + answer_checks
        código: check_example de la fase 1 + coherencia pregunta/argumentos
          falla → se devuelve el error al generador (máx. MAX_CORRECCIONES)
      verificador (LLM_VERIFICADOR_*, otro modelo), por grupos de hasta TAMANO_GRUPO casos
        del mismo software: los documentos se envían una vez por grupo, no por caso
        algún criterio parcial/no_cumple → en la ronda siguiente el generador escribe el
        caso de nuevo, con el motivo del rechazo
    resultado: «verificado», «revisar» (needs_review) u «omitido», con su motivo.

El generador nunca escribe documentos ni decide los argumentos: la conversación se
ensambla con la salida real de la herramienta. Cada llamada al LLM se guarda en
data/fase3/cache/ con una clave que depende del prompt de sistema, el prompt completo
(documentos, semilla, intento, rechazo previo), el esquema y el modelo: si cambia
cualquiera, se vuelve a llamar. Las del generador, en <tarea>.json; las del
verificador, en verificador/<clave>.json (una por grupo).
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.fase0.label import ROOT, read_jsonl
from src.fase1.catalog import FASE1
from src.fase1.reference_examples import REFERENCE_PATH, evidence_types, system_message, turn
from src.fase1.tool import TOOLS, obtener_documentacion, tool_message
from src.fase1.validate import CONTRACT, check_example, citations
from src.llm import LLMError, generate

FASE3 = ROOT / "data" / "fase3"
CACHE_DIR = FASE3 / "cache"
PROMPTS = Path(__file__).parent / "prompts"

MAX_CORRECCIONES = 2      # correcciones por errores de código dentro de un intento
MAX_INTENTOS = 3          # rondas: tras un rechazo, el caso se escribe de nuevo con el motivo
TAMANO_GRUPO = 10         # casos del mismo software por llamada al verificador

CRITERIOS = ["pregunta_coherente", "correccion_tecnica", "responde_pregunta", "respaldo_citas",
             "cobertura_citas", "evidencia_insuficiente", "sin_abstencion_injustificada",
             "consistencia", "conflictos", "answer_checks_validos"]
RESULTADOS = ["cumple", "parcial", "no_cumple", "no_aplica"]

GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "omitir": {"type": "boolean"},
        "motivo_omision": {"type": "string"},
        "historial_usuario": {"type": "string"},
        "historial_asistente": {"type": "string"},
        "pregunta": {"type": "string"},
        "respuesta": {"type": "string"},
        "answer_checks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["omitir", "motivo_omision", "historial_usuario", "historial_asistente",
                 "pregunta", "respuesta", "answer_checks"],
    "additionalProperties": False,
}
_CRITERIO = {"type": "object",
             "properties": {"resultado": {"type": "string", "enum": RESULTADOS},
                            "justificacion": {"type": "string"}},
             "required": ["resultado", "justificacion"], "additionalProperties": False}
VER_CASO = {
    "type": "object",
    "properties": {"case_id": {"type": "string"},
                   "criterios": {"type": "object", "properties": {c: _CRITERIO for c in CRITERIOS},
                                 "required": CRITERIOS, "additionalProperties": False},
                   "needs_review": {"type": "boolean"},
                   "motivo": {"type": "string"}},
    "required": ["case_id", "criterios", "needs_review", "motivo"],
    "additionalProperties": False,
}
VER_SCHEMA = {"type": "object", "properties": {"casos": {"type": "array", "items": VER_CASO}},
              "required": ["casos"], "additionalProperties": False}


def system_generador() -> str:
    return ((PROMPTS / "generador.md").read_text(encoding="utf-8") + "\n\n# Reglas del dataset\n\n"
            + (CONTRACT / "reglas.md").read_text(encoding="utf-8"))


def system_verificador() -> str:
    return ((PROMPTS / "verificador.md").read_text(encoding="utf-8") + "\n\n# Reglas del dataset\n\n"
            + (CONTRACT / "reglas.md").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Contexto
# ---------------------------------------------------------------------------

def load_context(cfg_gen=None, cfg_ver=None, solo_cache: bool = False) -> dict:
    catalog = read_jsonl(FASE1 / "catalogo.jsonl")
    return {
        "catalog": catalog,
        "restrictions": read_jsonl(FASE1 / "restricciones.jsonl"),
        "refs": {r["caso"]["situacion"]: r for r in read_jsonl(REFERENCE_PATH)},
        "cfg_gen": cfg_gen, "cfg_ver": cfg_ver, "solo_cache": solo_cache,
    }


def rangos(r: list[list[int]]) -> str:
    return ", ".join(f"{a}-{b}" for a, b in r) or "ninguna"


def render_docs(docs: list[dict], restr: dict) -> str:
    out = []
    for d in docs:
        lines = d["contenido"].split("\n")
        out.append(f'<documento id="{d["id"]}" software="{d["software"]}" version="{d["version"]}">\n'
                   f"Líneas no citables: {rangos(restr[d['id']]['no_citables'])}\n"
                   + "\n".join(f"{i:4d}| {line}" for i, line in enumerate(lines, 1))
                   + "\n</documento>")
    return "\n\n".join(out)


def render_seed(seed: dict) -> str:
    s = {k: v for k, v in seed.items() if k not in ("tipo",)}
    return json.dumps(s, ensure_ascii=False, indent=1)


def render_reference(ref: dict) -> str:
    case = ref["caso"]
    hist = [f"{m['role']}: {m['content']}" for m in case["historial"] if m.get("content")]
    return json.dumps({"historial": hist, "pregunta": case["pregunta"],
                       "argumentos": (case["expected_tool"] or {}).get("arguments"),
                       "respuesta": case["reference_answer"], "answer_checks": case["answer_checks"]},
                      ensure_ascii=False, indent=1)


def context_docs(task: dict, result: dict | None, catalog: list[dict]) -> tuple[list[dict], str]:
    """Documentos que ve el generador. Si la herramienta no devuelve nada (falta_software,
    sin_documentos), se le muestran los de la semilla como contexto para la pregunta."""
    if result and result["documentos"]:
        return result["documentos"], "Salida real de la herramienta"
    seed = task["semilla"]
    docs = obtener_documentacion(seed["software"], seed["version"], catalog)["documentos"]
    return docs, ("Documentos de contexto de la semilla. NO se entregan al modelo en esta conversación; "
                  "úsalos solo para escribir la pregunta")


def prompt_generador(task: dict, ctx: dict, intento: int, previo: dict | None, errores: list[str] | None,
                     rechazo: dict | None = None) -> str:
    restr = {r["id"]: r for r in ctx["restrictions"]}
    args = task["args"]
    result = obtener_documentacion(args["software"], args["version"], ctx["catalog"]) if args else None
    docs, etiqueta = context_docs(task, result, ctx["catalog"])
    parts = [
        f"# Caso {task['task_id']} (intento {intento})",
        f"Situación: {task['situacion']}" + (" — dato ausente" if task["semilla"].get("dato_ausente") else ""),
        f"Idioma del caso: {task['idioma']}",
        "Argumentos de la llamada: " + (json.dumps(args, ensure_ascii=False) if args else
                                        "ninguno (no se llama a la herramienta)"),
        "Estado de la herramienta: " + (result["status"] if result else "no se llama"),
        "## Semilla\n" + render_seed(task["semilla"]),
        "## Conversación de referencia de esta situación\n" + render_reference(ctx["refs"][task["situacion"]]),
        f"## {etiqueta}\n" + (render_docs(docs, restr) or "(sin documentos)"),
    ]
    if rechazo is not None:
        parts += ["## Un intento anterior de este caso fue rechazado\n"
                  + json.dumps(rechazo["caso"], ensure_ascii=False, indent=1)
                  + "\n\nMotivo: " + rechazo["motivo"]
                  + "".join(f"\n- {k}: {v}" for k, v in rechazo.get("criterios", {}).items())
                  + "\n\nEscribe el caso de nuevo corrigiendo esos problemas. Puedes cambiar la pregunta, "
                  "pero debe seguir saliendo de la semilla."]
    if previo is not None:
        parts += ["## Tu respuesta anterior no pasó la validación por código\n"
                  + json.dumps(previo, ensure_ascii=False, indent=1)
                  + "\n\nErrores:\n" + "\n".join(f"- {e}" for e in errores)
                  + "\n\nCorrígela y devuelve el caso completo."]
    return "\n\n".join(parts)


def salida_herramienta(task: dict, ctx: dict) -> dict | None:
    args = task["args"]
    return obtener_documentacion(args["software"], args["version"], ctx["catalog"]) if args else None


def prompt_verificador(grupo: list[tuple[dict, dict]], ctx: dict) -> str:
    """Un grupo de casos del mismo software. Los documentos van primero y una sola vez (la
    unión de los que recibió cada caso); cada caso dice cuáles le entregó la herramienta."""
    restr = {r["id"]: r for r in ctx["restrictions"]}
    docs: dict[str, dict] = {}
    casos = []
    for task, case in grupo:
        result = salida_herramienta(task, ctx)
        for d in (result["documentos"] if result else []):
            docs.setdefault(d["id"], d)
        entregados = [d["id"] for d in result["documentos"]] if result else []
        casos.append("\n\n".join([
            f"### Caso {task['task_id']}",
            f"Situación: {task['situacion']}" + (" — dato ausente" if task["semilla"].get("dato_ausente") else ""),
            f"Idioma del caso: {task['idioma']}",
            "Argumentos de la llamada: " + (json.dumps(task["args"], ensure_ascii=False) if task["args"] else "ninguno"),
            "Estado de la herramienta: " + (result["status"] if result else "no se llama"),
            "Documentos entregados a este caso: " + (", ".join(entregados) or "ninguno"),
            "#### Semilla\n" + render_seed(task["semilla"]),
            "#### Historial\n" + (json.dumps(case["historial"], ensure_ascii=False, indent=1)
                                  if case["historial"] else "(vacío)"),
            "#### Pregunta\n" + case["pregunta"],
            "#### Respuesta a verificar\n" + case["reference_answer"],
            "#### answer_checks\n" + "\n".join(f"- {c}" for c in case["answer_checks"]),
        ]))
    return "\n\n".join(["# Documentos", render_docs(sorted(docs.values(), key=lambda d: d["id"]), restr)
                         or "(ninguno)", f"# Casos a verificar ({len(grupo)})"] + casos)


# ---------------------------------------------------------------------------
# Ensamblado y validación por código
# ---------------------------------------------------------------------------

def restricciones_del_caso(seed: dict) -> list[dict]:
    if seed["tipo_semilla"] == "hueco":
        return [{"tipo": "hueco", "software": seed["software"], "version": seed["version"],
                 "documento": seed["documento"], "lineas": seed["lineas"], "descripcion": seed["descripcion"]}]
    if seed["tipo_semilla"] == "conflicto":
        return [{"tipo": "conflicto", "documento": seed["documento"], "lineas": seed["lineas"],
                 "motivo": seed["motivo"], "descripcion": seed["explicacion"]}]
    if seed.get("dato_ausente"):
        return [{"tipo": "dato_ausente", "documento": seed["documento"], "lineas": seed["lineas"]}]
    return []


def assemble(task: dict, gen: dict, catalog: list[dict]) -> tuple[dict, dict]:
    """Conversación de entrenamiento y caso de evaluación, con la salida real de la herramienta."""
    by_id = {d["id"]: d for d in catalog}
    history = []
    if task["situacion"] == "software_en_historial":
        history = [{"role": "user", "content": gen["historial_usuario"]},
                   {"role": "assistant", "content": gen["historial_asistente"]}]
    msgs, result = turn(gen["pregunta"], task["args"], gen["respuesta"], catalog)
    conversation = {"tools": copy.deepcopy(TOOLS),
                    "messages": [system_message()] + copy.deepcopy(history) + msgs}
    cites = [c for c in citations(gen["respuesta"]) if c[0] in by_id]
    case = {
        "case_id": task["task_id"],
        "corpus_version": catalog[0]["corpus_version"],
        "situacion": task["situacion"],
        "idioma": task["idioma"],
        "historial": history,
        "pregunta": gen["pregunta"],
        "expected_action": "clarification" if task["args"] is None else "tool_call",
        "expected_tool": None if task["args"] is None else {"name": TOOLS[0]["function"]["name"],
                                                            "arguments": dict(task["args"])},
        "expected_document_ids": [d["id"] for d in result["documentos"]] if result else [],
        "reference_answer": gen["respuesta"],
        "answer_checks": list(gen["answer_checks"]),
        "tipo_evidencia": evidence_types(cites, catalog),
        "restricciones": restricciones_del_caso(task["semilla"]),
        "procedencia": [{"documento": doc, "lineas": [a, b], "sha256_canonico": by_id[doc]["sha256_canonico"]}
                        for doc, a, b in cites],
    }
    return conversation, case


def nombres_del_software(software: str) -> list[str]:
    """El identificador y su forma sin sufijo (vendor-stockkeeper-api → vendor-stockkeeper)."""
    names = [software]
    for suffix in ("-api", "-docs", "-gateway", "-configs"):
        if software.endswith(suffix):
            names.append(software[: -len(suffix)])
    return [n.lower() for n in names]


def coherencia(task: dict, gen: dict, catalog: list[dict]) -> list[str]:
    """Lo que la pregunta debe nombrar (o no) según la situación y los argumentos."""
    sit, args, seed = task["situacion"], task["args"], task["semilla"]
    q = gen["pregunta"].lower()
    names = nombres_del_software(seed["software"])
    versions = {d["version"].lower() for d in catalog if d["software"] == seed["software"]}
    errors = []
    if not 3 <= len(gen["answer_checks"]) <= 5:
        errors.append("answer_checks debe tener de 3 a 5 criterios")
    if sit in ("falta_software", "software_en_historial"):
        if any(n in q for n in names):
            errors.append(f"en «{sit}» la pregunta no debe nombrar el software")
    elif seed["software"].lower() not in q:
        errors.append(f"la pregunta debe nombrar el software exactamente como en el catálogo: {seed['software']}")
    if sit == "software_en_historial":
        hist = gen["historial_usuario"].lower()
        if seed["software"].lower() not in hist or args["version"].lower() not in hist:
            errors.append("historial_usuario debe nombrar el software y la versión de los argumentos")
        if args["version"].lower() in q:
            errors.append("en «software_en_historial» la pregunta no debe repetir la versión")
    elif gen["historial_usuario"] or gen["historial_asistente"]:
        errors.append(f"en «{sit}» el historial debe quedar vacío")
    if sit in ("version_explicita", "sin_documentos") and args["version"].lower() not in q:
        errors.append(f"la pregunta debe nombrar la versión {args['version']}")
    if sit in ("sin_version", "en_que_version"):
        named = sorted(v for v in versions if v in q)
        if named:
            errors.append(f"en «{sit}» la pregunta no debe nombrar ninguna versión (nombra {', '.join(named)})")
    return errors


def code_errors(task: dict, gen: dict, ctx: dict) -> tuple[list[str], dict | None, dict | None]:
    if not gen["pregunta"].strip() or not gen["respuesta"].strip():
        return ["la pregunta y la respuesta no pueden estar vacías"], None, None
    conversation, case = assemble(task, gen, ctx["catalog"])
    errors = check_example(conversation, case, ctx["catalog"], ctx["restrictions"])
    errors += coherencia(task, gen, ctx["catalog"])
    return errors, conversation, case


def estado_verificacion(ver: dict) -> str:
    if any(c["resultado"] in ("parcial", "no_cumple") for c in ver["criterios"].values()):
        return "rechazado"
    return "revisar" if ver["needs_review"] else "verificado"


# ---------------------------------------------------------------------------
# Caché y llamadas
# ---------------------------------------------------------------------------

def cache_key(system: str, prompt: str, schema: dict, model: str | None) -> str:
    return hashlib.sha256(json.dumps([system, prompt, schema, model], ensure_ascii=False).encode()).hexdigest()


class TaskCache:
    """Respuestas de las llamadas de una tarea. Al terminar solo conserva las usadas."""

    def __init__(self, task_id: str, cache_dir: Path | None = None):
        self.path = (cache_dir or CACHE_DIR) / f"{task_id}.json"
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.entries = {e["clave"]: e for e in data.get("llamadas", [])}
        self.used: list[str] = []
        self.task_id = task_id
        self.nuevas = 0

    def call(self, tarea: str, system: str, prompt: str, schema: dict, cfg, solo_cache: bool) -> dict:
        model = cfg.model if cfg else None
        key = cache_key(system, prompt, schema, model)
        if key not in self.entries and cfg is None:
            # Sin configuración (--solo-cache): vale la respuesta de cualquier modelo ya registrado en la caché.
            for m in sorted({e["modelo"] for e in self.entries.values()}):
                if cache_key(system, prompt, schema, m) in self.entries:
                    key = cache_key(system, prompt, schema, m)
                    break
        if key not in self.entries:
            if solo_cache or cfg is None:
                raise LLMError(f"falta en la caché la llamada al {tarea} (y no se permiten llamadas nuevas)")
            resp = generate(cfg, system, prompt, schema)
            self.entries[key] = {"clave": key, "tarea": tarea, "modelo": cfg.model, "backend": cfg.backend,
                                 "respuesta": resp}
            self.nuevas += 1
            self.save(partial=True)
        if key not in self.used:
            self.used.append(key)
        return self.entries[key]

    def save(self, partial: bool = False) -> None:
        keys = list(self.entries) if partial else self.used
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"task_id": self.task_id, "llamadas": [self.entries[k] for k in keys]},
                                        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Rondas
# ---------------------------------------------------------------------------

def log_entry(task_id: str, e: dict, intento: int, correccion: int, resultado: str, **extra) -> dict:
    return {"task_id": task_id, "intento": intento, "correccion": correccion, "tarea": e["tarea"],
            "modelo": e["modelo"], "backend": e["backend"], "clave": e["clave"], "resultado": resultado, **extra}


def generar(task: dict, ctx: dict, cache: TaskCache, intento: int, rechazo: dict | None) -> dict:
    """Un intento del generador, con sus correcciones por errores de código.
    estado ∈ listo | omitido | fallo_codigo | error."""
    sys_gen, log = system_generador(), []
    previo, errores = None, None
    try:
        for correccion in range(MAX_CORRECCIONES + 1):
            prompt = prompt_generador(task, ctx, intento, previo, errores, rechazo)
            e = cache.call("generador", sys_gen, prompt, GEN_SCHEMA, ctx["cfg_gen"], ctx["solo_cache"])
            gen = e["respuesta"]
            if gen["omitir"]:
                log.append(log_entry(task["task_id"], e, intento, correccion, "omitido: " + gen["motivo_omision"]))
                return {"estado": "omitido", "motivo": "generador: " + gen["motivo_omision"], "log": log}
            errores, conversation, case = code_errors(task, gen, ctx)
            log.append(log_entry(task["task_id"], e, intento, correccion,
                                 "ok" if not errores else "errores: " + " | ".join(errores)))
            if not errores:
                return {"estado": "listo", "gen": gen, "conversacion": conversation, "caso": case, "log": log}
            previo = gen
        return {"estado": "fallo_codigo", "gen": gen, "motivo": "validación por código: " + " | ".join(errores),
                "log": log}
    except LLMError as err:
        return {"estado": "error", "motivo": str(err), "log": log}


def agrupar(listos: list[tuple[dict, dict]]) -> list[list[tuple[dict, dict]]]:
    """Grupos de hasta TAMANO_GRUPO casos del mismo software, en orden de task_id."""
    by_sw = defaultdict(list)
    for task, g in sorted(listos, key=lambda x: x[0]["task_id"]):
        by_sw[task["semilla"]["software"]].append((task, g))
    return [ts[i:i + TAMANO_GRUPO] for sw in sorted(by_sw) for ts in [by_sw[sw]]
            for i in range(0, len(ts), TAMANO_GRUPO)]


def verificar(grupo: list[tuple[dict, dict]], ctx: dict, cache_dir: Path | None = None) -> tuple[dict, dict, int]:
    """Una llamada al verificador para el grupo. Devuelve (entrada de caché, veredicto por task_id, nuevas)."""
    sys_ver = system_verificador()
    prompt = prompt_verificador([(t, g["caso"]) for t, g in grupo], ctx)
    model = ctx["cfg_ver"].model if ctx["cfg_ver"] else None
    cache = TaskCache("verificador/" + cache_key(sys_ver, prompt, VER_SCHEMA, model)[:24], cache_dir=cache_dir)
    e = cache.call("verificador", sys_ver, prompt, VER_SCHEMA, ctx["cfg_ver"], ctx["solo_cache"])
    cache.save()
    vers = {v["case_id"]: v for v in e["respuesta"]["casos"]}
    ids = [t["task_id"] for t, _ in grupo]
    if sorted(vers) != sorted(ids):
        raise LLMError(f"el verificador devolvió los casos {sorted(vers)} en lugar de {ids}")
    return e, vers, cache.nuevas


def run_tasks(tasks_: list[dict], ctx: dict, workers: int = 4, progress=print) -> dict:
    """Ejecuta las rondas. Devuelve {resultados, log, nuevas}."""
    caches = {t["task_id"]: TaskCache(t["task_id"]) for t in tasks_}
    results: dict[str, dict] = {}
    rechazos: dict[str, dict] = {}
    log: list[dict] = []
    nuevas = 0
    pendientes = list(tasks_)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for intento in range(1, MAX_INTENTOS + 1):
            if not pendientes:
                break
            gens = list(pool.map(lambda t: generar(t, ctx, caches[t["task_id"]], intento,
                                                   rechazos.get(t["task_id"])), pendientes))
            listos = []
            for task, g in zip(pendientes, gens):
                log += g["log"]
                if g["estado"] in ("omitido", "error"):
                    results[task["task_id"]] = base(task, g["estado"], intento, motivo=g["motivo"])
                elif g["estado"] == "fallo_codigo":
                    rechazos[task["task_id"]] = {"caso": g["gen"], "motivo": g["motivo"]}
                else:
                    listos.append((task, g))

            grupos = agrupar(listos)

            def verificar_seguro(grupo):
                try:
                    return verificar(grupo, ctx)
                except LLMError as err:
                    return err
            for grupo, out in zip(grupos, pool.map(verificar_seguro, grupos)):
                if isinstance(out, LLMError):
                    for task, _ in grupo:
                        results[task["task_id"]] = base(task, "error", intento, motivo=str(out))
                    continue
                e, vers, n = out
                nuevas += n
                ids = [t["task_id"] for t, _ in grupo]
                for task, g in grupo:
                    ver = vers[task["task_id"]]
                    estado = estado_verificacion(ver)
                    log.append(log_entry(task["task_id"], e, intento, 0,
                                         estado + (": " + ver["motivo"] if ver["motivo"] else ""),
                                         grupo=ids, veredicto=ver))
                    if estado == "rechazado":
                        fallos = {k: c["justificacion"] for k, c in ver["criterios"].items()
                                  if c["resultado"] in ("parcial", "no_cumple")}
                        rechazos[task["task_id"]] = {"caso": g["gen"], "motivo": "verificador: " + ver["motivo"],
                                                     "criterios": fallos}
                    else:
                        r = base(task, estado, intento)
                        r.update({"verificacion": ver, "conversacion": g["conversacion"], "caso": g["caso"]})
                        results[task["task_id"]] = r
            pendientes = [t for t in pendientes if t["task_id"] not in results]
            progress(f"Ronda {intento}: {len(gens)} generados, {len(listos)} verificados en {len(grupos)} "
                     f"llamadas, {len(pendientes)} pendientes")
    for task in pendientes:
        results[task["task_id"]] = base(task, "omitido", MAX_INTENTOS,
                                        motivo="agotó los intentos; " + rechazos[task["task_id"]]["motivo"])
    for c in caches.values():
        c.save()
        nuevas += c.nuevas
    return {"resultados": sorted(results.values(), key=lambda r: r["task_id"]), "log": log, "nuevas": nuevas}


def base(task: dict, estado: str, intentos: int, motivo: str = "") -> dict:
    seed = task["semilla"]
    return {"task_id": task["task_id"], "conjunto": task["conjunto"], "situacion": task["situacion"],
            "idioma": task["idioma"], "estado": estado, "intentos": intentos, "motivo": motivo,
            "semilla": {k: seed.get(k) for k in ("tipo_semilla", "section_id", "documento", "lineas", "tipo",
                                                  "dato_ausente") if seed.get(k) is not None}}
