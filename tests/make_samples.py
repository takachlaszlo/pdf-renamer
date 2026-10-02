"""Mintafájlok generálása a teszteléshez (reportlab kell: pip install reportlab)."""
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

pdfmetrics.registerFont(TTFont("Arial", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("ArialB", "C:/Windows/Fonts/arialbd.ttf"))


def make(path: Path, blocks, title=""):
    c = canvas.Canvas(str(path), pagesize=A4)
    if title:
        c.setTitle(title)
    y = 800
    for text, size, bold in blocks:
        c.setFont("ArialB" if bold else "Arial", size)
        for line in text.split("\n"):
            c.drawString(50, y, line)
            y -= size + 4
        y -= 6
    c.save()


out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

make(out / "scan0001.pdf", [
    ("SZÁMLA", 20, True),
    ("Számla sorszáma: ABC-2024/00123", 10, False),
    ("Eladó: Példa Kereskedelmi Kft.\n1111 Budapest, Fő utca 1.", 10, False),
    ("Vevő: Takács László", 10, False),
    ("Számla kelte: 2024. március 5.\nTeljesítés dátuma: 2024.03.04.\nFizetési határidő: 2024.03.19.", 10, False),
    ("Nettó: 10 000 Ft  ÁFA 27%: 2 700 Ft  Bruttó: 12 700 Ft", 10, False),
])
make(out / "download (3).pdf", [
    ("Rechnung", 20, True),
    ("Muster Energie GmbH", 12, True),
    ("Rechnungsnummer: 2025-778812\nRechnungsdatum: 17.01.2025\nZahlungsziel: 31.01.2025", 10, False),
    ("Summe netto 100,00 EUR  MwSt 19% 19,00 EUR  Brutto 119,00 EUR", 10, False),
])
make(out / "x1.pdf", [
    ("Deep learning", 22, True),
    ("Yann LeCun, Yoshua Bengio, Geoffrey Hinton", 11, False),
    ("Abstract. Deep learning allows computational models that are composed of multiple processing layers to learn\n"
     "representations of data with multiple levels of abstraction.", 10, False),
    ("Nature 521, 436-444 (2015). https://doi.org/10.1038/nature14539", 9, False),
    ("Keywords: neural networks. References", 9, False),
])
# DOI egy hivatkozott műé, a cím a saját cikké (nem szabad a hivatkozott DOI-t elfogadni)
make(out / "paper_final.pdf", [
    ("Esettanulmány gyermekkori csontvelőgyulladásról", 20, True),
    ("Kovács Anna, Nagy Béla", 11, False),
    ("Összefoglaló: egy ritka esetet mutatunk be. Kulcsszavak: osteomyelitis, gyermek. Bevezetés. Irodalom:", 10, False),
    ("Hivatkozás: LeCun et al. https://doi.org/10.1038/nature14539", 9, False),
])
make(out / "doc.pdf", [
    ("Házirend és adatkezelési tájékoztató", 22, True),
    ("Ez a dokumentum a rendelő működési szabályait tartalmazza.", 10, False),
])
make(out / "Kovacs Anna 2020 - Mar jo nev.pdf", [("Valami", 12, False)])
make(out / "Diabetes mellitus gyermekkori kezelése összefoglaló.pdf", [("Valami más", 12, False)])
make(out / "empty.pdf", [])
(out / "broken.pdf").write_bytes(b"%PDF-1.4 nem igazi pdf")
print("kész:", out)
