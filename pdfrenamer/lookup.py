"""Online metaadat-lekérdezés: Crossref, doi.org (DataCite stb.), arXiv, Crossref címkeresés."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from difflib import SequenceMatcher

UA = "PdfRenamer/1.0"


class NetError(Exception):
    """Hálózati hiba (offline, időtúllépés, tartós szerverhiba)."""


@dataclass
class Bib:
    title: str
    authors: list[str] = field(default_factory=list)   # családnevek
    year: int | None = None
    doi: str | None = None
    source: str = ""
    type: str | None = None


def _get(url: str, headers: dict | None = None, timeout: float = 12, mailto: str = "") -> bytes | None:
    h = {"User-Agent": f"{UA} (mailto:{mailto})" if mailto else UA}
    h.update(headers or {})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt == 1:
                time.sleep(2)
                continue
            raise NetError(f"HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise NetError(str(e)) from e
    return None


def _fix_case(name: str) -> str:
    name = name.strip()
    return name.title() if name.isupper() and len(name) > 3 else name


def _year(item: dict) -> int | None:
    for key in ("issued", "published-print", "published-online", "published"):
        dp = (item.get(key) or {}).get("date-parts") or [[None]]
        if dp and dp[0] and dp[0][0]:
            try:
                return int(dp[0][0])
            except (TypeError, ValueError):
                continue
    return None


def _from_json(m: dict, source: str) -> Bib | None:
    title = m.get("title")
    title = title[0] if isinstance(title, list) and title else (title or "")
    if not title:
        return None
    authors = []
    for a in m.get("author") or m.get("editor") or []:
        fam = a.get("family") or a.get("name") or a.get("literal") or ""
        if fam:
            authors.append(_fix_case(fam))
    doi = m.get("DOI")
    return Bib(title=title, authors=authors, year=_year(m), doi=doi, source=source, type=m.get("type"))


def by_doi(doi: str, mailto: str = "") -> Bib | None:
    q = urllib.parse.quote(doi, safe="/()")
    raw = _get(f"https://api.crossref.org/works/{q}", mailto=mailto)
    if raw:
        try:
            bib = _from_json(json.loads(raw)["message"], f"Crossref DOI ({doi})")
            if bib:
                return bib
        except (ValueError, KeyError):
            pass
    # Nem Crossref-DOI (pl. DataCite) – a doi.org tartalom-egyeztetéssel mindkettőt tudja
    raw = _get(f"https://doi.org/{q}", {"Accept": "application/vnd.citationstyles.csl+json"}, mailto=mailto)
    if raw:
        try:
            return _from_json(json.loads(raw), f"doi.org ({doi})")
        except ValueError:
            return None
    return None


def by_arxiv(arxiv_id: str, mailto: str = "") -> Bib | None:
    raw = _get(f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}", mailto=mailto)
    if not raw:
        return None
    try:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entry = ET.fromstring(raw).find("a:entry", ns)
        if entry is None:
            return None
        title = re.sub(r"\s+", " ", entry.findtext("a:title", "", ns)).strip()
        if not title or title.lower() == "error":
            return None
        authors = [n.strip().split()[-1] for n in
                   (a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)) if n.strip()]
        published = entry.findtext("a:published", "", ns)
        year = int(published[:4]) if published[:4].isdigit() else None
        return Bib(title=title, authors=authors, year=year, source=f"arXiv ({arxiv_id})", type="preprint")
    except ET.ParseError:
        return None


def search_title(title: str, mailto: str = "", min_ratio: float = 0.92) -> Bib | None:
    q = urllib.parse.quote(title[:250])
    raw = _get(f"https://api.crossref.org/works?query.bibliographic={q}&rows=3"
               f"&select=DOI,title,author,issued,published-print,published-online,type", mailto=mailto)
    if not raw:
        return None
    try:
        items = json.loads(raw)["message"]["items"]
    except (ValueError, KeyError):
        return None
    best, best_ratio = None, 0.0
    for it in items:
        bib = _from_json(it, "Crossref címkeresés")
        if bib:
            r = similarity(title, bib.title)
            if r > best_ratio:
                best, best_ratio = bib, r
    if best and best_ratio >= min_ratio:
        best.source = f"Crossref címkeresés ({best_ratio:.0%}, DOI {best.doi})"
        return best
    return None


# --- egyezés-ellenőrzés ------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def title_in_text(title: str, text: str, min_fraction: float = 0.6) -> bool:
    """Igaz, ha a cím szavainak legalább 60%-a szerepel a PDF szövegében – ez szűri ki a hivatkozott cikkek DOI-it."""
    words = {w for w in _norm(title).split() if len(w) >= 3}
    if not words:
        return True
    have = set(_norm(text).split())
    return len(words & have) / len(words) >= min_fraction
