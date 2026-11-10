"""Tests de la fase 5: el diseño del experimento. No entrenan ni llaman a ningún LLM."""

import copy

import pytest

from src.fase0.label import read_jsonl
from src.fase4.run import FASE4
from src.fase5.run import entrada, errores_diseno, errores_entrada, load_config, presupuesto

HAS_EXPORT = all((FASE4 / f"{n}.jsonl").exists() for n in ("train", "validation", "test"))
needs_export = pytest.mark.skipif(not HAS_EXPORT, reason="falta ejecutar python -m src.fase4.run")


@pytest.fixture(scope="module")
def data():
    return {n: read_jsonl(FASE4 / f"{n}.jsonl") for n in ("train", "validation", "test")}


@pytest.fixture
def cfg():
    return load_config()


@needs_export
def test_el_diseno_entregado_pasa_los_controles(cfg, data):
    assert errores_diseno(cfg, presupuesto(cfg, data["train"]), data["train"]) == []


# --- T5.2 Contrato de entrada ------------------------------------------------------

@needs_export
def test_t52_las_entradas_terminan_en_la_pregunta_y_no_llevan_la_referencia(data):
    for n in ("validation", "test"):
        for r in data[n]:
            e = entrada(r)
            assert errores_entrada(e, r) == [], r["id"]
            assert e["messages"][-1]["role"] == "user"


@needs_export
def test_t52_una_entrada_con_la_respuesta_de_referencia_se_detecta(data):
    r = data["test"][0]
    e = entrada(r)
    e["messages"] = e["messages"] + [{"role": "assistant", "content": r["caso"]["reference_answer"]}]
    assert errores_entrada(e, r)


@needs_export
def test_t52_una_entrada_con_metadatos_del_caso_se_detecta(data):
    r = data["test"][0]
    e = dict(entrada(r), answer_checks=r["caso"]["answer_checks"])
    assert errores_entrada(e, r)


# --- T5.1 Paridad, T5.4 Presupuesto, T5.5 Test reservado -------------------------

@needs_export
def test_t51_un_experimento_con_otra_inferencia_rompe_la_paridad(cfg, data):
    cfg = copy.deepcopy(cfg)
    cfg["experimentos"]["E1"]["inferencia"] = {"temperatura": 0.7}
    assert any("T5.1" in e for e in errores_diseno(cfg, presupuesto(cfg, data["train"]), data["train"]))


@needs_export
def test_t54_e2_ve_los_mismos_ejemplos_y_pasos_que_e1_con_mas_epocas(cfg, data):
    b = presupuesto(cfg, data["train"])
    assert b["E2"]["pasos"] == b["E1"]["pasos"] and b["E2"]["ejemplos_vistos"] == b["E1"]["ejemplos_vistos"]
    assert b["E2"]["conversaciones"] < b["E1"]["conversaciones"] and b["E2"]["epocas"] > b["E1"]["epocas"]
    assert b["E2"]["situaciones"]["evidencia_parcial"] == b["E2"]["situaciones"]["sin_evidencia"] == 0
    assert {k: v for k, v in b["E2"]["situaciones"].items() if v} == \
        {k: v for k, v in b["E1"]["situaciones"].items() if k not in ("evidencia_parcial", "sin_evidencia")}


@needs_export
def test_t55_elegir_con_test_es_un_error(cfg, data):
    cfg = copy.deepcopy(cfg)
    cfg["seleccion"]["conjunto"] = "test"
    assert any("T5.5" in e for e in errores_diseno(cfg, presupuesto(cfg, data["train"]), data["train"]))


@needs_export
def test_la_longitud_maxima_cubre_la_conversacion_mas_larga(cfg, data):
    assert max(r["tokens"] for r in data["train"]) <= cfg["entrenamiento"]["longitud_maxima"]


def test_lora_solo_en_el_modelo_de_lenguaje(cfg):
    import re
    from src.fase5.entrenar import lora_targets
    r = lora_targets(cfg["entrenamiento"]["lora"])
    for name in ("model.language_model.layers.3.self_attn.q_proj", "model.language_model.layers.0.linear_attn.in_proj_qkv",
                 "model.language_model.layers.0.linear_attn.out_proj", "model.language_model.layers.1.mlp.down_proj"):
        assert re.fullmatch(r, name), name
    for name in ("model.visual.blocks.0.attn.qkv", "model.visual.blocks.0.attn.proj", "model.visual.merger.linear_fc1",
                 "lm_head", "model.language_model.layers.0.linear_attn.in_proj_a"):
        assert not re.fullmatch(r, name), name
