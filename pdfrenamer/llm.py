"""Opcionális: a PDF első oldalának szövege a Claude API-nak (csak ha a felhasználó kéri és van ANTHROPIC_API_KEY)."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date

from .classify import TYPES, Fields
from .extract import PdfInfo
from .lookup import NetError

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_CHARS = 6000

_SYSTEM = (
    "Egy PDF első oldalainak szövegéből kell a fájl átnevezéséhez adatokat kinyerned. "
    "Csak egyetlen JSON-objektumot adj vissza, magyarázat nélkül, ezekkel a kulcsokkal: "
    '{"kind": "article|' + "|".join(TYPES) + '|other", "title": str, "authors": [családnevek], "year": int|null, '
    '"date": "YYYY-MM-DD"|null, "issuer": str, "reference": str, "dated": bool}. '
    "Cikknél (tudományos közlemény) a title a cikk címe, az authors a szerzők családnevei, a year a megjelenés éve. "
    "Számlánál, szerződésnél, igazolásnál, levélnél stb. a date a dokumentum kiállításának napja, az issuer a kiállító "
    "(cég/intézmény) rövid neve, a reference a számlaszám/hivatkozási szám/levél tárgya. "
    "Minden más dokumentumnál kind=other, a title 3-8 szavas, a tartalmat jól leíró cím a dokumentum nyelvén; "
    "dated csak akkor true, ha a dátum a dokumentum azonosításához lényeges. Ismeretlen mező: üres string / null."
)


def api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def describe(info: PdfInfo, timeout: float = 40) -> Fields | None:
    key = api_key()
    if not key:
        return None
    text = info.text.strip()[:MAX_CHARS]
    if not text:
        return None
    body = {
        "model": os.environ.get("PDFRENAMER_MODEL", DEFAULT_MODEL),
        "max_tokens": 500,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": f"Fájlnév: {info.path.name}\nPDF cím-metaadat: {info.meta_title}\n\n{text}"}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise NetError(f"Claude API: {e}") from e
    out = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")
    return parse_reply(out)


def parse_reply(out: str) -> Fields | None:
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    kind = d.get("kind") if d.get("kind") in TYPES or d.get("kind") in ("article", "other") else "other"
    when = None
    if d.get("date"):
        try:
            when = date.fromisoformat(str(d["date"])[:10])
        except ValueError:
            pass
    year = d.get("year")
    f = Fields(
        kind=kind,
        title=str(d.get("title") or ""),
        authors=[str(a) for a in (d.get("authors") or []) if a],
        year=int(year) if isinstance(year, int) or (isinstance(year, str) and year.isdigit()) else None,
        date=when,
        issuer=str(d.get("issuer") or ""),
        ref=str(d.get("reference") or ""),
        dated=bool(kind in TYPES or (kind == "other" and d.get("dated"))),
    )
    return f
