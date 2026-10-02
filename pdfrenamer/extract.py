"""PDF beolvasás: metaadatok, az első oldalak szövege, cím-tipp (legnagyobb betűméret), DOI/arXiv azonosítók."""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

logging.getLogger("pypdf").setLevel(logging.CRITICAL)

TEXT_PAGES = 3
MIN_TEXT_CHARS = 50

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)
_DOI_GLUE = re.compile(r"(?<=[0-9a-z])(?=(?:Received|Accepted|Published|Copyright|Available|"
                       r"Article|Citation|Keywords|Abstract|Corresponding|Journal|Online|©|https?:|www\.))")
ARXIV_RE = re.compile(r"arXiv:\s*((?:\d{4}\.\d{4,5})|(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7}))(?:v\d+)?", re.I)
ARXIV_DOI_RE = re.compile(r"10\.48550/arXiv\.(\d{4}\.\d{4,5})", re.I)


@dataclass
class PdfInfo:
    path: Path
    n_pages: int = 0
    meta_title: str = ""
    meta_author: str = ""
    created: datetime | None = None
    meta_blob: str = ""                 # az összes metaadat-mező + XMP egyben (DOI kereséshez)
    page_texts: list[str] = field(default_factory=list)
    title_guess: str = ""               # az 1. oldal legnagyobb betűméretű szövege
    error: str = ""

    @property
    def text(self) -> str:
        return "\n".join(self.page_texts)

    @property
    def scanned(self) -> bool:
        return len(self.text.strip()) < MIN_TEXT_CHARS


def read_pdf(path: Path, max_pages: int = TEXT_PAGES) -> PdfInfo:
    info = PdfInfo(path=Path(path))
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                pass
        info.n_pages = len(reader.pages)
    except Exception as e:  # sérült / jelszóvédett PDF
        info.error = f"nem olvasható PDF ({type(e).__name__}: {e})"
        return info

    try:
        md = reader.metadata
        if md:
            info.meta_title = str(md.title or "").strip()
            info.meta_author = str(md.author or "").strip()
            try:
                info.created = md.creation_date
            except Exception:
                pass
            info.meta_blob = " ".join(str(v) for v in md.values() if isinstance(v, str))
    except Exception:
        pass
    try:
        xmp = reader.root_object.get("/Metadata")
        if xmp is not None:
            info.meta_blob += " " + xmp.get_object().get_data().decode("utf-8", "ignore")
    except Exception:
        pass

    for i in range(min(info.n_pages, max_pages)):
        try:
            page = reader.pages[i]
            if i == 0:
                chunks: list[tuple[str, float]] = []

                def visitor(text, cm, tm, font_dict, font_size, _c=chunks):
                    if text and text.strip():
                        size = (font_size or 1) * math.hypot(tm[2], tm[3]) * math.hypot(cm[2], cm[3])
                        _c.append((text, round(size, 1)))

                info.page_texts.append(page.extract_text(visitor_text=visitor) or "")
                info.title_guess = _title_from_chunks(chunks)
            else:
                info.page_texts.append(page.extract_text() or "")
        except Exception:
            info.page_texts.append("")
    return info


def _title_from_chunks(chunks: list[tuple[str, float]]) -> str:
    """Az egymás melletti, azonos méretű szövegdarabokat blokkba fűzi; a legnagyobb értelmes blokk a cím-tipp."""
    blocks: list[tuple[float, str]] = []
    for text, size in chunks:
        if blocks and abs(blocks[-1][0] - size) <= 0.5:
            blocks[-1] = (blocks[-1][0], blocks[-1][1] + " " + text.strip())
        else:
            blocks.append((size, text.strip()))
    best = ""
    best_size = 0.0
    for size, text in blocks:
        text = re.sub(r"\s+", " ", text).strip()
        letters = sum(c.isalpha() for c in text)
        if len(text.split()) >= 3 and letters >= 12 and size > best_size:
            best, best_size = text, size
    return best[:300]


# --- azonosítók ------------------------------------------------------------------

def _trim_doi(s: str) -> str:
    while s and (s[-1] in ".,;:'\"]}>" or (s[-1] == ")" and s.count("(") < s.count(")"))):
        s = s[:-1]
    return s


def find_dois(*texts: str) -> list[str]:
    """DOI-jelöltek előfordulási sorrendben; a "rátapadt" szöveges változatot is felveszi."""
    seen: dict[str, None] = {}
    for text in texts:
        for m in DOI_RE.finditer(text or ""):
            raw = m.group(0)
            variants = [_trim_doi(raw)]
            cut = _DOI_GLUE.split(raw, maxsplit=1)[0]
            if cut != raw:
                variants.append(_trim_doi(cut))
            for v in variants:
                if len(v) > 8:
                    seen.setdefault(v, None)
    out: dict[str, None] = {}
    for d in seen:  # kis/nagybetű-duplikátumok kiszűrése
        if d.lower() not in {x.lower() for x in out}:
            out[d] = None
    return list(out)


def find_arxiv_ids(*texts: str) -> list[str]:
    ids: dict[str, None] = {}
    for text in texts:
        for m in ARXIV_RE.finditer(text or ""):
            ids.setdefault(m.group(1), None)
        for m in ARXIV_DOI_RE.finditer(text or ""):
            ids.setdefault(m.group(1), None)
    return list(ids)


_BAD_TITLE = re.compile(r"(microsoft (word|powerpoint|excel)|\.docx?\b|\.pdf\b|^untitled|^document\d*$|^scan|pdfcreator|\.indd)", re.I)


def clean_meta_title(t: str) -> str:
    """A PDF-metaadat 'Title' mezője sokszor szemét; csak az értelmes címet adja vissza."""
    t = re.sub(r"^\s*Microsoft Word\s*-\s*", "", t or "", flags=re.I).strip()
    if _BAD_TITLE.search(t):
        return ""
    if len(t) < 12 or len(t.split()) < 3 or sum(c.isalpha() for c in t) < 8:
        return ""
    return t
