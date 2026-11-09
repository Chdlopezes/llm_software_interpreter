"""Fase 0, paso 1: inventario, partición en secciones y chequeos deterministas.

No llama a ningún LLM. Lee docs_raw/ y escribe en data/fase0/:

    units.jsonl      un registro por software/versión
    inventory.jsonl  un registro por archivo, con sus chequeos
    sections.jsonl   un registro por sección; juntas cubren el 100% de las líneas

Uso, desde la raíz del repositorio:
    python -m src.fase0.extract
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS_RAW = ROOT / "docs_raw"
OUT_DIR = ROOT / "data" / "fase0"

IGNORED_FILES = {".DS_Store"}
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def read_lines(text: str) -> list[str]:
    """Líneas del archivo sin el salto final. '\n'.join(lines) reconstruye el texto
    salvo el salto de línea final, que no aporta contenido."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def fence_mask(lines: list[str]) -> list[bool]:
    """True para cada línea que está dentro de un bloque de código (incluidas las vallas)."""
    mask, open_fence = [], None
    for line in lines:
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if open_fence is None:
            if m:
                open_fence = m.group(1)
                mask.append(True)
                continue
            mask.append(False)
        else:
            mask.append(True)
            if m and m.group(1)[0] == open_fence[0] and len(m.group(1)) >= len(open_fence):
                open_fence = None
    return mask


HEADING_RE = re.compile(r"^(#{1,6})(?!#)\s*(\S.*?)\s*#*\s*$")


def headings(lines: list[str], mask: list[bool]) -> list[tuple[int, int, str]]:
    """(línea 1-based, nivel, título) de los títulos Markdown fuera de bloques de código.
    Acepta también '#Título' sin espacio, que aparece en el corpus."""
    out = []
    for i, (line, in_code) in enumerate(zip(lines, mask), start=1):
        if in_code:
            continue
        m = HEADING_RE.match(line)
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def slug_loose(text: str) -> str:
    """Normalización tolerante para comparar anclas con títulos: solo letras y dígitos,
    en minúsculas y sin acentos. Evita falsos positivos por diferencias entre
    algoritmos de slug (GitHub, docsify, etc.)."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text.lower() if c.isalnum() and not unicodedata.combining(c))


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------

@dataclass
class Section:
    section_id: str
    unit: str
    software: str
    version: str
    file: str
    n: int
    kind: str
    title: str
    line_start: int
    line_end: int
    text: str

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["text_sha256"] = sha256(self.text)
        d["n_chars"] = len(self.text)
        return d


@dataclass
class FileRecord:
    path: str            # relativa a docs_raw/
    unit: str
    software: str
    version: str
    file_type: str
    sha256: str
    bytes: int
    n_lines: int
    parse_ok: bool = True
    checks: list[dict] = field(default_factory=list)
    n_sections: int = 0

    def add_check(self, tipo: str, linea: int | None, detalle: str) -> None:
        self.checks.append({"tipo": tipo, "linea": linea, "detalle": detalle})


# ---------------------------------------------------------------------------
# Partición en secciones
# ---------------------------------------------------------------------------

def ranges_from_starts(starts: list[int], n_lines: int) -> list[tuple[int, int]]:
    starts = sorted(set(starts))
    ends = [s - 1 for s in starts[1:]] + [n_lines]
    return list(zip(starts, ends))


def split_markdown(lines: list[str], mask: list[bool]) -> list[tuple[int, int, str, str]]:
    """Secciones por títulos de nivel 1 y 2.

    - El texto anterior al primer título es su propia sección si tiene contenido; si
      solo son líneas en blanco, se une a la primera.
    - Un título sin cuerpo seguido de un título más profundo ('# Components' y luego
      '## Database') se une a esa subsección: es estructura, no un hueco. Un título sin
      cuerpo seguido de otro del mismo nivel se conserva y se marca como vacío.
    """
    hs = [(ln, level, title) for ln, level, title in headings(lines, mask) if level <= 2]
    if not hs:
        return [(1, len(lines), "markdown", "")]
    merged: list[tuple[int, int, str]] = []
    for ln, level, title in hs:
        if merged:
            p_ln, p_level, p_title = merged[-1]
            body_blank = not any(l.strip() for l in lines[p_ln:ln - 1])
            if body_blank and level > p_level:
                merged[-1] = (p_ln, level, f"{p_title} / {title}")
                continue
        merged.append((ln, level, title))
    starts = [ln for ln, _, _ in merged]
    titles = {ln: t for ln, _, t in merged}
    first = starts[0]
    if first > 1:
        preamble_has_text = any(l.strip() for l in lines[: first - 1])
        if preamble_has_text:
            starts.insert(0, 1)
        else:
            titles[1] = titles.pop(first)
            starts[0] = 1
    out = []
    for s, e in ranges_from_starts(starts, len(lines)):
        title = titles.get(s, "")
        kind = "markdown" if title else "markdown_preambulo"
        out.append((s, e, kind, title))
    return out


def split_openapi(lines: list[str]) -> list[tuple[int, int, str, str]]:
    """Cabecera (todo lo anterior a la primera operación), una sección por operación
    (método + ruta) y una por cada bloque de nivel superior posterior a `paths`
    (p. ej. `components`). Trabaja por líneas para conservar la procedencia exacta."""
    top_re = re.compile(r"^([A-Za-z_][\w-]*):")
    paths_line = next((i for i, l in enumerate(lines, 1) if l.startswith("paths:")), None)
    if paths_line is None:
        return [(1, len(lines), "openapi_cabecera", "OpenAPI (sin paths)")]

    # fin del bloque paths = siguiente clave de nivel superior
    paths_end = next(
        (i for i in range(paths_line + 1, len(lines) + 1) if top_re.match(lines[i - 1])),
        len(lines) + 1,
    )
    # indentación de las rutas = la de la primera línea no vacía dentro de paths
    path_indent = None
    for i in range(paths_line + 1, paths_end):
        l = lines[i - 1]
        if l.strip() and not l.strip().startswith("#"):
            path_indent = len(l) - len(l.lstrip())
            break

    starts: list[int] = [1]
    titles: dict[int, tuple[str, str]] = {1: ("openapi_cabecera", "Cabecera OpenAPI")}
    current_path, pending_path_line, method_indent = None, None, None
    for i in range(paths_line + 1, paths_end):
        l = lines[i - 1]
        if not l.strip():
            continue
        indent = len(l) - len(l.lstrip())
        key = l.strip().split(":", 1)[0].strip("'\"")
        if indent == path_indent and key.startswith("/"):
            current_path, pending_path_line, method_indent = key, i, None
        elif current_path and indent > path_indent and key.lower() in HTTP_METHODS:
            if method_indent is None:
                method_indent = indent
            if indent == method_indent:
                # la línea de la ruta (y sus parámetros comunes) van con la primera operación
                start = pending_path_line or i
                pending_path_line = None
                starts.append(start)
                titles[start] = ("openapi_operacion", f"{key.upper()} {current_path}")

    for i in range(paths_end, len(lines) + 1):
        m = top_re.match(lines[i - 1])
        if m:
            starts.append(i)
            titles[i] = ("openapi_bloque", m.group(1))

    return [(s, e, *titles[s]) for s, e in ranges_from_starts(starts, len(lines))]


# ---------------------------------------------------------------------------
# Chequeos deterministas
# ---------------------------------------------------------------------------

MD_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(\s*([^)]*?)\s*\)")
HTML_LINK_RE = re.compile(r"""\b(href|src)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
HTML_ID_RE = re.compile(r"""\b(?:id|name)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
HTML_ENTITY_RE = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|quot|amp|lt|gt|apos);")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}


def guide_root(unit_dir: Path, file_path: Path) -> Path:
    """Raíz del sitio docsify: la carpeta guide/ de la unidad (o la propia unidad)."""
    g = unit_dir / "guide"
    return g if g.is_dir() and g in file_path.parents else unit_dir


def resolve_target(target: str, file_path: Path, root: Path) -> Path | None:
    """Resuelve un enlace local como lo haría docsify: absoluto desde la raíz de la guía,
    o relativo al archivo o a la raíz; sin extensión prueba .md; carpeta prueba README.md."""
    bases = [root / target.lstrip("/")] if target.startswith("/") else [
        file_path.parent / target, root / target]
    for base in bases:
        candidates = [base]
        if base.suffix == "":
            candidates += [base.with_suffix(".md"), base / "README.md"]
        if target.endswith("/"):
            candidates.insert(0, base / "README.md")
        for c in candidates:
            if c.is_file():
                return c
    return None


def anchors_of(path: Path, cache: dict) -> set[str]:
    if path not in cache:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = read_lines(text)
        mask = fence_mask(lines)
        found = {slug_loose(t) for _, _, t in headings(lines, mask)}
        found |= {slug_loose(a) for a in HTML_ID_RE.findall(text)}
        cache[path] = found
    return cache[path]


def check_markdown(rec: FileRecord, lines: list[str], mask: list[bool], file_path: Path,
                   unit_dir: Path, anchor_cache: dict) -> None:
    root = guide_root(unit_dir, file_path)
    entity_lines: list[int] = []
    for i, (line, in_code) in enumerate(zip(lines, mask), start=1):
        if in_code:
            if HTML_ENTITY_RE.search(line):
                entity_lines.append(i)
            continue
        links = [(bang == "!", tgt) for bang, _, tgt in MD_LINK_RE.findall(line)]
        links += [(attr.lower() == "src", tgt) for attr, tgt in HTML_LINK_RE.findall(line)]
        for is_image, raw in links:
            target = raw.split()[0] if raw.split() else ""  # quita opciones tipo ':size=200'
            target = target.strip("<>")
            if is_image and HEX_COLOR_RE.match(target):
                continue  # docsify: ![color](#f0f0f0) es el color de fondo de la portada
            if target.startswith("("):
                rec.add_check("enlace_mal_formado", i, raw)
                continue
            if not target or SCHEME_RE.match(target):
                continue  # http(s), mailto, etc.
            if "@" in target and "/" not in target:
                rec.add_check("enlace_correo_sin_mailto", i, target)
                continue
            path_part, _, anchor = target.partition("#")
            path_part = path_part.split("?")[0]
            if not path_part:
                dest = file_path
            else:
                dest = resolve_target(path_part, file_path, root)
                if dest is None:
                    is_asset = is_image or Path(path_part).suffix.lower() in IMAGE_EXT
                    tipo = "recurso_ausente" if is_asset else "enlace_roto"
                    rec.add_check(tipo, i, target)
                    continue
            if anchor and dest.suffix == ".md":
                # anclas de docsify '#/pagina?id=x' no aparecen en el corpus; se tratan igual
                if slug_loose(anchor) not in anchors_of(dest, anchor_cache):
                    rec.add_check("ancla_rota", i, target)
    if entity_lines:
        # Un solo aviso por archivo: suelen ser bloques enteros escapados al exportar.
        first = entity_lines[0]
        rec.add_check("entidad_html_en_codigo", first,
                      f"{len(entity_lines)} líneas de código con entidades HTML sin decodificar "
                      f"(líneas {entity_lines[0]}-{entity_lines[-1]}); ej.: {lines[first - 1].strip()[:100]}")


def check_metadata(rec: FileRecord, data: dict) -> dict:
    """documentationTypes.json: compara software/versión de las URLs con la carpeta."""
    info = {}
    for kind, url in data.items():
        m = re.search(r"/([^/]+)/([^/]+)/(?:guide|specs)/", str(url))
        if not m:
            rec.add_check("metadatos_url_irreconocible", None, f"{kind}: {url}")
            continue
        sw, ver = m.groups()
        info[kind] = {"software": sw, "version": ver}
        if sw != rec.software:
            rec.add_check("metadatos_software_distinto", None, f"{kind} apunta a software '{sw}'")
        if ver != rec.version:
            if rec.version == "latest":
                rec.add_check("metadatos_latest_resuelve_a", None, f"{kind}: latest -> {ver}")
            else:
                rec.add_check("metadatos_version_distinta", None,
                              f"{kind}: carpeta '{rec.version}' pero la URL dice '{ver}'")
        if kind == "specifications":
            spec = DOCS_RAW / rec.unit / "specs" / Path(str(url)).name
            if not spec.is_file():
                rec.add_check("metadatos_spec_ausente", None, f"no existe specs/{Path(str(url)).name}")
        if kind == "guide":
            if not (DOCS_RAW / rec.unit / "guide").is_dir():
                rec.add_check("metadatos_guide_ausente", None, "no existe la carpeta guide/")
    return info


def check_empty_sections(rec: FileRecord, sections: list[Section]) -> None:
    for s in sections:
        lines = s.text.split("\n")
        if s.kind.startswith("markdown"):
            lines = [l for l in lines if not HEADING_RE.match(l)]
        if not any(l.strip() for l in lines):
            rec.add_check("seccion_vacia", s.line_start, s.title or s.section_id)


# ---------------------------------------------------------------------------
# Proceso principal
# ---------------------------------------------------------------------------

def iter_units() -> list[Path]:
    return sorted(p for sw in sorted(DOCS_RAW.iterdir()) if sw.is_dir()
                  for p in sorted(sw.iterdir()) if p.is_dir())


def process_file(file_path: Path, unit_dir: Path, anchor_cache: dict) -> tuple[FileRecord, list[Section]]:
    raw = file_path.read_bytes()
    rel = file_path.relative_to(DOCS_RAW).as_posix()
    unit = unit_dir.relative_to(DOCS_RAW).as_posix()
    software, version = unit.split("/")
    ext = file_path.suffix.lower().lstrip(".")
    file_type = {"md": "markdown", "yaml": "openapi", "yml": "openapi", "json": "json"}.get(ext, ext)

    try:
        text = raw.decode("utf-8")
        decode_ok = True
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        decode_ok = False
    lines = read_lines(text)

    rec = FileRecord(path=rel, unit=unit, software=software, version=version,
                     file_type=file_type, sha256=sha256(raw), bytes=len(raw), n_lines=len(lines))
    if not decode_ok:
        rec.parse_ok = False
        rec.add_check("utf8_invalido", None, "el archivo no es UTF-8 válido")

    # Partición
    if not "".join(lines).strip():
        parts = [(1, max(len(lines), 1), "vacio", "")]
        rec.add_check("archivo_vacio", None, "el archivo no tiene contenido")
    elif file_type == "markdown":
        mask = fence_mask(lines)
        parts = split_markdown(lines, mask)
        check_markdown(rec, lines, mask, file_path, unit_dir, anchor_cache)
    elif file_type == "openapi":
        try:
            doc = yaml.safe_load(text)
            if not isinstance(doc, dict) or "paths" not in doc:
                rec.add_check("openapi_sin_paths", None, "el YAML no tiene la clave paths")
        except yaml.YAMLError as e:
            rec.parse_ok = False
            rec.add_check("yaml_invalido", None, str(e).replace("\n", " ")[:200])
        parts = split_openapi(lines)
    elif file_type == "json":
        try:
            data = json.loads(text)
            if file_path.name == "documentationTypes.json" and isinstance(data, dict):
                check_metadata(rec, data)
        except json.JSONDecodeError as e:
            rec.parse_ok = False
            rec.add_check("json_invalido", None, str(e))
        parts = [(1, len(lines), "json", file_path.name)]
    else:
        parts = [(1, len(lines), "otro", file_path.name)]

    file_in_unit = file_path.relative_to(unit_dir).as_posix()
    sections = [
        Section(section_id=f"{unit}/{file_in_unit}#{n}", unit=unit, software=software,
                version=version, file=rel, n=n, kind=kind, title=title,
                line_start=s, line_end=e, text="\n".join(lines[s - 1:e]))
        for n, (s, e, kind, title) in enumerate(parts)
    ]
    check_empty_sections(rec, sections)
    rec.n_sections = len(sections)
    verify_coverage(rec, lines, sections)
    return rec, sections


def verify_coverage(rec: FileRecord, lines: list[str], sections: list[Section]) -> None:
    """Invariante: rangos contiguos, sin solapes, que cubren todas las líneas, y cuyo
    texto concatenado reconstruye el archivo. Si falla, se detiene todo el proceso."""
    expected_start = 1
    for s in sections:
        if s.line_start != expected_start or s.line_end < s.line_start - 1:
            raise SystemExit(f"[error] Partición inválida en {rec.path}: {s.section_id} "
                             f"empieza en {s.line_start}, se esperaba {expected_start}")
        expected_start = s.line_end + 1
    if lines and expected_start != len(lines) + 1:
        raise SystemExit(f"[error] Partición incompleta en {rec.path}: cubre hasta "
                         f"{expected_start - 1} de {len(lines)} líneas")
    if lines and "\n".join(s.text for s in sections) != "\n".join(lines):
        raise SystemExit(f"[error] El texto de las secciones no reconstruye {rec.path}")


def build_units(records: list[FileRecord]) -> list[dict]:
    """Un registro por software/versión, con su huella de contenido y la unidad
    idéntica previa (si existe), de la que heredará las etiquetas."""
    by_unit: dict[str, list[FileRecord]] = {}
    for r in records:
        by_unit.setdefault(r.unit, []).append(r)
    units, seen = [], {}
    for unit, recs in by_unit.items():
        prefix = unit + "/"
        fingerprint = sha256("\n".join(
            f"{r.path[len(prefix):]}:{r.sha256}" for r in sorted(recs, key=lambda r: r.path)))
        software, version = unit.split("/")
        units.append({
            "unit": unit, "software": software, "version": version,
            "n_files": len(recs), "n_sections": sum(r.n_sections for r in recs),
            "bytes": sum(r.bytes for r in recs), "fingerprint": fingerprint,
            "identica_a": seen.get(fingerprint),
        })
        seen.setdefault(fingerprint, unit)
    return units


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    if not DOCS_RAW.is_dir():
        print(f"[error] No existe {DOCS_RAW}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    records: list[FileRecord] = []
    sections: list[Section] = []
    anchor_cache: dict = {}
    for unit_dir in iter_units():
        files = sorted(p for p in unit_dir.rglob("*") if p.is_file() and p.name not in IGNORED_FILES)
        for fp in files:
            rec, secs = process_file(fp, unit_dir, anchor_cache)
            records.append(rec)
            sections.extend(secs)

    # Comprobación global: todos los archivos de docs_raw están en el inventario
    on_disk = {p.relative_to(DOCS_RAW).as_posix() for p in DOCS_RAW.rglob("*")
               if p.is_file() and p.name not in IGNORED_FILES}
    listed = {r.path for r in records}
    if on_disk != listed:
        print(f"[error] Archivos fuera del inventario: {sorted(on_disk - listed)}")
        return 1
    ids = [s.section_id for s in sections]
    if len(ids) != len(set(ids)):
        print("[error] section_id duplicados")
        return 1

    units = build_units(records)
    write_jsonl(OUT_DIR / "units.jsonl", units)
    write_jsonl(OUT_DIR / "inventory.jsonl", [r.__dict__ for r in records])
    write_jsonl(OUT_DIR / "sections.jsonl", [s.to_dict() for s in sections])

    # Resumen
    n_checks: dict[str, int] = {}
    for r in records:
        for c in r.checks:
            n_checks[c["tipo"]] = n_checks.get(c["tipo"], 0) + 1
    print(f"Unidades software/versión: {len(units)}")
    print(f"Archivos inventariados:    {len(records)} (todos los de docs_raw/)")
    print(f"Secciones:                 {len(sections)} (cubren el 100% de las líneas)")
    for u in units:
        if u["identica_a"]:
            print(f"Idéntica:                  {u['unit']} = {u['identica_a']} (heredará etiquetas)")
    print("Chequeos deterministas:")
    for tipo, n in sorted(n_checks.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {tipo}")
    print(f"Salidas en {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
