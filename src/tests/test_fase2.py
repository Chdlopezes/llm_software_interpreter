"""Tests deterministas de la fase 2: separación en conjuntos."""

import random

import pytest

from src.fase0.label import FASE0
from src.fase1.catalog import CATALOG_PATH
from src.fase2 import split
from src.fase2.split import SETS, requirements, search, software_groups, violations

HAS_DATA = CATALOG_PATH.exists() and (FASE0 / "section_status.jsonl").exists()
needs_data = pytest.mark.skipif(not HAS_DATA, reason="faltan las salidas de las fases 0 y 1")


def profile(secciones=10, tipos=(), huecos=0, conflictos=0, versiones=1, distintas=False):
    return {"secciones": secciones, "lineas_por_tipo": {t: 5 for t in tipos}, "huecos": huecos,
            "conflictos": conflictos, "varias_versiones": versiones > 1,
            "versiones_distintas": distintas, "versiones": [str(i) for i in range(versiones)]}


FULL = ("tabla", "codigo", "diagrama", "especificacion")


@pytest.fixture
def no_forced(monkeypatch):
    monkeypatch.setattr(split, "FORCED", {})


# --- Grupos ------------------------------------------------------------------

def test_software_que_comparten_contenido_forman_un_grupo():
    line = "Esta es una línea larga que se repite en dos software distintos {}"
    docs = [{"software": "a", "contenido": "\n".join(line.format(i) for i in range(3))},
            {"software": "b", "contenido": "\n".join(line.format(i) for i in range(3))},
            {"software": "c", "contenido": line.format(0)}]
    assert software_groups(docs) == [["a", "b"], ["c"]]


# --- Mínimo obligatorio ------------------------------------------------------

def test_un_elemento_escaso_no_se_exige():
    profiles = {"a": profile(tipos=FULL + ("formula",)), "b": profile(tipos=FULL), "c": profile(tipos=FULL)}
    _, excluded = requirements([["a"], ["b"], ["c"]], profiles)
    assert "formula" in excluded and "tabla" not in excluded


def test_violaciones_detectadas(no_forced):
    profiles = {"a": profile(tipos=FULL, huecos=1, conflictos=1, versiones=2, distintas=True),
                "b": profile(tipos=FULL, huecos=1, conflictos=1, versiones=2),
                "c": profile(tipos=("texto",)),
                "d": profile(tipos=FULL, huecos=1, conflictos=1)}
    groups = [["a"], ["b"], ["c"], ["d"]]
    req, _ = requirements(groups, profiles)
    errors = violations({"a": "train", "b": "validation", "c": "test", "d": "train"}, groups, profiles, req)
    assert any("test no tiene «versiones_distintas»" in e for e in errors)
    assert any("test no tiene «tabla»" in e for e in errors)


def test_software_forzado_fuera_de_train_se_rechaza(monkeypatch):
    monkeypatch.setattr(split, "FORCED", {"a": "train"})
    profiles = {s: profile(tipos=FULL, huecos=1, conflictos=1, versiones=2, distintas=True) for s in "abc"}
    groups = [["a"], ["b"], ["c"]]
    req, _ = requirements(groups, profiles)
    assert any("a debe ir a train" in e for e in violations({"a": "test", "b": "train", "c": "validation"},
                                                             groups, profiles, req))


def test_un_grupo_no_se_reparte_entre_conjuntos(no_forced):
    profiles = {s: profile() for s in "ab"}
    errors = violations({"a": "train", "b": "test"}, [["a", "b"]], profiles, {n: [] for n in SETS})
    assert any("repartido" in e for e in errors)


# --- Búsqueda ----------------------------------------------------------------

def test_busqueda_exhaustiva_elige_el_mas_cercano_al_objetivo(no_forced):
    profiles = {"a": profile(60), "b": profile(20), "c": profile(20), "d": profile(1)}
    groups = [[s] for s in "abcd"]
    assignment, method = search(groups, profiles, {n: [] for n in SETS})
    assert method["metodo"] == "exhaustivo"
    assert assignment["a"] == "train" and {assignment["b"], assignment["c"]} == {"validation", "test"}


def test_reparto_voraz_con_muchos_software(no_forced):
    rng = random.Random(0)
    profiles = {f"sw{i:03d}": profile(rng.randint(1, 30), tipos=rng.sample(FULL, 2), huecos=rng.randint(0, 3),
                                      conflictos=rng.randint(0, 3), versiones=rng.choice([1, 1, 2]),
                                      distintas=rng.random() < 0.3)
                for i in range(200)}
    groups = [[s] for s in sorted(profiles)]
    req, _ = requirements(groups, profiles)
    assignment, method = search(groups, profiles, req)
    assert method["metodo"] == "voraz"
    assert violations(assignment, groups, profiles, req) == []
    w = split.sizes(assignment, profiles)
    total = sum(w.values())
    assert all(abs(w[n] / total - split.TARGET[n]) < 0.01 for n in SETS)


# --- Corpus real -------------------------------------------------------------

@needs_data
def test_reparto_real_cumple_el_criterio():
    result = split.build()
    sets = result["conjuntos"]
    assert sorted(s for n in SETS for s in sets[n]["software"]) == sorted(result["perfiles"])
    assert all(result["asignacion"][s] == "train" for s in split.FORCED)
    assert sets["test"]["cobertura"]["versiones_distintas"]
    hashes = [{d["sha256_canonico"] for d in sets[n]["documentos"]} for n in SETS]
    assert not (hashes[0] & hashes[1] or hashes[0] & hashes[2] or hashes[1] & hashes[2])


@needs_data
def test_reparto_determinista():
    assert split.build() == split.build()
