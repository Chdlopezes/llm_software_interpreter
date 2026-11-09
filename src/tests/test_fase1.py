"""Tests deterministas de la fase 1: catálogo, restricciones, herramienta y contrato."""

import copy
import json

import pytest

from src.fase0.extract import DOCS_RAW, read_lines
from src.fase0.label import FASE0, read_jsonl
from src.fase1 import catalog, reference_examples, restrictions
from src.fase1.catalog import normalize, normalize_line
from src.fase1.restrictions import locate
from src.fase1.tool import obtener_documentacion, seleccionar_documentos
from src.fase1.validate import check_example, check_schema, load_schema

HAS_DATA = DOCS_RAW.is_dir() and (FASE0 / "section_status.jsonl").exists()
needs_data = pytest.mark.skipif(not HAS_DATA, reason="faltan docs_raw o los resultados de la fase 0")


@pytest.fixture(scope="module")
def real():
    docs = catalog.build_catalog()
    rows, gaps = restrictions.build(docs, read_jsonl(FASE0 / "section_status.jsonl"),
                                    read_jsonl(FASE0 / "gaps.jsonl"))
    return docs, rows, gaps


# --- Normalización -----------------------------------------------------------

@pytest.mark.parametrize("line, expected, kind", [
    ("C-&gt;&gt;W: &#39;ok&#39;", "C->>W: 'ok'", "entidad_html"),
    ("<!-- tab:Operation -->", "Operation:", "pestana_docsify"),
    ("### Responsable de: <!-- {docsify-ignore} -->", "### Responsable de:", "marca_docsify"),
    ("![technology Go](https://img.shields.io/badge/technology-go-blue.svg)", "", "insignia"),
    ("[![Java](https://img.shields.io/badge/Java-17-red.svg)](https://www.oracle.com/java/)", "", "insignia"),
])
def test_cada_transformacion(line, expected, kind):
    new, done, _ = normalize_line(line)
    assert (new, done) == (expected, [kind])


def test_normalizar_no_mueve_lineas_y_se_puede_deshacer():
    raw = ["# T", "a &amp; b", "<!-- tab:Op -->", "", "texto"]
    canon, changes = normalize(raw)
    assert len(canon) == len(raw)
    restored = list(canon)
    for ch in changes:
        restored[ch["linea"] - 1] = ch["original"]
    assert restored == raw


def test_secretos_se_redactan_y_los_valores_de_relleno_no():
    assert normalize_line("Authorization: Bearer abcdefghijklmnop1234")[0] == "Authorization: Bearer <REDACTADO>"
    assert normalize_line('"password": "s3cr3tValue"')[0] == '"password": "<REDACTADO>"'
    assert normalize_line("- **Password:** your_password")[1] == []
    assert normalize_line('-H "Authorization: Bearer ${AUTH_TOKEN}"')[1] == []
    assert normalize_line('"inbound_shipment_id": "900000734"')[1] == []
    assert "<REDACTADO>" in normalize_line("- Ana Ruiz :: ana.ruiz@empresa.com")[0]
    assert normalize_line("contacto: freshproducts@vendorsync.com")[1] == []   # buzón de equipo


# --- Restricciones -----------------------------------------------------------

def test_localizar_cita_que_cruza_lineas():
    lines = ["uno", "la tabla guarda", "   datos de PME.", "fin"]
    assert locate("guarda datos de PME.", lines, 1, 4) == [2, 3]
    assert locate("no está", lines, 1, 4) is None


@needs_data
def test_todas_las_afirmaciones_excluidas_se_localizan(real):
    _, rows, _ = real
    assert all(e["lineas"] for r in rows for e in r["afirmaciones_excluidas"])


@needs_data
def test_copias_identicas_comparten_la_union_de_no_citables(real):
    docs, rows, _ = real
    by_id = {r["id"]: r for r in rows}
    for d in docs:
        r = by_id[d["id"]]
        for other in r["copias_identicas"]:
            assert by_id[other]["no_citables"] == r["no_citables"]
        assert all(any(u[0] <= s and e <= u[1] for u in r["no_citables"]) for s, e in r["no_citables_propias"])


# --- Catálogo ----------------------------------------------------------------

@needs_data
def test_catalogo_ids_unicos_lineas_y_original(real):
    docs, _, _ = real
    assert len({d["id"] for d in docs}) == len(docs) == 74
    for d in docs:
        raw = read_lines((DOCS_RAW / d["id"]).read_text(encoding="utf-8"))
        assert d["n_lineas"] == len(raw) == len(d["contenido"].split("\n"))
        assert d["id"].split("/")[:2] == [d["software"], d["version"]]
        canon = d["contenido"].split("\n")
        changed = {ch["linea"] for ch in d["transformaciones"]}
        assert all(canon[i] == raw[i] for i in range(len(raw)) if i + 1 not in changed)
        for ch in d["transformaciones"]:
            if "original" in ch:
                assert raw[ch["linea"] - 1] == ch["original"]


@needs_data
def test_catalogo_excluye_navegacion(real):
    docs, _, _ = real
    assert not any(d["id"].split("/")[-1] in catalog.NAV_FILES for d in docs)


# --- Herramienta -------------------------------------------------------------

DEMO = [
    {"id": "xss/1.0/api.md", "software": "xss", "version": "1.0", "titulo": "API", "contenido": "a",
     "corpus_version": "docs_000000000000"},
    {"id": "xss/2.0/api.md", "software": "xss", "version": "2.0", "titulo": "API", "contenido": "b",
     "corpus_version": "docs_000000000000"},
    {"id": "xss/2.0/guia.md", "software": "xss", "version": "2.0", "titulo": "Guía", "contenido": "c",
     "corpus_version": "docs_000000000000"},
    {"id": "otro/2.0/api.md", "software": "otro", "version": "2.0", "titulo": "API", "contenido": "d",
     "corpus_version": "docs_000000000000"},
]


def ids(result):
    return [d["id"] for d in result["documentos"]]


def test_filtros_de_la_herramienta():
    assert ids(obtener_documentacion("xss", None, DEMO)) == ["xss/1.0/api.md", "xss/2.0/api.md", "xss/2.0/guia.md"]
    assert ids(obtener_documentacion("xss", "2.0", DEMO)) == ["xss/2.0/api.md", "xss/2.0/guia.md"]
    assert ids(obtener_documentacion("otro", "2.0", DEMO)) == ["otro/2.0/api.md"]
    assert obtener_documentacion("xss", "9.9", DEMO)["status"] == "not_found"
    assert obtener_documentacion("nada", None, DEMO) == {"status": "not_found", "corpus_version": "docs_000000000000",
                                                        "documentos": []}


def test_la_herramienta_devuelve_solo_campos_publicos_y_contenido_completo():
    doc = obtener_documentacion("otro", "2.0", DEMO)["documentos"][0]
    assert doc == {k: DEMO[3][k] for k in ("id", "software", "version", "titulo", "contenido")}


def test_error_de_lectura_no_es_not_found(monkeypatch):
    def broken():
        raise OSError("no se puede leer")
    monkeypatch.setattr("src.fase1.tool.load_catalog", broken)
    assert obtener_documentacion("xss", None)["status"] == "error"


@needs_data
def test_version_null_incluye_las_copias_identicas(real):
    docs, _, _ = real
    versions = {d["version"] for d in seleccionar_documentos(docs, "catalog-portfolio-api", None)}
    assert versions == {"0.0.1-test-bench-v2a", "latest"}


# --- Contrato ----------------------------------------------------------------

def test_esquema_rechaza_argumentos_extra_y_casos_incompletos():
    conv = {"tools": [{}], "messages": [
        {"role": "system", "content": "s"}, {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {
            "name": "obtener_documentacion", "arguments": {"software": "x", "version": None, "query": "y"}}}]}]}
    assert any("query" in e for e in check_schema(conv, load_schema("conversation_schema.json")))
    assert any("expected_document_ids" in e for e in check_schema({"case_id": "c"}, load_schema("eval_case_schema.json")))


@pytest.fixture(scope="module")
def refs(real):
    docs, rows, _ = real
    return reference_examples.build(docs), docs, rows


@needs_data
def test_ejemplos_de_referencia_cumplen_el_contrato(refs):
    examples, docs, rows = refs
    assert len(examples) == 10
    assert {e["caso"]["situacion"] for e in examples} == set(load_schema("eval_case_schema.json")
                                                              ["properties"]["situacion"]["enum"])
    for e in examples:
        assert check_example(e["conversacion"], e["caso"], docs, rows) == []
        args = (e["caso"]["expected_tool"] or {}).get("arguments", {})
        assert args.get("software", "payment-promise-gateway") in reference_examples.REFERENCE_SOFTWARE


def mutate(examples, case_id, fn):
    e = copy.deepcopy(next(x for x in examples if x["example_id"] == case_id))
    fn(e)
    return e


@needs_data
def test_el_validador_detecta_errores(refs):
    examples, docs, rows = refs

    def errors(e):
        return " | ".join(check_example(e["conversacion"], e["caso"], docs, rows))

    def answer(e, text):
        e["conversacion"]["messages"][-1]["content"] = text

    # cita a un documento no entregado
    e = mutate(examples, "ref_version_explicita",
               lambda e: answer(e, "Dato [vendor-stockkeeper-api/latest/guide/api.md:L20-L20]."))
    assert "no entregado" in errors(e)
    # rango fuera del documento
    e = mutate(examples, "ref_version_explicita",
               lambda e: answer(e, "Dato [payment-promise-gateway/latest/guide/README.md:L9000-L9001]."))
    assert "fuera del documento" in errors(e)
    # línea no citable fuera de la situación de contradicción
    e = mutate(examples, "ref_version_explicita",
               lambda e: answer(e, "Dato [payment-promise-gateway/latest/guide/README.md:L540-L541]."))
    assert "no citables" in errors(e)
    # la misma línea en conflicto sí puede citarse en «contradiccion», pero no en otra situación
    e = mutate(examples, "ref_contradiccion", lambda e: None)
    assert errors(e) == ""
    e = mutate(examples, "ref_contradiccion", lambda e: e["caso"].update(situacion="version_explicita"))
    assert "no citables" in errors(e)
    # salida de la herramienta alterada (documento recortado)
    def cut(e):
        msg = e["conversacion"]["messages"][3]
        out = json.loads(msg["content"])
        out["documentos"][0]["contenido"] = out["documentos"][0]["contenido"][:100]
        msg["content"] = json.dumps(out, ensure_ascii=False)
    assert "salida real" in errors(mutate(examples, "ref_version_explicita", cut))
    # versión equivocada en la llamada
    def wrong_version(e):
        e["conversacion"]["messages"][2]["tool_calls"][0]["function"]["arguments"]["version"] = None
    assert "no es la esperada" in errors(mutate(examples, "ref_version_explicita", wrong_version))
    # respuesta técnica sin citas
    e = mutate(examples, "ref_version_explicita", lambda e: answer(e, "Primero getUserDebt."))
    assert "no tiene citas" in errors(e)


# --- Determinismo ------------------------------------------------------------

@needs_data
def test_dos_construcciones_dan_lo_mismo(real):
    docs, rows, gaps = real
    docs2 = catalog.build_catalog()
    rows2, gaps2 = restrictions.build(docs2, read_jsonl(FASE0 / "section_status.jsonl"),
                                      read_jsonl(FASE0 / "gaps.jsonl"))
    assert (docs, rows, gaps) == (docs2, rows2, gaps2)
    assert reference_examples.build(docs) == reference_examples.build(docs2)
