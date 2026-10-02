"""Fájlnév-segédek: tisztítás, névséma, és annak eldöntése, hogy egy név "azonosítható"-e."""
from __future__ import annotations

import html
import os
import re
import unicodedata
from pathlib import Path

MAX_STEM = 150
MAX_TITLE = 110
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def strip_markup(text: str) -> str:
    """HTML/JATS címkék és entitások eltávolítása (a Crossref címek tele vannak velük)."""
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def sanitize(text: str, max_len: int = MAX_STEM) -> str:
    """Windows-barát fájlnév-törzs (kiterjesztés nélkül)."""
    s = unicodedata.normalize("NFC", strip_markup(text))
    s = re.sub(r":\s+", " - ", s)
    s = s.replace(":", "-").replace('"', "'")
    s = re.sub(r"[\\/|]", "-", s)
    s = re.sub(r"[<>?*\x00-\x1f]", "", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(?:\s*-\s*){2,}", " - ", s)
    s = s.strip(" .-")
    if len(s) > max_len:
        cut = s[:max_len]
        if " " in cut[max_len // 2:]:
            cut = cut[:cut.rfind(" ")]
        s = cut.rstrip(" .-,;")
    if s.upper() in _RESERVED:
        s += "_"
    return s


def article_stem(authors: list[str], year: int | None, title: str) -> str:
    """'Smith 2020 - Cím', 'Smith & Jones 2020 - Cím', 'Smith et al 2020 - Cím'."""
    names = [sanitize(a, 40) for a in authors if a and a.strip()]
    if not names:
        who = ""
    elif len(names) == 1:
        who = names[0]
    elif len(names) == 2:
        who = f"{names[0]} & {names[1]}"
    else:
        who = f"{names[0]} et al"
    head = " ".join(p for p in (who, str(year) if year else "") if p)
    title = sanitize(title, MAX_TITLE)
    stem = f"{head} - {title}" if head and title else (head or title)
    return sanitize(stem)


# --- "azonosítható-e a fájlnév?" -------------------------------------------------

_WHO = r"[^\W\d_][\w'’.&\- ]{0,80}?"
_ARTICLE_RE = re.compile(rf"^{_WHO} (?:19|20)\d\d - \S.{{4,}}$")
_DATED_RE = re.compile(r"^(?:19|20)\d\d-\d{2}-\d{2} - \S.{2,}$")
_YEAR_RE = re.compile(r"^(?:19|20)\d\d - \S.{4,}$")

_GENERIC = {
    "scan", "scanned", "scanner", "document", "doc", "untitled", "download", "downloads",
    "fulltext", "full", "text", "main", "paper", "article", "file", "pdf", "new", "img",
    "image", "print", "export", "output", "copy", "final", "draft", "manuscript",
    "dokumentum", "szkennelés", "névtelen", "nevtelen", "unbenannt", "dokument",
    "attachment", "mellékelt", "csatolmány", "bill", "invoice",
}


def is_well_named(stem: str) -> bool:
    """A program saját sémái szerint elnevezett fájl."""
    return bool(_ARTICLE_RE.match(stem) or _DATED_RE.match(stem) or _YEAR_RE.match(stem))


def looks_meaningful(stem: str) -> bool:
    """Emberi, beszédes név (legalább 3 valódi szó), nem DOI/hash/'scan0012'-szerű."""
    s = re.sub(r"\s*\(\d+\)$", "", stem)
    s = re.sub(r"(?<=[a-zà-ű])(?=[A-ZÀ-Ű])", " ", s)  # CamelCase szétvágás
    words = [w for w in re.findall(r"[^\W\d_]{3,}", s) if w.lower() not in _GENERIC]
    if len(words) < 3:
        return False
    letters = sum(c.isalpha() for c in s)
    return letters / max(1, len(s)) >= 0.6


def is_identifiable(stem: str) -> bool:
    return is_well_named(stem) or looks_meaningful(stem)


# --- ütközéskezelés --------------------------------------------------------------

def unique_path(folder: Path, stem: str, ext: str, taken: set[str], own: Path | None = None) -> Path:
    """Szabad célnév; ' (2)', ' (3)' ... ha foglalt. `taken`: már tervezett célok (kisbetűs)."""
    folder = Path(folder)
    max_stem = max(20, 250 - len(str(folder)) - len(ext) - 8)
    stem = stem[:max_stem].rstrip(" .")
    n = 1
    while True:
        name = f"{stem}{'' if n == 1 else f' ({n})'}{ext}"
        cand = folder / name
        key = str(cand).lower()
        free = key not in taken
        if free and cand.exists():
            free = own is not None and _same_file(cand, own)
        if free:
            return cand
        n += 1


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False
