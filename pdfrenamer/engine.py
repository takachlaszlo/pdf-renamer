"""Az átnevezési folyamat: mappa-bejárás, elemzés, alkalmazás, visszavonás, beállítások."""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from . import llm, lookup
from .classify import Fields, compose_name, guess_fields, looks_like_article
from .extract import PdfInfo, clean_meta_title, find_arxiv_ids, find_dois, read_pdf
from .lookup import NetError, title_in_text
from .naming import is_identifiable, unique_path

if os.name == "nt":
    APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "PdfRenamer"
else:  # Linux/macOS: XDG
    APP_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "pdfrenamer"
DEFAULT_FOLDER = Path.home()   # a "munkamappa": C:\Users\<felhasználó>

# A teljes profilmappa bejárásakor ezeket kihagyjuk
EXCLUDE_DIRS = {
    "appdata", "node_modules", "venv", ".venv", "site-packages", "__pycache__", "$recycle.bin",
    "system volume information", "windows", "program files", "program files (x86)", "programdata",
    "application data", "local settings", "snap",
}
_ATTR_SKIP_DIR = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM | stat.FILE_ATTRIBUTE_REPARSE_POINT
_ATTR_CLOUD_ONLY = 0x00400000 | 0x00001000   # RECALL_ON_DATA_ACCESS | OFFLINE (pl. OneDrive "csak online")


@dataclass
class Options:
    recursive: bool = True
    force_all: bool = False     # a már azonosítható nevűeket is átvizsgálja
    use_llm: bool = False
    online: bool = True
    mailto: str = ""


@dataclass
class Result:
    path: Path
    new_stem: str | None
    kind: str
    source: str
    status: str                 # "ok" | "rename" | "unknown" | "error" | "skip"
    note: str = ""
    warn: bool = False          # bizonytalan (pl. dátum nélkül) – alapból nincs kijelölve


# --- mappabejárás ----------------------------------------------------------------

def _attrs(p: str) -> int:
    try:
        return os.stat(p, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return 0


def _skip_dir(parent: str, name: str) -> bool:
    if name.lower() in EXCLUDE_DIRS or name.startswith("."):
        return True
    return bool(_attrs(os.path.join(parent, name)) & _ATTR_SKIP_DIR)


def scan_pdfs(folder: Path | str, recursive: bool = True) -> list[Path]:
    out: list[Path] = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [] if not recursive else sorted(d for d in dirs if not _skip_dir(root, d))
        out += [Path(root) / f for f in sorted(files) if f.lower().endswith(".pdf")]
    return out


def is_cloud_only(path: Path) -> bool:
    return bool(_attrs(str(path)) & _ATTR_CLOUD_ONLY)


# --- elemzés ---------------------------------------------------------------------

def _article_lookup(info: PdfInfo, opts: Options, notes: list[str]) -> tuple[Fields, str] | None:
    """DOI -> arXiv -> címkeresés. NetError-t dob, ha nincs hálózat."""
    verify = not info.scanned
    for doi in find_dois(info.meta_blob, *info.page_texts)[:5]:
        bib = lookup.by_doi(doi, opts.mailto)
        if bib and (not verify or title_in_text(bib.title, info.text)):
            return Fields("article", bib.title, bib.authors, bib.year), bib.source
        if bib:
            notes.append(f"a(z) {doi} DOI másik műé lehet (a címe nincs a szövegben) – kihagyva")
    for aid in find_arxiv_ids(info.meta_blob, *info.page_texts)[:2]:
        bib = lookup.by_arxiv(aid, opts.mailto)
        if bib and (not verify or title_in_text(bib.title, info.text)):
            return Fields("article", bib.title, bib.authors, bib.year), bib.source
    # Címkeresés: csak ha a PDF tudományos cikknek látszik – más dokumentum (pl. betegirat) címe nem hagyja el a gépet
    if not looks_like_article(info.text):
        return None
    for title in dict.fromkeys(t for t in (clean_meta_title(info.meta_title), info.title_guess) if t):
        bib = lookup.search_title(title, opts.mailto)
        if bib:
            return Fields("article", bib.title, bib.authors, bib.year), bib.source
    return None


def _result_from_fields(path: Path, f: Fields, source: str, notes: list[str]) -> Result:
    stem = compose_name(f)
    if not stem:
        return Result(path, None, "–", source, "unknown", "; ".join(notes + ["nem sikerült értelmes nevet képezni"]))
    kind = "cikk" if f.kind == "article" else (f.label.lower() or "egyéb")
    warn = False
    if f.date_note:
        notes.append(f.date_note)
        warn = True
    if f.dated and not f.date:
        notes.append("nem találtam dátumot")
        warn = True
    if f.kind == "article" and not f.authors:
        notes.append("szerző nélkül")
        warn = True
    if f.kind == "other" and not f.dated:
        warn = True  # csak cím-tipp alapján, nézd át
    return Result(path, stem, kind, source, "rename", "; ".join(notes), warn)


def analyze(path: Path, opts: Options) -> Result:
    path = Path(path)
    stem = path.stem
    if not opts.force_all and is_identifiable(stem):
        return Result(path, None, "–", "fájlnév", "ok", "a fájlnév már azonosítható")
    if is_cloud_only(path):
        return Result(path, None, "–", "", "skip", "felhő-only fájl (OneDrive) – nem töltöm le, töltsd le előbb")

    info = read_pdf(path)
    if info.error:
        return Result(path, None, "–", "", "error", info.error)

    notes: list[str] = []
    offline = False
    if opts.online:
        try:
            hit = _article_lookup(info, opts, notes)
            if hit:
                return _result_from_fields(path, hit[0], hit[1], notes)
        except NetError as e:
            offline = True
            notes.append(f"hálózati hiba ({e}) – csak helyi adatok")

    fields, source = None, "tartalom"
    if opts.use_llm and llm.api_key() and not info.scanned:
        try:
            fields = llm.describe(info)
            source = "Claude"
        except NetError as e:
            notes.append(str(e))
    if not fields:
        fields, source = guess_fields(info), "tartalom"
    if not fields:
        why = ("szkennelt PDF (nincs szöveg), OCR nélkül nem azonosítható" if info.scanned
               else "nem sikerült azonosítani")
        return Result(path, None, "–", "", "unknown", "; ".join(notes + [why]))
    if offline and fields.kind == "article":
        notes.append("DOI/cím nem ellenőrizhető offline")
    return _result_from_fields(path, fields, source, notes)


def analyze_all(folder: Path | str, opts: Options,
                progress: Callable[[int, int, Path], None] | None = None,
                should_stop: Callable[[], bool] = lambda: False) -> Iterator[Result]:
    files = scan_pdfs(folder, opts.recursive)
    for i, f in enumerate(files, 1):
        if should_stop():
            return
        if progress:
            progress(i, len(files), f)
        try:
            yield analyze(f, opts)
        except Exception as e:  # egy hibás fájl ne állítsa meg az egészet
            yield Result(f, None, "–", "", "error", f"{type(e).__name__}: {e}")


# --- alkalmazás / visszavonás ----------------------------------------------------

def apply(items: list[tuple[Path, str]]) -> tuple[list[tuple[Path, Path]], list[tuple[Path, str]], Path | None]:
    """(régi útvonal, új törzs) párok átnevezése. Visszaad: (sikeresek, hibák, napló-fájl)."""
    done: list[tuple[Path, Path]] = []
    errors: list[tuple[Path, str]] = []
    taken: set[str] = set()
    for old, stem in items:
        try:
            new = unique_path(old.parent, stem, old.suffix, taken, own=old)
            taken.add(str(new).lower())
            if new != old:
                os.rename(old, new)
            done.append((old, new))
        except OSError as e:
            errors.append((old, str(e)))
    log = None
    if done:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        log = APP_DIR / f"undo-{datetime.now():%Y%m%d-%H%M%S}.json"
        log.write_text(json.dumps({"time": datetime.now().isoformat(timespec="seconds"),
                                   "items": [{"old": str(o), "new": str(n)} for o, n in done]},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    return done, errors, log


def latest_undo_log() -> Path | None:
    logs = sorted(APP_DIR.glob("undo-*.json")) if APP_DIR.exists() else []
    return logs[-1] if logs else None


def undo(log: Path) -> tuple[int, list[str]]:
    data = json.loads(Path(log).read_text(encoding="utf-8"))
    ok, problems = 0, []
    for it in reversed(data["items"]):
        old, new = Path(it["old"]), Path(it["new"])
        if old == new:
            continue
        if not new.exists():
            problems.append(f"{new.name}: már nincs meg")
        elif old.exists() and not os.path.samefile(old, new):
            problems.append(f"{old.name}: az eredeti név foglalt")
        else:
            try:
                os.rename(new, old)
                ok += 1
            except OSError as e:
                problems.append(f"{new.name}: {e}")
    Path(log).rename(Path(log).with_suffix(".done.json"))
    return ok, problems


# --- beállítások -----------------------------------------------------------------

_SETTINGS = APP_DIR / "settings.json"
_DEFAULTS = {"folder": str(DEFAULT_FOLDER), "recursive": True, "auto_scan": True, "force_all": False,
             "use_llm": False, "mailto": ""}


def load_settings() -> dict:
    try:
        return {**_DEFAULTS, **json.loads(_SETTINGS.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(_DEFAULTS)


def save_settings(s: dict) -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        _SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
