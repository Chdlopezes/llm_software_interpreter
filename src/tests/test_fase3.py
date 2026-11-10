"""Tests de la fase 3. No llaman a ningún LLM: el generador y el verificador son falsos."""

import re
from collections import Counter
from types import SimpleNamespace

import pytest

from src.fase0.label import read_jsonl
from src.fase1.catalog import CATALOG_PATH
from src.fase1.reference_examples import REFERENCE_PATH
from src.fase1.validate import check_example
from src.fase2.split import SPLITS_PATH
from src.fase3 import generate, tasks
from src.fase3.generate import CRITERIOS, cache_key, coherencia, estado_verificacion, run_tasks

HAS_DATA = CATALOG_PATH.exists() and SPLITS_PATH.exists() and REFERENCE_PATH.exists()
needs_data = pytest.mark.skipif(not HAS_DATA, reason="faltan las salidas de las fases 0 a 2")

GEN_CFG = SimpleNamespace(model="gen-model", backend="fake", label="fake:gen-model")
VER_CFG = SimpleNamespace(model="ver-model", backend="fake", label="fake:ver-model")


def veredicto(resultado="cumple", needs_review=False, motivo=""):
    return {"case_id": "", "criterios": {c: {"resultado": resultado, "justificacion": "x"} for c in CRITERIOS},
            "needs_review": needs_review, "motivo": motivo}


# --- Plan de tareas ------------------------------------------------------------

def test_cuotas_suman_n():
    for n in (1, 7, 80, 100, 232):
        assert sum(tasks.cuotas(n).values()) == n


@pytest.fixture(scope="module")
def inp():
    return tasks.load_inputs()


@pytest.fixture(scope="module")
def plan(inp):
    return tasks.build(inp)


@needs_data
def test_plan_determinista(inp, plan):
    assert tasks.build(inp) == plan


@needs_data
def test_aislamiento_cada_tarea_es_de_un_software_de_su_conjunto(inp, plan):
    for t in plan:
        assert inp["splits"]["asignacion"][t["semilla"]["software"]] == t["conjunto"]
        if t["args"]:
            assert inp["splits"]["asignacion"][t["args"]["software"]] == t["conjunto"]


@needs_data
def test_argumentos_segun_situacion(inp, plan):
    versions = {(d["software"], d["version"]) for d in inp["catalog"]}
    for t in plan:
        a = t["args"]
        if t["situacion"] == "falta_software":
            assert a is None
        elif t["situacion"] in ("sin_version", "en_que_version", "comparacion_versiones"):
            assert a["version"] is None
        elif t["situacion"] == "sin_documentos":
            assert (a["software"], a["version"]) not in versions
        else:
            assert (a["software"], a["version"]) in versions


@needs_data
def test_cada_seccion_se_usa_como_maximo_dos_veces(plan):
    uses = Counter((t["conjunto"], t["semilla"]["section_id"]) for t in plan
                   if t["semilla"]["tipo_semilla"] == "seccion")
    assert max(uses.values()) <= tasks.MAX_USOS_SECCION


@needs_data
def test_no_se_repite_semilla_mientras_queden_secciones_libres(inp, plan):
    for n in ("train", "validation", "test"):
        seeds = tasks.semillas(n, inp)["secciones"]
        used = {t["semilla"]["section_id"] for t in plan if t["conjunto"] == n and t["semilla"]["tipo_semilla"] == "seccion"}
        if any(t["semilla"].get("segundo_uso") for t in plan if t["conjunto"] == n):
            assert used == {s["section_id"] for s in seeds}          # todas se usaron antes de repetir


@needs_data
def test_comparaciones_priorizan_versiones_distintas(plan):
    test_cmp = [t for t in plan if t["conjunto"] == "test" and t["situacion"] == "comparacion_versiones"]
    assert test_cmp and test_cmp[0]["semilla"]["difiere_entre_versiones"]


# --- Caché -----------------------------------------------------------------------

def test_la_clave_cambia_si_cambia_el_prompt_o_el_modelo():
    k = cache_key("sys", "prompt", {"a": 1}, "m")
    assert k == cache_key("sys", "prompt", {"a": 1}, "m")
    assert k != cache_key("sys", "prompt con otro documento", {"a": 1}, "m")
    assert k != cache_key("otro sistema", "prompt", {"a": 1}, "m")
    assert k != cache_key("sys", "prompt", {"a": 1}, "otro modelo")


# --- Ciclo con LLM falsos --------------------------------------------------------

@pytest.fixture
def ref_task(inp):
    """Una tarea real cuya respuesta correcta es la conversación de referencia de la fase 1."""
    ref = next(r for r in read_jsonl(REFERENCE_PATH) if r["caso"]["situacion"] == "version_explicita")
    case = ref["caso"]
    task = {"task_id": "train-version_explicita-999", "conjunto": "train", "situacion": "version_explicita",
            "idioma": "es", "args": case["expected_tool"]["arguments"], "cuota": 1,
            "semilla": {"tipo_semilla": "seccion", "section_id": "x#0", "software": "payment-promise-gateway",
                        "version": "latest", "documento": case["procedencia"][0]["documento"], "lineas": [1, 2]}}
    gen = {"omitir": False, "motivo_omision": "", "historial_usuario": "", "historial_asistente": "",
           "pregunta": case["pregunta"], "respuesta": case["reference_answer"], "answer_checks": case["answer_checks"]}
    return task, gen


@pytest.fixture
def fake_llm(monkeypatch, tmp_path):
    """Generador y verificador falsos. Las respuestas del verificador son veredictos por caso:
    el falso los asigna, en orden, a los casos que aparecen en el prompt del grupo."""
    monkeypatch.setattr(generate, "CACHE_DIR", tmp_path)
    calls = []

    def install(gen_responses, ver_responses):
        gens, vers = iter(gen_responses), iter(ver_responses)

        def fake(cfg, system, prompt, schema):
            calls.append((cfg.model, prompt))
            if cfg is GEN_CFG:
                return next(gens)
            ids = re.findall(r"^### Caso (\S+)$", prompt, flags=re.M)
            return {"casos": [dict(next(vers), case_id=i) for i in ids]}
        monkeypatch.setattr(generate, "generate", fake)
        return generate.load_context(GEN_CFG, VER_CFG)
    install.calls = calls
    return install


def run_one(task, ctx):
    out = run_tasks([task], ctx, workers=1, progress=lambda *_: None)
    return out["resultados"][0], out


@needs_data
def test_caso_valido_queda_verificado_y_cumple_el_contrato(ref_task, fake_llm):
    task, gen = ref_task
    ctx = fake_llm([gen], [veredicto()])
    r, _ = run_one(task, ctx)
    assert r["estado"] == "verificado"
    assert check_example(r["conversacion"], r["caso"], ctx["catalog"], ctx["restrictions"]) == []


@needs_data
def test_error_de_codigo_se_corrige_con_el_error_devuelto(ref_task, fake_llm):
    task, gen = ref_task
    bad = dict(gen, respuesta=gen["respuesta"].replace("L120-L141", "L9000-L9001"))
    ctx = fake_llm([bad, gen], [veredicto()])
    r, out = run_one(task, ctx)
    assert r["estado"] == "verificado"
    assert [l["correccion"] for l in out["log"] if l["tarea"] == "generador"] == [0, 1]
    assert "rango fuera del documento" in fake_llm.calls[1][1]       # el error vuelve al generador


@needs_data
def test_rechazo_vuelve_al_generador_con_su_motivo(ref_task, fake_llm):
    task, gen = ref_task
    otro = dict(gen, answer_checks=gen["answer_checks"][:3])
    ctx = fake_llm([gen, otro], [veredicto("no_cumple", motivo="inventa un ejemplo curl"), veredicto()])
    r, _ = run_one(task, ctx)
    assert r["estado"] == "verificado" and r["intentos"] == 2
    segundo_prompt_gen = [p for m, p in fake_llm.calls if m == "gen-model"][1]
    assert "inventa un ejemplo curl" in segundo_prompt_gen


@needs_data
def test_agotar_los_intentos_omite_el_caso_con_su_motivo(ref_task, fake_llm):
    task, gen = ref_task
    gens = [dict(gen, pregunta=gen["pregunta"] + " " * i) for i in range(generate.MAX_INTENTOS)]
    ctx = fake_llm(gens, [veredicto("parcial", motivo="cita débil")] * generate.MAX_INTENTOS)
    r, _ = run_one(task, ctx)
    assert r["estado"] == "omitido" and "cita débil" in r["motivo"]


@needs_data
def test_casos_del_mismo_software_se_verifican_en_una_llamada(ref_task, fake_llm):
    task, gen = ref_task
    t2 = dict(task, task_id="train-version_explicita-998")
    ctx = fake_llm([gen, gen], [veredicto(), veredicto()])
    out = run_tasks([task, t2], ctx, workers=1, progress=lambda *_: None)
    assert [r["estado"] for r in out["resultados"]] == ["verificado", "verificado"]
    ver_prompts = [p for m, p in fake_llm.calls if m == "ver-model"]
    assert len(ver_prompts) == 1 and ver_prompts[0].count("<documento ") == len(set(
        re.findall(r'<documento id="([^"]+)"', ver_prompts[0])))   # cada documento, una sola vez


@needs_data
def test_la_cache_evita_volver_a_llamar(ref_task, fake_llm):
    task, gen = ref_task
    ctx = fake_llm([gen], [veredicto()])
    first, _ = run_one(task, ctx)
    ctx = fake_llm([], [])                                           # cualquier llamada nueva fallaría
    second, out = run_one(task, dict(ctx, solo_cache=True))
    assert second == first and out["nuevas"] == 0


@needs_data
def test_no_filtracion_la_entrada_del_modelo_no_lleva_referencia_ni_criterios(ref_task, fake_llm):
    task, gen = ref_task
    r, _ = run_one(task, fake_llm([gen], [veredicto()]))
    entrada = str(r["caso"]["historial"]) + r["caso"]["pregunta"]
    assert all(c not in entrada for c in r["caso"]["answer_checks"])
    assert r["caso"]["reference_answer"] not in entrada and "version_explicita" not in entrada


# --- Coherencia y veredicto ------------------------------------------------------

@needs_data
def test_coherencia_de_la_pregunta_con_la_situacion(inp):
    seed = {"software": "price-engine-api", "version": "latest"}
    gen = {"pregunta": "¿Qué devuelve price-engine-api?", "historial_usuario": "", "historial_asistente": "",
           "answer_checks": ["a", "b", "c"]}
    fs = {"situacion": "falta_software", "args": None, "semilla": seed}
    assert any("no debe nombrar el software" in e for e in coherencia(fs, gen, inp["catalog"]))
    ve = {"situacion": "version_explicita", "args": {"software": "price-engine-api", "version": "latest"}, "semilla": seed}
    assert any("debe nombrar la versión" in e for e in coherencia(ve, gen, inp["catalog"]))


def test_veredicto_lo_decide_el_programa():
    assert estado_verificacion(veredicto()) == "verificado"
    assert estado_verificacion(veredicto(needs_review=True)) == "revisar"
    v = veredicto()
    v["criterios"]["respaldo_citas"]["resultado"] = "parcial"
    assert estado_verificacion(v) == "rechazado"
    v = veredicto("no_aplica")
    assert estado_verificacion(v) == "verificado"
