"""Tests deterministas del paso 1 de la fase 0 (inventario y secciones)."""

from pathlib import Path

import pytest

from src.fase0 import extract
from src.fase0.extract import fence_mask, process_file, read_lines, split_markdown, split_openapi


def md_split(text: str):
    lines = read_lines(text)
    return split_markdown(lines, fence_mask(lines))


def covers_all(parts, n_lines):
    starts = [p[0] for p in parts]
    ends = [p[1] for p in parts]
    return starts[0] == 1 and ends[-1] == n_lines and all(
        s == e + 1 for s, e in zip(starts[1:], ends[:-1]))


# --- Partición de Markdown -------------------------------------------------

def test_preambulo_con_texto_es_su_propia_seccion():
    parts = md_split("intro suelta\n\n# Título\ntexto\n")
    assert [(s, e, k) for s, e, k, _ in parts] == [(1, 2, "markdown_preambulo"), (3, 4, "markdown")]


def test_preambulo_en_blanco_se_une_a_la_primera_seccion():
    parts = md_split("\n\n# Título\ntexto\n")
    assert [(s, e, t) for s, e, _, t in parts] == [(1, 4, "Título")]


def test_comentarios_bash_en_bloques_de_codigo_no_parten_secciones():
    text = "# Uso\n```bash\n# esto es un comentario\nls\n```\n## Otra\nx\n"
    parts = md_split(text)
    assert [t for *_, t in parts] == ["Uso", "Otra"]


def test_titulo_sin_espacio_se_reconoce():
    parts = md_split("#API FRESH\ntexto\n")
    assert parts[0][3] == "API FRESH"


def test_titulo_sin_cuerpo_seguido_de_subseccion_se_une():
    parts = md_split("# Components\n\n## Database\nMySQL\n")
    assert [(s, e, t) for s, e, _, t in parts] == [(1, 4, "Components / Database")]


def test_titulo_sin_cuerpo_seguido_del_mismo_nivel_se_conserva():
    parts = md_split("# API\n\n# Domain\ntexto\n")
    assert [t for *_, t in parts] == ["API", "Domain"]


def test_h3_no_parte_secciones():
    parts = md_split("## A\nx\n### A.1\ny\n")
    assert len(parts) == 1


# --- Partición de OpenAPI --------------------------------------------------

SPEC = """openapi: 3.0.1
info:
  title: Demo
paths:
  /items:
    parameters:
      - name: site
    get:
      summary: lista
    post:
      summary: crea
  /items/{id}:
    get:
      summary: detalle
components:
  schemas:
    Item:
      type: object
"""


def test_openapi_una_seccion_por_operacion_y_cobertura_total():
    lines = read_lines(SPEC)
    parts = split_openapi(lines)
    assert [t for *_, t in parts] == [
        "Cabecera OpenAPI", "GET /items", "POST /items", "GET /items/{id}", "components"]
    assert covers_all(parts, len(lines))
    # la línea de la ruta y sus parámetros comunes van con la primera operación
    get_items = parts[1]
    assert lines[get_items[0] - 1].strip() == "/items:"


# --- Chequeos sobre archivos ----------------------------------------------

@pytest.fixture
def unit(tmp_path, monkeypatch):
    """Crea docs_raw/<sw>/<ver>/guide/ en un directorio temporal."""
    docs = tmp_path / "docs_raw"
    guide = docs / "svc" / "1.0" / "guide"
    guide.mkdir(parents=True)
    monkeypatch.setattr(extract, "DOCS_RAW", docs)
    return guide


def checks_of(path: Path, unit_dir: Path):
    rec, secs = process_file(path, unit_dir, {})
    return {(c["tipo"], c["detalle"]) for c in rec.checks}, secs


def test_sidebar_con_enlace_a_pagina_inexistente(unit):
    (unit / "api.md").write_text("# API\nx\n")
    (unit / "_sidebar.md").write_text("- [API](/api)\n- [Soporte](/support.md)\n")
    checks, _ = checks_of(unit / "_sidebar.md", unit.parent)
    assert ("enlace_roto", "/support.md") in checks
    assert not any(d == "/api" for _, d in checks)


def test_ancla_inexistente_y_color_de_portada(unit):
    (unit / "api.md").write_text("[a](#detalle)\n[b](#no-existe)\n\n## Detalle\nx\n")
    (unit / "_coverpage.md").write_text("![color](#f0f0f0)\n")
    checks, _ = checks_of(unit / "api.md", unit.parent)
    assert ("ancla_rota", "#no-existe") in checks
    assert ("ancla_rota", "#detalle") not in checks
    cover, _ = checks_of(unit / "_coverpage.md", unit.parent)
    assert not cover


def test_marcador_pendiente_solo_en_lineas_completas(unit):
    (unit / "general.md").write_text("## Intro\nTO DO.\n\nTo do this, run make.\n")
    checks, _ = checks_of(unit / "general.md", unit.parent)
    assert [d for t, d in checks if t == "marcador_pendiente"] == ["TO DO."]


def test_archivo_vacio_produce_una_seccion(unit):
    (unit / "vacio.md").write_text("")
    checks, secs = checks_of(unit / "vacio.md", unit.parent)
    assert len(secs) == 1 and secs[0].kind == "vacio"
    assert any(t == "archivo_vacio" for t, _ in checks)


def test_metadatos_version_distinta(unit):
    meta = unit.parent / "documentationTypes.json"
    meta.write_text('{"guide": "https://x.s3.amazonaws.com/svc/2.0/guide/index.html"}')
    checks, _ = checks_of(meta, unit.parent)
    assert any(t == "metadatos_version_distinta" for t, _ in checks)


# --- Invariante sobre el corpus real ---------------------------------------

def test_corpus_real_cobertura_total_y_texto_exacto():
    """Cada archivo de docs_raw se parte en secciones que reconstruyen el archivo
    exactamente (process_file aborta si no). Además, cada sección coincide con sus
    líneas de origen."""
    docs = extract.DOCS_RAW
    if not docs.is_dir():
        pytest.skip("docs_raw no disponible")
    n = 0
    for unit_dir in extract.iter_units():
        for fp in sorted(p for p in unit_dir.rglob("*") if p.is_file() and p.name != ".DS_Store"):
            _, secs = process_file(fp, unit_dir, {})
            lines = read_lines(fp.read_text(encoding="utf-8"))
            for s in secs:
                assert s.text == "\n".join(lines[s.line_start - 1:s.line_end])
            n += 1
    assert n > 0
