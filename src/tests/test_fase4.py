"""Tests de la fase 4. Deterministas: no llaman a ningún LLM.

Incluyen las mutaciones de la guía que se detectan con código (T4.1, T4.6, T4.7, T4.8). Las
semánticas (T4.2 a T4.5: hecho falso con cita real, respuesta irrelevante, abstención excesiva,
versión mezclada) las juzga el verificador; ver docs/fase4.md.
"""

import copy
import json

import pytest

from src.fase0.label import FASE0, read_jsonl
from src.fase1.catalog import CATALOG_PATH
from src.fase1.restrictions import RESTRICTIONS_PATH
from src.fase2.split import SETS, SPLITS_PATH
from src.fase3.generate import FASE3
from src.fase4 import checks, tokens
from src.fase4.run import FASE4

HAS_DATA = (FASE3 / "candidatos.jsonl").exists() and CATALOG_PATH.exists() and SPLITS_PATH.exists()
needs_data = pytest.mark.skipif(not HAS_DATA, reason="faltan las salidas de las fases 1 a 3")
HAS_EXPORT = all((FASE4 / f"{n}.jsonl").exists() for n in SETS)
needs_export = pytest.mark.skipif(not HAS_EXPORT, reason="falta ejecutar python -m src.fase4.run")


@pytest.fixture(scope="module")
def data():
    return {"rows": read_jsonl(FASE3 / "candidatos.jsonl"), "catalog": read_jsonl(CATALOG_PATH),
            "restrictions": read_jsonl(RESTRICTIONS_PATH),
            "asignacion": json.loads(SPLITS_PATH.read_text(encoding="utf-8"))["asignacion"]}


def caso(data, situacion="version_explicita", conjunto="train"):
    return copy.deepcopy(next(r for r in data["rows"] if r["situacion"] == situacion and r["conjunto"] == conjunto))


def con_respuesta(r: dict, nueva: str) -> dict:
    r["caso"]["reference_answer"] = nueva
    r["conversacion"]["messages"][-1]["content"] = nueva
    return r


# --- Estructura (T4.1) ------------------------------------------------------------

@needs_data
def test_candidato_real_pasa_los_controles(data):
    r = caso(data)
    assert checks.errores_estructura(r, data["catalog"], data["restrictions"]) == []
    assert checks.errores_aislamiento(r, data["asignacion"]) == []


@needs_data
def test_t41_cita_a_un_documento_inexistente_se_rechaza(data):
    r = caso(data)
    doc = r["caso"]["procedencia"][0]["documento"]
    r = con_respuesta(r, r["caso"]["reference_answer"].replace(doc, doc + "_no_existe"))
    assert checks.errores_estructura(r, data["catalog"], data["restrictions"])


@needs_data
def test_cita_fuera_del_documento_se_rechaza(data):
    r = caso(data)
    r = con_respuesta(r, r["caso"]["reference_answer"] + f" [{r['caso']['procedencia'][0]['documento']}:L9000-L9001]")
    assert checks.errores_estructura(r, data["catalog"], data["restrictions"])


@needs_data
def test_hash_de_procedencia_alterado_se_rechaza(data):
    r = caso(data)
    r["caso"]["procedencia"][0]["sha256_canonico"] = "0" * 64
    assert any("hash" in e for e in checks.errores_estructura(r, data["catalog"], data["restrictions"]))


@needs_data
def test_salida_de_la_herramienta_alterada_se_rechaza(data):
    r = caso(data)
    tool = next(m for m in r["conversacion"]["messages"] if m["role"] == "tool")
    out = json.loads(tool["content"])
    out["documentos"][0]["contenido"] += "\nlínea añadida"
    tool["content"] = json.dumps(out, ensure_ascii=False)
    assert any("herramienta" in e for e in checks.errores_estructura(r, data["catalog"], data["restrictions"]))


# --- Aislamiento (T4.6) -----------------------------------------------------------

@needs_data
def test_t46_documento_de_otro_conjunto_bloquea_el_caso(data):
    r = caso(data, conjunto="test")
    otro = next(d for d in data["catalog"] if data["asignacion"][d["software"]] == "train")
    tool = next(m for m in r["conversacion"]["messages"] if m["role"] == "tool")
    out = json.loads(tool["content"])
    out["documentos"].append({k: otro[k] for k in ("id", "software", "version", "titulo", "contenido")})
    tool["content"] = json.dumps(out, ensure_ascii=False)
    assert any("es de train" in e for e in checks.errores_aislamiento(r, data["asignacion"]))


@needs_data
def test_caso_en_un_conjunto_que_no_es_el_de_su_software_se_bloquea(data):
    r = caso(data, conjunto="train")
    r["conjunto"] = "test"
    assert checks.errores_aislamiento(r, data["asignacion"])


# --- Duplicados ------------------------------------------------------------------

def fila(task_id, situacion, section, pregunta, respuesta):
    return {"task_id": task_id, "conjunto": "train", "situacion": situacion,
            "semilla": {"tipo_semilla": "seccion", "section_id": section},
            "caso": {"pregunta": pregunta, "reference_answer": respuesta}}


SECCIONES = {"sw/v1/a.md#0": {"text": "misma sección"}, "sw/v2/a.md#0": {"text": "misma sección"},
             "sw/v1/b.md#0": {"text": "otra sección"}}


def test_misma_seccion_en_otra_version_y_mismas_lineas_es_duplicado():
    a = fila("train-x-001", "sin_version", "sw/v1/a.md#0", "¿Qué stack usa?", "Usa Java [sw/v1/a.md:L3-L4].")
    b = fila("train-x-002", "sin_version", "sw/v2/a.md#0", "What stack does it use?", "Java [sw/v2/a.md:L3-L4].")
    assert checks.duplicados([a, b], SECCIONES) == {"train-x-002": {"de": "train-x-001", "motivo": checks.duplicados(
        [a, b], SECCIONES)["train-x-002"]["motivo"]}}


def test_misma_seccion_con_otro_aspecto_se_conserva():
    # El par real train-software_en_historial-004/006: misma sección, una pregunta por prod y otra por stage.
    a = fila("train-x-001", "software_en_historial", "sw/v1/a.md#0",
             "¿Cómo se llama la base de producción y a qué host y puerto me conecto? ¿Es el mismo servidor que usa la base de test?",
             "La base de producción es prod_db, en el host db-prod y el puerto 3306 [sw/v1/a.md:L3-L3].")
    b = fila("train-x-002", "software_en_historial", "sw/v2/a.md#0",
             "¿Cómo se llama la base de stage y a qué host y puerto me conecto? ¿Es distinto del de producción?",
             "Stage usa stg_db, en otro servidor [sw/v2/a.md:L9-L9].")
    assert checks.duplicados([a, b], SECCIONES) == {}


def test_respuestas_genericas_identicas_no_son_duplicado():
    a = fila("train-f-001", "falta_software", "sw/v1/a.md#0", "¿Qué alerta salta si falla el stock?",
             "¿Sobre qué software es tu consulta?")
    b = fila("train-f-002", "falta_software", "sw/v1/b.md#0", "¿Cómo despliego el servicio?",
             "¿Sobre qué software es tu consulta?")
    assert checks.duplicados([a, b], SECCIONES) == {}


def test_situaciones_distintas_no_se_comparan():
    a = fila("train-a-001", "comparacion_versiones", "sw/v1/a.md#0", "¿Cambia la tabla?", "No [sw/v1/a.md:L3-L4].")
    b = fila("train-b-001", "en_que_version", "sw/v1/a.md#0", "¿En qué versión está la tabla?", "En v1 [sw/v1/a.md:L3-L4].")
    assert checks.duplicados([a, b], SECCIONES) == {}


# --- Render con la plantilla de Qwen ---------------------------------------------

def test_version_null_se_escribe_como_null_sin_tocar_los_datos():
    msgs = [{"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {
        "name": "obtener_documentacion", "arguments": {"software": "x", "version": None}}}]}]
    out = tokens.para_qwen(msgs)
    assert out[0]["tool_calls"][0]["function"]["arguments"]["version"] == "null"
    assert msgs[0]["tool_calls"][0]["function"]["arguments"]["version"] is None


@pytest.fixture(scope="module")
def tok():
    try:
        return tokens.load_tokenizer()
    except Exception as e:                       # sin red y sin caché local del tokenizer
        pytest.skip(f"no se pudo cargar el tokenizer de {tokens.MODELO}: {e}")


@needs_data
def test_t53_solo_se_supervisan_los_mensajes_del_asistente_tras_la_ultima_pregunta(data, tok):
    r = caso(data, situacion="software_en_historial")
    msgs = r["conversacion"]["messages"]
    full, spans, errors = tokens.tramos_supervisados(tok, msgs, r["conversacion"]["tools"])
    assert errors == [] and len(spans) == 2                      # la llamada y la respuesta
    supervisado = "".join(full[a:b] for a, b in spans)
    assert "<tool_call>" in supervisado and msgs[-1]["content"] in supervisado
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user", "assistant", "tool", "assistant"]
    assert msgs[3]["content"] not in supervisado                 # la pregunta del usuario
    assert msgs[2]["content"] not in supervisado                 # el turno del historial
    assert "<tool_response>" not in supervisado                  # la salida de la herramienta


# --- Exportación (T4.7, T4.8) ----------------------------------------------------

@needs_export
def test_t47_cada_tarea_tiene_un_solo_estado_final():
    ids = [r["id"] for n in SETS for r in read_jsonl(FASE4 / f"{n}.jsonl")]
    ids += [r["task_id"] for r in read_jsonl(FASE4 / "rejected.jsonl")]
    report = json.loads((FASE4 / "dataset_report.json").read_text(encoding="utf-8"))
    assert len(ids) == len(set(ids)) == report["contabilidad"]["tareas"]


@needs_export
def test_t48_las_filas_exportadas_cumplen_el_contrato_y_sus_fuentes_existen(data):
    by_id = {d["id"]: d for d in data["catalog"]}
    for n in SETS:
        for r in read_jsonl(FASE4 / f"{n}.jsonl"):
            conv = {"messages": r["messages"], "tools": r["tools"]}
            assert checks.check_example(conv, r["caso"], data["catalog"], data["restrictions"]) == [], r["id"]
            assert r["conjunto"] == n and data["asignacion"][checks.software_del_caso(
                {"caso": r["caso"], "semilla": {"documento": ""}})] == n if r["caso"]["expected_tool"] else True
            for p in r["caso"]["procedencia"]:
                assert by_id[p["documento"]]["sha256_canonico"] == p["sha256_canonico"]
            assert r["tokens"] <= tokens.MAX_TOKENS and r["tokens_supervisados"] > 0


@needs_export
def test_revision_humana_cubre_validation_y_test():
    for n in SETS:
        estados = {r["revision_humana"] for r in read_jsonl(FASE4 / f"{n}.jsonl")}
        if n == "train":
            assert estados <= {"no_aplica", "aprobado"}
        else:
            assert estados <= {"pendiente", "aprobado"}


# --- Revisión interactiva ----------------------------------------------------------

@pytest.fixture
def review_copy(tmp_path, monkeypatch):
    """Una copia del CSV de revisión con dos casos pendientes; el CSV real no se toca."""
    from src.fase4 import revisar
    rows = revisar.load_rows(FASE4 / "revision_humana.csv")[:3]
    for r in rows:
        r["decision"], r["comentario"] = "", ""
    rows[2]["decision"] = "aprobar"
    path = tmp_path / "revision_humana.csv"
    revisar.save_rows(rows, path)
    monkeypatch.setattr(revisar, "REVIEW_PATH", path)
    monkeypatch.setattr(revisar, "show", lambda *a, **k: None)
    return revisar, path, [r["task_id"] for r in rows]


def teclas(monkeypatch, *valores):
    it = iter(valores)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


@needs_export
def test_revisar_guarda_cada_decision_y_respeta_las_ya_tomadas(review_copy, monkeypatch):
    revisar, path, ids = review_copy
    monkeypatch.setattr("sys.argv", ["revisar"])
    teclas(monkeypatch, "a", "r", "", "la cita no respalda el límite")   # el motivo vacío se vuelve a pedir
    assert revisar.main() == 0
    rows = {r["task_id"]: r for r in revisar.load_rows(path)}
    assert rows[ids[0]]["decision"] == "aprobar"
    assert rows[ids[1]]["decision"] == "rechazar" and rows[ids[1]]["comentario"] == "la cita no respalda el límite"
    assert rows[ids[2]]["decision"] == "aprobar"                             # ya decidido: no se mostró


@needs_export
def test_revisar_se_puede_cortar_y_retomar(review_copy, monkeypatch):
    revisar, path, ids = review_copy
    monkeypatch.setattr("sys.argv", ["revisar"])
    teclas(monkeypatch, "s", "q")                                           # salta el primero y sale
    assert revisar.main() == 0
    rows = revisar.load_rows(path)
    assert [r["decision"] for r in rows] == ["", "", "aprobar"]
    assert [r["task_id"] for r in revisar.seleccion(rows, None, None, None, False)] == ids[:2]


# --- Exportación para TRL (data/fase4/sft) ----------------------------------------

@needs_export
def test_la_exportacion_sft_tiene_lo_que_lee_trl_y_los_ajustes_de_render():
    from src.fase4.run import SFT_DIR
    for n in ("train", "validation"):
        canon = {r["id"]: r for r in read_jsonl(FASE4 / f"{n}.jsonl")}
        sft = read_jsonl(SFT_DIR / f"{n}.jsonl")
        assert [r["id"] for r in sft] == list(canon)
        for r in sft:
            assert set(r) == {"id", "situacion", "messages", "tools", "chat_template_kwargs"}
            assert r["chat_template_kwargs"] == {"enable_thinking": False}
            assert r["messages"] == tokens.para_qwen(canon[r["id"]]["messages"])
            args = [c["function"]["arguments"] for m in r["messages"] for c in m.get("tool_calls") or []]
            assert all(a["version"] is not None for a in args)            # null → "null"
    assert not (SFT_DIR / "test.jsonl").exists()                         # test no se usa al entrenar


@needs_export
def test_trl_supervisa_la_llamada_y_la_respuesta_y_no_la_pregunta(tok):
    """La máscara que aplicará TRL (assistant_only_loss) con su plantilla de entrenamiento de Qwen3.5."""
    pytest.importorskip("trl")
    from trl.chat_template_utils import get_training_chat_template
    from src.fase4.run import SFT_DIR
    template = get_training_chat_template(tok)
    assert template is not None and "{% generation %}" in template
    for r in read_jsonl(SFT_DIR / "train.jsonl"):
        out = tok.apply_chat_template(r["messages"], tools=r["tools"], chat_template=template, tokenize=True,
                                      return_dict=True, return_assistant_tokens_mask=True, **r["chat_template_kwargs"])
        sup = tok.decode([i for i, k in zip(out["input_ids"], out["assistant_masks"]) if k])
        last_user = max(i for i, m in enumerate(r["messages"]) if m["role"] == "user")
        assert r["messages"][-1]["content"] in sup and sup.rstrip().endswith("<|im_end|>"), r["id"]
        assert r["messages"][last_user]["content"] not in sup and "<tool_response>" not in sup, r["id"]
        if any(m.get("tool_calls") for m in r["messages"]):
            assert "<tool_call>" in sup and "<parameter=version>\nNone" not in sup, r["id"]
        assert len(out["input_ids"]) <= 24576
