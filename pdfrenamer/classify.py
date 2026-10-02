"""Tartalom-alapú felismerés DOI nélküli PDF-ekhez: dokumentumtípus, dátum, kiállító, hivatkozási szám, cím."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .extract import PdfInfo, clean_meta_title
from .naming import MAX_TITLE, article_stem, sanitize


@dataclass
class Fields:
    kind: str                       # "article" | TYPES kulcs | "other"
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    date: date | None = None
    date_note: str = ""             # honnan jött a dátum (ha nem a "kiállítás kelte" címke)
    issuer: str = ""
    ref: str = ""                   # számlaszám, tárgy, stb.
    dated: bool = False

    @property
    def label(self) -> str:
        return TYPES[self.kind][0] if self.kind in TYPES else ""


# kulcs: (magyar címke, [(minta, súly)]) – a legnagyobb pontszám nyer, küszöb: THRESHOLD
THRESHOLD = 3
TYPES: dict[str, tuple[str, list[tuple[str, int]]]] = {
    "invoice": ("Számla", [
        (r"számla|invoice|rechnung|facture|fattura", 3),
        (r"fizetési határidő|due date|zahlungsziel|fälligkeit|payment terms|fizetési mód|zahlungsbedingungen", 1),
        (r"\báfa\b|\bvat\b|\bmwst|umsatzsteuer|ust-id|adószám|tax id", 1),
        (r"bruttó|nettó|\bgross\b|\bnetto\b|\bbrutto\b|subtotal|\bsumme\b", 1),
        (r"számla sorszáma|invoice (?:no|number)|rechnungs(?:nummer|nr)", 2),
    ]),
    "receipt": ("Nyugta", [
        (r"nyugta|receipt|quittung|kassenbon|pénztárbizonylat", 3),
        (r"fizetve|\bpaid\b|bezahlt|készpénz|\bcash\b|kártya|\bcard\b|\bec-karte", 1),
        (r"összesen|\btotal\b|gesamt", 1),
    ]),
    "order": ("Megrendelés", [
        (r"megrendelés|visszaigazolás|order confirmation|bestellung|auftragsbestätigung|order (?:no|number)", 3),
        (r"szállítás|delivery|lieferung|versand|shipping", 1),
    ]),
    "offer": ("Árajánlat", [
        (r"árajánlat|quotation|\bangebot\b|price quote|kostenvoranschlag|ajánlat", 3),
        (r"érvényes|valid until|gültig bis", 1),
    ]),
    "contract": ("Szerződés", [
        (r"szerződés|contract|agreement|\bvertrag\b|vereinbarung", 3),
        (r"\bfelek\b|\bparty\b|\bparties\b|vertragspartner|aláírás|signature|unterschrift|hatály|jogosult", 1),
    ]),
    "statement": ("Kivonat", [
        (r"számlakivonat|kontoauszug|account statement|bank statement|statement of account|kivonat", 3),
        (r"egyenleg|\bbalance\b|\bsaldo\b|tranzakció|buchung|\biban\b", 1),
    ]),
    "payslip": ("Bérjegyzék", [
        (r"bérjegyzék|fizetési jegyzék|payslip|lohnabrechnung|gehaltsabrechnung|lohnzettel", 3),
        (r"nettó bér|bruttó bér|\bgehalt\b|\blohn\b|járulék|\bnet pay\b", 1),
    ]),
    "tax": ("Adóügy", [
        (r"adóbevallás|személyi jövedelemadó|\bszja\b|steuerbescheid|steuererklärung|tax return|adóigazolás|adóhatóság", 3),
        (r"\bnav\b|adóazonosító|finanzamt|steuernummer", 1),
    ]),
    "insurance": ("Biztosítás", [
        (r"biztosítás|kötvény|insurance|\bpolicy\b|versicherung|\bpolice\b", 3),
        (r"biztosított|díj|prémium|premium|prämie|schaden|kár", 1),
    ]),
    "certificate": ("Igazolás", [
        (r"igazolás|igazolvány|bizonyítvány|certificate|zertifikat|bescheinigung|oklevél|diploma|tanúsítvány", 3),
        (r"igazoljuk|certify|hereby|bestätigen wir", 1),
    ]),
    "medical": ("Orvosi lelet", [
        (r"zárójelentés|\blelet\b|epikrízis|arztbrief|\bbefund\b|discharge summary|ambuláns|kórlap", 3),
        (r"diagnózis|diagnosis|diagnose|anamnézis|anamnese|terápia|therapie|therapy", 1),
    ]),
    "ticket": ("Jegy", [
        (r"\bjegy\b|\bticket\b|boarding pass|fahrkarte|buchungsbestätigung|foglalás|booking|reservation", 3),
        (r"utazás|flight|\bzug\b|\bvonat\b|\bgate\b|ülés|seat", 1),
    ]),
    "letter": ("Levél", [
        (r"tisztelt|sehr geehrte|\bdear (?:sir|madam|mr|ms|mrs|dr|prof)", 2),
        (r"\btárgy\s*:|\bbetreff\s*:|\bsubject\s*:|\bref\s*:|iktatószám|geschäftszeichen", 2),
        (r"üdvözlettel|tisztelettel|mit freundlichen grüßen|sincerely|best regards|yours faithfully", 1),
    ]),
}


def score_types(text: str) -> dict[str, int]:
    low = text.lower()
    return {k: sum(w for pat, w in pats if re.search(pat, low)) for k, (_, pats) in TYPES.items()}


def classify_type(text: str) -> str | None:
    scores = score_types(text)
    best = max(scores, key=lambda k: scores[k])  # döntetlennél a TYPES sorrendje
    return best if scores[best] >= THRESHOLD else None


def looks_like_article(text: str) -> bool:
    low = text.lower()
    if not re.search(r"\babstract\b|összefoglaló|zusammenfassung|\bresumen\b", low):
        return False
    return sum(bool(re.search(p, low)) for p in
               (r"\breferences\b|bibliography|irodalom|literatur", r"\bkeywords?\b|kulcsszavak|schlüsselwörter",
                r"\bintroduction\b|bevezetés|einleitung", r"\bdoi\b", r"\bjournal\b|folyóirat|zeitschrift")) >= 2


# --- dátumok ---------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "már": 3, "mar": 3, "mär": 3, "apr": 4, "ápr": 4, "máj": 5, "maj": 5, "may": 5, "mai": 5,
    "jún": 6, "jun": 6, "júl": 7, "jul": 7, "aug": 8, "szep": 9, "sep": 9, "okt": 10, "oct": 10,
    "nov": 11, "dec": 12, "dez": 12,
}
_Y = r"(?P<y>(?:19|20)\d{2})"
_DATE_PATTERNS = [
    re.compile(_Y + r"\s*[.\-/]\s*(?P<m>\d{1,2})\s*[.\-/]\s*(?P<d>\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(?P<d>\d{1,2})\s*[.\-/]\s*(?P<m>\d{1,2})\s*[.\-/]\s*" + _Y + r"(?!\d)"),
    re.compile(_Y + r"\.?\s*(?P<mn>[^\W\d_]{3,10})\.?\s*(?P<d>\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(?P<d>\d{1,2})\.?\s*(?P<mn>[^\W\d_]{3,10})\.?,?\s*" + _Y + r"(?!\d)"),
    re.compile(r"(?P<mn>[^\W\d_]{3,10})\.?\s*(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s*" + _Y + r"(?!\d)"),
]


def _month(name: str) -> int | None:
    n = name.lower()
    return _MONTHS.get(n[:4]) or _MONTHS.get(n[:3])


def find_dates(text: str) -> list[tuple[int, date]]:
    """Minden felismert dátum (pozíció, dátum), pozíció szerint rendezve, átfedés nélkül."""
    found: dict[int, tuple[int, date]] = {}
    this_year = date.today().year
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            g = m.groupdict()
            mon = _month(g["mn"]) if g.get("mn") else int(g["m"])
            if not mon:
                continue
            try:
                d = date(int(g["y"]), mon, int(g["d"]))
            except ValueError:
                continue
            if not 1990 <= d.year <= this_year + 1:
                continue
            if not any(abs(m.start() - p) < 4 for p in found):
                found[m.start()] = (m.start(), d)
    return sorted(found.values())


_STRONG_DATE_LABEL = re.compile(
    r"számla kelte|kiállítás(?:\s*(?:dátuma|kelte|napja))?|kiállítva|invoice date|date of issue|issue date|issued"
    r"|rechnungsdatum|ausstellungsdatum|ausgestellt am|belegdatum|dokumentum kelte", re.I)
_WEAK_DATE_LABEL = re.compile(r"\bkelt(?:e)?\b|\bdatum\b|\bdate\b|\bdátum\b", re.I)
_NOT_ISSUE_CTX = re.compile(r"due|payment|fizet|teljesít|esedék|fällig|zahl|deliver|szállít|liefer|leistung|valid|érvényes|gültig", re.I)


def find_issue_date(text: str) -> tuple[date | None, str]:
    """(dátum, forrás-megjegyzés). A címkézett dátumot részesíti előnyben, utána az első dátumot a szövegben."""
    for pat, strong in ((_STRONG_DATE_LABEL, True), (_WEAK_DATE_LABEL, False)):
        for m in pat.finditer(text):
            line_ctx = text[max(0, m.start() - 25):m.end()].splitlines()[-1]  # csak az adott sor, az előzőt nem
            if not strong and _NOT_ISSUE_CTX.search(line_ctx):
                continue
            hits = [(p, d) for p, d in find_dates(text[m.end():m.end() + 45]) if p < 45]
            if hits:
                return hits[0][1], ""
    head = find_dates(text[:3000])
    if head:
        return head[0][1], "dátum: első dátum a szövegben"
    return None, ""


# --- kiállító, azonosító, tárgy ---------------------------------------------------

_LEGAL = (r"(?:Kft|KFT|Zrt|ZRT|Nyrt|Bt|BT|Kkt|GmbH|AG|KG|Ltd|LLC|Inc|Corp|S\.A|Sàrl|Sarl|B\.V|BV|plc|e\.U)")
_LEGAL_RE = re.compile(rf"(.{{2,70}}?\b{_LEGAL}\b\.?)")
_ISSUER_LABEL = re.compile(
    r"^\s*(?:Eladó|Szállító|Kibocsátó|Számlakibocsátó|Supplier|Seller|Vendor|Issued by|Rechnungssteller|Lieferant)"
    r"\s*[:\-]?\s*(.*)$", re.I | re.M)
_BUYER_MARK = re.compile(r"vevő|buyer|customer|bill to|rechnungsempfänger|kunde|megrendelő", re.I)
_DOMAIN_RE = re.compile(r"(?:www\.)([a-z0-9\-]{3,30})\.(?:hu|com|de|ch|at|eu|org|net)\b", re.I)
_INV_NO_RE = re.compile(
    r"(?:számla\s*(?:sorszáma|száma|szám|sorszám)|számlaszám|invoice\s*(?:no\.?|number|nr\.?|#)|"
    r"rechnungs?\s*(?:nummer|nr\.?)|rechnung\s*nr\.?|bizonylatszám|beleg(?:nummer|nr\.?)|receipt\s*(?:no\.?|number)|"
    r"nyugtaszám|order\s*(?:no\.?|number)|megrendelés(?:\s*száma)?)\s*[:#.\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/_.]{2,30})",
    re.I)


def find_issuer(text: str) -> str:
    m = _ISSUER_LABEL.search(text)
    if m:
        val = m.group(1).strip()
        if len(val) < 3:  # a címke önálló sor – a következő sor a név
            rest = text[m.end():].lstrip().splitlines()
            val = rest[0].strip() if rest else ""
        lm = _LEGAL_RE.search(val)
        val = lm.group(1) if lm else val[:50]
        if len(val) >= 3:
            return val.strip(" ,.;:")
    # első jogi formás sor, de a "Vevő" jelzés előtt
    buyer = _BUYER_MARK.search(text)
    zone = text[:buyer.start()] if buyer and buyer.start() > 40 else text
    for line in zone.splitlines()[:50]:
        lm = _LEGAL_RE.search(line.strip())
        if lm:
            return re.sub(r"^[\d\W]+", "", lm.group(1)).strip(" ,.;:")
    dm = _DOMAIN_RE.search(text)
    if dm:
        return dm.group(1).capitalize()
    return ""


def find_reference(text: str) -> str:
    for m in _INV_NO_RE.finditer(text):
        val = m.group(1).rstrip(".-/_")
        if any(c.isdigit() for c in val):
            return val
    return ""


def find_subject(text: str) -> str:
    m = re.search(r"(?:Tárgy|Betreff|Subject|Re)\s*:\s*(.{5,100})", text, re.I)
    return m.group(1).strip() if m else ""


def find_year(text: str) -> int | None:
    m = re.search(r"(?:©|copyright|published|received|accepted|közzétéve)[^\n]{0,40}?((?:19|20)\d\d)", text, re.I)
    return int(m.group(1)) if m else None


def first_title_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 15 and len(line.split()) >= 3 and sum(c.isalpha() for c in line) >= 0.6 * len(line):
            return line[:150]
    return ""


def best_title(info: PdfInfo) -> str:
    return clean_meta_title(info.meta_title) or info.title_guess or first_title_line(info.text)


# --- fő belépési pont --------------------------------------------------------------

def guess_fields(info: PdfInfo) -> Fields | None:
    """DOI nélküli PDF tartalmának felismerése. None, ha semmi értelmeset nem sikerült kiolvasni."""
    text = info.text
    if info.scanned:
        title = clean_meta_title(info.meta_title)
        return Fields(kind="other", title=title) if title else None

    if looks_like_article(text):
        title = best_title(info)
        return Fields(kind="article", title=title, year=find_year(text)) if title else None

    kind = classify_type(text)
    if kind:
        f = Fields(kind=kind, dated=True)
        f.date, f.date_note = find_issue_date(text)
        if not f.date and info.created:
            f.date, f.date_note = info.created.date(), "dátum: a PDF létrehozási dátuma"
        f.issuer = find_issuer(text)
        f.ref = find_subject(text) if kind == "letter" else find_reference(text)
        if kind in ("medical", "tax", "certificate", "insurance", "statement", "payslip", "contract") and not f.ref:
            f.title = ""
        return f

    title = best_title(info)
    return Fields(kind="other", title=title) if title else None


def compose_name(f: Fields) -> str | None:
    """Fields -> fájlnév-törzs."""
    if f.kind == "article":
        if f.authors or f.year or f.title:
            return article_stem(f.authors, f.year, f.title) or None
        return None
    if f.dated and (f.label or f.title):
        parts = [f.date.isoformat() if f.date else "", f.label, f.issuer, f.ref or f.title]
        return sanitize(" - ".join(sanitize(p, 60) for p in parts if p)) or None
    return sanitize(f.title, MAX_TITLE) or None
