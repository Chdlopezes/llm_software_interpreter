"""Fase 1, catálogo: un documento por archivo de docs_raw, con su contenido canónico.

No llama a ningún LLM. Lee docs_raw/ y escribe data/fase1/catalogo.jsonl.

- Un documento es un archivo de docs_raw. Su id es la ruta relativa.
- Se excluyen los archivos de navegación y metadatos de docsify (NAV_FILES): no
  contienen evidencia técnica y ocuparían contexto en cada llamada.
- El contenido canónico se obtiene normalizando el original SIN añadir ni quitar
  líneas: la línea N del canónico es la línea N del archivo de docs_raw, así que
  las líneas de la fase 0 y las citas apuntan siempre al original.
- Cada cambio queda registrado con su línea y su tipo. Salvo en los secretos, se
  guarda también la línea original, de modo que deshacerlos devuelve el archivo.
- Cada documento guarda dos hashes: el del original (procedencia, copias
  idénticas) y el del canónico (integridad de lo que devuelve la herramienta).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from src.fase0.extract import DOCS_RAW, HEADING_RE, fence_mask, read_lines, sha256
from src.fase0.label import ROOT, write_jsonl

FASE1 = ROOT / "data" / "fase1"
CATALOG_PATH = FASE1 / "catalogo.jsonl"

NAV_FILES = {"_sidebar.md", "_coverpage.md", "documentationTypes.json"}
IGNORED_FILES = {".DS_Store"}

# ---------------------------------------------------------------------------
# Normalización (una línea cada vez; nunca cambia el número de líneas)
# ---------------------------------------------------------------------------

ENTITY_RE = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|quot|amp|lt|gt|apos|nbsp);")
TAB_RE = re.compile(r"<!--\s*tab:\s*(.*?)\s*-->")
TABS_MARK_RE = re.compile(r"<!--\s*tabs:(start|end)\s*-->")
DOCSIFY_IGNORE_RE = re.compile(r"\s*<!--\s*\{docsify-ignore(-all)?\}\s*-->")
BADGE_RE = re.compile(r"\[!\[[^\]]*\]\(https?://img\.shields\.io/[^)]*\)\]\([^)]*\)"
                      r"|!\[[^\]]*\]\(https?://img\.shields\.io/[^)]*\)")

# Secretos. Los valores de relleno (your_password, ${AUTH_TOKEN}, <token>…) no se tocan.
PLACEHOLDER_RE = re.compile(r"^(\$\{?\w+\}?|<[^>]*>|your[-_].*|x{3,}|\*{3,}|changeme|example.*|\.\.\.)$",
                            re.IGNORECASE)
SECRET_RES = [
    ("token", re.compile(r"(Bearer\s+)([A-Za-z0-9._~+/=-]{16,})")),
    ("jwt", re.compile(r"()(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})")),
    ("credencial", re.compile(r"""((?:password|passwd|contraseña|secret|api[_-]?key|token)["'*]*\s*[:=][*\s]*["']?)"""
                              r"""([^\s"',}*]+)""", re.IGNORECASE)),
    ("credencial_url", re.compile(r"(://[^/\s:@]+:)([^@\s/]+)(?=@)")),
]
# Correo personal: nombre.apellido@dominio. Los buzones de equipo se conservan.
PERSONAL_EMAIL_RE = re.compile(r"\b[a-z]+\.[a-z]+@[A-Za-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE)
REDACTED = "<REDACTADO>"


def redact(line: str) -> tuple[str, list[str]]:
    kinds = []
    for kind, rx in SECRET_RES:
        def repl(m):
            if PLACEHOLDER_RE.match(m.group(2)) or m.group(2) == REDACTED:
                return m.group(0)
            kinds.append(kind)
            return m.group(1) + REDACTED
        line = rx.sub(repl, line)
    line, n = PERSONAL_EMAIL_RE.subn(REDACTED, line)
    kinds += ["correo_personal"] * n
    return line, kinds


def normalize_line(line: str) -> tuple[str, list[str], list[str]]:
    """Devuelve (línea normalizada, transformaciones, tipos de secreto redactados)."""
    done = []
    if ENTITY_RE.search(line):
        line = html.unescape(line).replace("\xa0", " ")
        done.append("entidad_html")
    if TAB_RE.search(line) or TABS_MARK_RE.search(line):
        line = TABS_MARK_RE.sub("", TAB_RE.sub(lambda m: f"{m.group(1)}:", line))
        done.append("pestana_docsify")
    if DOCSIFY_IGNORE_RE.search(line):
        line = DOCSIFY_IGNORE_RE.sub("", line)
        done.append("marca_docsify")
    if BADGE_RE.search(line):
        line = BADGE_RE.sub("", line).rstrip()
        done.append("insignia")
    line, secrets = redact(line)
    if secrets:
        done.append("secreto")
    return line, done, secrets


def normalize(raw_lines: list[str]) -> tuple[list[str], list[dict]]:
    out, changes = [], []
    for i, line in enumerate(raw_lines, start=1):
        new, done, secrets = normalize_line(line)
        out.append(new)
        if done:
            change = {"linea": i, "tipos": done}
            if secrets:
                change["secretos"] = secrets          # sin la línea original
            else:
                change["original"] = line
            changes.append(change)
    return out, changes


# ---------------------------------------------------------------------------
# Tipo de evidencia por líneas
# ---------------------------------------------------------------------------

DIAGRAM_LANGS = {"mermaid", "plantuml", "puml"}
FORMULA_RE = re.compile(r"\$\$|\\(sum|frac|sqrt|cdot|times|left|right|mathrm|text)\b")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def to_ranges(lines: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for n in sorted(lines):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def evidence_types(lines: list[str], is_openapi: bool) -> dict[str, list[list[int]]]:
    if is_openapi:
        return {"especificacion": [[1, len(lines)]]} if lines else {}
    mask = fence_mask(lines)
    found: dict[str, list[int]] = {}
    i = 0
    while i < len(lines):
        if mask[i]:                                   # bloque de código completo
            start, lang = i, lines[i].strip().strip("`~").strip().lower().split(" ")[0]
            while i + 1 < len(lines) and mask[i + 1] and not (
                    i > start and re.match(r"^\s{0,3}(`{3,}|~{3,})\s*$", lines[i])):
                i += 1
            kind = "diagrama" if lang in DIAGRAM_LANGS else "formula" if lang in {"latex", "math"} else "codigo"
            found.setdefault(kind, []).extend(range(start + 1, i + 2))
        elif lines[i].strip().startswith("|") and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
            start = i
            while i + 1 < len(lines) and not mask[i + 1] and lines[i + 1].strip().startswith("|"):
                i += 1
            found.setdefault("tabla", []).extend(range(start + 1, i + 2))
        elif lines[i].strip():
            kind = "formula" if FORMULA_RE.search(lines[i]) else "texto"
            found.setdefault(kind, []).append(i + 1)
        i += 1
    # Las líneas en blanco no interrumpen un rango: se unen los tramos del mismo tipo
    # separados solo por líneas vacías.
    blank = {n for n, line in enumerate(lines, start=1) if not line.strip()}
    order = ["texto", "tabla", "codigo", "diagrama", "especificacion", "formula"]
    out = {}
    for k in order:
        if k in found:
            merged: list[list[int]] = []
            for r in to_ranges(found[k]):
                if merged and all(n in blank for n in range(merged[-1][1] + 1, r[0])):
                    merged[-1][1] = r[1]
                else:
                    merged.append(r)
            out[k] = merged
    return out


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------

def title_of(lines: list[str], path: Path) -> str:
    mask = fence_mask(lines)
    for line, in_code in zip(lines, mask):
        m = None if in_code else HEADING_RE.match(line)
        if m:
            return m.group(2).strip()
        if path.suffix in {".yaml", ".yml"}:
            t = re.match(r"^\s{2}title:\s*['\"]?(.+?)['\"]?\s*$", line)
            if t:
                return t.group(1)
    return path.name


def iter_documents() -> list[Path]:
    return sorted(p for p in DOCS_RAW.rglob("*")
                  if p.is_file() and p.name not in IGNORED_FILES | NAV_FILES)


def build_document(path: Path) -> dict:
    rel = path.relative_to(DOCS_RAW).as_posix()
    software, version = rel.split("/")[:2]
    raw = path.read_bytes()
    raw_lines = read_lines(raw.decode("utf-8"))
    canon_lines, changes = normalize(raw_lines)
    content = "\n".join(canon_lines)
    is_openapi = path.suffix in {".yaml", ".yml"} and any(l.startswith("openapi:") for l in raw_lines[:5])
    return {
        "id": rel,
        "software": software,
        "version": version,
        "titulo": title_of(canon_lines, path),
        "contenido": content,
        "n_lineas": len(canon_lines),
        "sha256_original": sha256(raw),
        "sha256_canonico": sha256(content),
        "transformaciones": changes,
        "tipos_evidencia": evidence_types(canon_lines, is_openapi),
    }


def corpus_version(docs: list[dict]) -> str:
    return "docs_" + sha256("\n".join(f"{d['id']} {d['sha256_canonico']}" for d in docs))[:12]


def build_catalog() -> list[dict]:
    docs = [build_document(p) for p in iter_documents()]
    ids = [d["id"] for d in docs]
    if len(ids) != len(set(ids)):
        raise SystemExit("[error] IDs de documento repetidos en el catálogo")
    version = corpus_version(docs)
    for d in docs:
        d["corpus_version"] = version
    return docs


def main() -> int:
    docs = build_catalog()
    FASE1.mkdir(parents=True, exist_ok=True)
    write_jsonl(CATALOG_PATH, docs)
    print(f"Catálogo: {len(docs)} documentos ({docs[0]['corpus_version']}) → {CATALOG_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
