"""Tests deterministas de los pasos 5 y 6 de la fase 0 (etiqueta final y cobertura)."""

import pytest

from src.fase0.finalize import default_decision, final_label, review_reason, verify_coverage

SECTION = {"section_id": "svc/1.0/a.md#0", "unit": "svc/1.0", "software": "svc", "version": "1.0",
           "file": "svc/1.0/a.md", "line_start": 1, "line_end": 3, "title": "A"}


def a_label(estado="usable", categoria="endpoint_api", valida=True, problemas=None):
    return {"estado": estado, "categoria": categoria, "valida": valida, "justificacion": "j",
            "problemas": problemas or [], "heredada_de": None}


def b_label(estado="usable", categoria="endpoint_api", de_acuerdo=True, valida=True, cita=""):
    return {"estado": estado, "categoria": categoria, "de_acuerdo": de_acuerdo, "valida": valida,
            "cita": cita, "explicacion": "e"}


# --- Cuándo hace falta una decisión -----------------------------------------

def test_mismo_estado_no_necesita_decision():
    assert review_reason(a_label(), b_label()) is None


def test_categoria_distinta_no_necesita_decision_y_se_usa_la_de_a():
    a, b = a_label(categoria="endpoint_api"), b_label(categoria="otro", de_acuerdo=False)
    assert review_reason(a, b) is None
    assert final_label(SECTION, a, b, None)["categoria"] == "endpoint_api"


def test_estado_distinto_o_respuesta_invalida_necesita_decision():
    assert review_reason(a_label(), b_label(estado="no_usable", de_acuerdo=False))
    assert review_reason(a_label(valida=False), b_label())
    assert review_reason(a_label(), None)


# --- Decisión humana y por defecto ------------------------------------------

def test_la_persona_elige_el_criterio_de_a_o_de_b():
    a, b = a_label("usable", "endpoint_api"), b_label("no_usable", "otro", de_acuerdo=False, cita="x")
    s = final_label(SECTION, a, b, "A")
    assert (s["estado"], s["categoria"], s["origen"]) == ("usable", "endpoint_api", "decision_humana")
    s = final_label(SECTION, a, b, "B")
    assert (s["estado"], s["categoria"], s["decision"]) == ("no_usable", "otro", "B")


@pytest.mark.parametrize("ea, eb, expected", [
    ("usable", "parcial", "B"),      # gana parcial
    ("parcial", "no_usable", "A"),   # gana parcial
    ("no_usable", "usable", "B"),    # sin parcial, gana usable
    ("usable", "no_usable", "A"),
])
def test_decision_por_defecto(ea, eb, expected):
    assert default_decision(a_label(ea), b_label(eb, de_acuerdo=False)) == expected


def test_fila_vacia_se_completa_por_defecto():
    s = final_label(SECTION, a_label("no_usable"), b_label("usable", de_acuerdo=False), None)
    assert (s["estado"], s["origen"], s["decision"]) == ("usable", "decision_por_defecto", "B")


def test_decision_humana_no_pisa_un_acuerdo_entre_a_y_b():
    assert final_label(SECTION, a_label(), b_label(), "B")["origen"] == "acuerdo_a_b"


def test_parcial_elegido_excluye_solo_las_citas_del_modelo_elegido():
    problema = {"motivo": "inconsistencia", "cita": "name: x", "otras_secciones": [], "explicacion": ""}
    a = a_label("parcial", problemas=[problema])
    b = b_label("no_usable", de_acuerdo=False, cita="name: y")
    assert final_label(SECTION, a, b, "A")["afirmaciones_excluidas"] == ["name: x"]


def test_parcial_por_acuerdo_excluye_las_citas_de_ambos():
    problema = {"motivo": "inconsistencia", "cita": "name: x", "otras_secciones": [], "explicacion": ""}
    s = final_label(SECTION, a_label("parcial", problemas=[problema]), b_label("parcial", cita="name: y"), None)
    assert s["afirmaciones_excluidas"] == ["name: x", "name: y"]


# --- Cobertura (paso 6) -----------------------------------------------------

def test_cobertura_detecta_secciones_sin_etiqueta_y_duplicadas():
    other = {**SECTION, "section_id": "svc/1.0/a.md#1"}
    s0 = final_label(SECTION, a_label(), b_label(), None)
    assert verify_coverage([SECTION], [s0]) == []
    assert verify_coverage([SECTION, other], [s0])          # falta una
    assert verify_coverage([SECTION], [s0, s0])             # duplicada
