"""Tests de la fase 6: evaluación y calibración. No llaman a ningún LLM (el juez es falso)."""

import copy
import re
from types import SimpleNamespace

import pytest

from src.fase0.label import read_jsonl
from src.fase1.catalog import CATALOG_PATH
from src.fase1.restrictions import RESTRICTIONS_PATH
from src.fase3 import generate
from src.fase4.run import FASE4
from src.fase6 import calibracion, evaluar, judge

HAS_EXPORT = all((FASE4 / f"{n}.jsonl").exists() for n in ("train", "validation"))
needs_export = pytest.mark.skipif(not HAS_EXPORT, reason="falta ejecutar python -m src.fase4.run")
JUEZ = SimpleNamespace(model="juez-falso", backend="fake", label="fake:juez-falso")


@pytest.fixture(scope="module")
def ctx():
    return {"catalog": read_jsonl(CATALOG_PATH), "restrictions": read_jsonl(RESTRICTIONS_PATH), "max_llamadas": 2}


@pytest.fixture(scope="module")
def val():
    return read_jsonl(FASE4 / "validation.jsonl")


def fila(val, situacion):
    return copy.deepcopy(next(r for r in val if r["situacion"] == situacion))


def generado(r):
    """La conversación de referencia como si la hubiera generado el modelo (lo que sigue a la pregunta)."""
    last_user = max(i for i, m in enumerate(r["messages"]) if m["role"] == "user")
    return r["messages"][last_user + 1:]


def juicio(n_checks=3, resultado="cumple", respaldo="respaldada", cita_respalda=True, abstencion="no_aplica",
           incidencia=False):
    return {"checks": [{"indice": i, "resultado": resultado, "evidencia": "x"} for i in range(1, n_checks + 1)],
            "afirmaciones": [{"texto": "a", "cita": "[d:L1-L2]", "respaldo": respaldo, "cita_respalda": cita_respalda}],
            "abstencion": abstencion, "etiquetas_error": [], "incidencia_referencia": incidencia,
            "motivo_incidencia": "", "resumen": ""}


# --- Veredicto: lo decide el programa --------------------------------------------

def test_veredicto_aprueba_solo_si_todo_esta_bien():
    assert judge.veredicto(juicio())["estado"] == "aprueba"
    assert judge.veredicto(juicio(resultado="parcial"))["estado"] == "falla"
    assert judge.veredicto(juicio(respaldo="contradicha"))["estado"] == "falla"
    assert judge.veredicto(juicio(cita_respalda=False))["estado"] == "falla"        # T6.6: sin cita que respalde
    assert judge.veredicto(juicio(abstencion="indebida"))["estado"] == "falla"      # T6.4
    assert judge.veredicto(juicio(abstencion="faltante"))["estado"] == "falla"
    assert judge.veredicto(juicio(incidencia=True))["estado"] == "incidencia_referencia"   # T6.7


def test_una_oferta_de_ayuda_no_necesita_cita():
    j = juicio()
    j["afirmaciones"].append({"texto": "Puedo consultar otra versión", "cita": "", "respaldo": "sin_verificar",
                              "cita_respalda": False})
    assert judge.veredicto(j)["estado"] == "aprueba"


@needs_export
def test_el_juez_debe_devolver_todos_los_criterios(val):
    caso = fila(val, "version_explicita")["caso"]
    j = juicio(n_checks=len(caso["answer_checks"]) - 1)
    assert judge.errores_juicio(j, caso)


# --- Controles por código (8.1, 8.2, citas) -------------------------------------

@needs_export
def test_la_referencia_como_prediccion_pasa_los_controles(val, ctx):
    for r in val:
        a = evaluar.analizar(generado(r), r["caso"], ctx["catalog"], ctx["restrictions"], 2)
        assert a["llamada_ok"] and a["documentos_ok"] and a["errores_citas"] == [], r["id"]


@needs_export
def test_otra_version_falla_la_llamada_y_los_documentos(val, ctx):
    r = fila(val, "version_explicita")
    msgs = generado(r)
    msgs[0]["tool_calls"][0]["function"]["arguments"]["version"] = None
    a = evaluar.analizar(msgs, r["caso"], ctx["catalog"], ctx["restrictions"], 2)
    assert not a["llamada_ok"]


@needs_export
def test_null_como_texto_cuenta_como_null(val, ctx):
    r = fila(val, "sin_version")
    msgs = generado(r)
    msgs[0]["tool_calls"][0]["function"]["arguments"]["version"] = "null"
    a = evaluar.analizar(msgs, r["caso"], ctx["catalog"], ctx["restrictions"], 2)
    assert a["llamada_ok"] and a["documentos_ok"]


@needs_export
def test_llamar_cuando_falta_el_software_es_un_error(val, ctx):
    r = fila(val, "falta_software")
    otro = fila(val, "version_explicita")
    a = evaluar.analizar(generado(otro), r["caso"], ctx["catalog"], ctx["restrictions"], 2)
    assert not a["llamada_ok"]


@needs_export
def test_citar_un_documento_no_recibido_es_un_error(val, ctx):
    r = fila(val, "version_explicita")
    msgs = generado(r)
    msgs[-1]["content"] += " [otro-software/latest/README.md:L1-L2]"
    a = evaluar.analizar(msgs, r["caso"], ctx["catalog"], ctx["restrictions"], 2)
    assert any("no entregado" in e for e in a["errores_citas"])


# --- Prompt del juez -------------------------------------------------------------

@needs_export
def test_el_prompt_del_juez_no_revela_el_modelo_y_respeta_el_orden(val, ctx):
    r = fila(val, "version_explicita")
    a = evaluar.analizar(generado(r), r["caso"], ctx["catalog"], ctx["restrictions"], 2)
    p = judge.prompt_juez(r["caso"], a["respuesta"], a["llamadas"], a["documentos"], ctx["restrictions"])
    assert "E1" not in p and "B0" not in p and "Qwen" not in p
    n = len(r["caso"]["answer_checks"])
    inv = judge.prompt_juez(r["caso"], a["respuesta"], a["llamadas"], a["documentos"], ctx["restrictions"],
                            orden=list(reversed(range(n))))
    assert inv.index(f"{n}. ") < inv.index("1. " + r["caso"]["answer_checks"][0])      # mismo número, otro orden


# --- Métricas ----------------------------------------------------------------------

def resultado(situacion, j, llamada_ok=True, tool=True):
    return {"caso": {"situacion": situacion, "expected_tool": {} if tool else None}, "llamada_ok": llamada_ok,
            "documentos_ok": True, "errores_citas": [], "juicio": j, "veredicto": judge.veredicto(j)}


def test_metricas_con_numerador_y_denominador():
    rs = [resultado("version_explicita", juicio()), resultado("version_explicita", juicio(resultado="no_cumple")),
          resultado("sin_evidencia", juicio(abstencion="correcta")),
          resultado("evidencia_parcial", juicio(respaldo="no_respaldada"))]
    m = evaluar.metricas(rs)["total"]
    assert m["correccion_completitud"] == {"num": 9, "den": 12, "valor": 0.75}
    assert m["abstencion_correcta"] == {"num": 1, "den": 1, "valor": 1.0}
    assert m["parcial_correcta"]["num"] == 0 and m["parcial_correcta"]["den"] == 1
    assert m["aprobados"] == {"num": 2, "den": 4, "valor": 0.5}


def test_sin_afirmaciones_citadas_el_respaldo_no_aplica():
    j = juicio()
    j["afirmaciones"] = []
    m = evaluar.metricas([resultado("falta_software", j, tool=False)])["total"]
    assert m["respaldo_citas"]["valor"] is None and m["cobertura_citas"]["valor"] is None   # no 100%


def test_una_incidencia_de_referencia_no_cuenta_contra_el_modelo():
    m = evaluar.metricas([resultado("version_explicita", juicio(resultado="no_cumple", incidencia=True))])["total"]
    assert m["incidencias_referencia"] == 1 and m["correccion_completitud"]["den"] == 0


# --- Evaluación de punta a punta con un juez falso --------------------------------

@needs_export
def test_evaluar_con_juez_falso_y_cache(val, ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(evaluar, "CACHE_JUEZ", tmp_path)
    llamadas = []

    def fake(cfg, system, prompt, schema):
        llamadas.append(prompt)
        n = len(re.findall(r"^\d+\. ", prompt.split("## Criterios (answer_checks)\n")[1].split("\n\n## ")[0], re.M))
        return juicio(n_checks=n)
    monkeypatch.setattr(generate, "generate", fake)
    rows = val[:3]
    preds = [{"id": r["id"], "mensajes": generado(r)} for r in rows]
    casos = {r["id"]: r["caso"] for r in rows}
    res, nuevas = evaluar.evaluar(preds, casos, dict(ctx, cfg=JUEZ, solo_cache=False), "E1")
    assert nuevas == 3 and all(r["veredicto"]["estado"] == "aprueba" for r in res)
    res2, nuevas2 = evaluar.evaluar(preds, casos, dict(ctx, cfg=None, solo_cache=True), "E1")
    assert nuevas2 == 0 and [r["juicio"] for r in res2] == [r["juicio"] for r in res]


# --- Calibración -------------------------------------------------------------------

@needs_export
def test_la_calibracion_no_usa_test_y_es_determinista(ctx):
    sel = calibracion.seleccionar(ctx["catalog"])
    assert sel == calibracion.seleccionar(ctx["catalog"])
    assert all(not r["id"].startswith("test-") for r, _ in sel)
    versiones = [r for r, tipos in sel if "version_mezclada" in tipos]
    assert versiones and all(calibracion.difiere(r, ctx["catalog"]) for r in versiones)
    for r, tipos in sel:
        assert tipos[0] == "referencia" and set(tipos) <= set(calibracion.TIPOS)


@needs_export
def test_la_variante_sin_citas_no_tiene_ninguna_y_el_contrato_la_rechaza(val, ctx):
    r = fila(val, "version_explicita")
    sin = calibracion.CITA.sub("", r["caso"]["reference_answer"])
    assert "[" not in sin or not re.search(r":L\d+-L\d+\]", sin)
    a = calibracion.analisis_esperado(r, sin, ctx)
    assert "la respuesta no tiene citas" in a["errores_citas"]
