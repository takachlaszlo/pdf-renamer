import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pdfrenamer import classify, engine, llm
from pdfrenamer.extract import clean_meta_title, find_arxiv_ids, find_dois
from pdfrenamer.naming import article_stem, is_identifiable, sanitize, unique_path


class Naming(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(sanitize('Cím: alcím <i>dőlt</i> "idézet" a/b?'), "Cím - alcím dőlt 'idézet' a-b")
        self.assertEqual(sanitize("CON"), "CON_")
        self.assertLessEqual(len(sanitize("szó " * 100)), 150)

    def test_article_stem(self):
        self.assertEqual(article_stem(["Smith"], 2020, "T"), "Smith 2020 - T")
        self.assertEqual(article_stem(["Smith", "Jones"], 2020, "T"), "Smith & Jones 2020 - T")
        self.assertEqual(article_stem(["A", "B", "C"], None, "T"), "A et al - T")
        self.assertEqual(article_stem([], 2020, "T"), "2020 - T")

    def test_identifiable(self):
        for good in ("Smith et al 2020 - Valami cím", "2024-03-05 - Számla - X Kft - 12",
                     "Diabetes mellitus gyermekkori kezelése", "Kovács Anna önéletrajz 2024"):
            self.assertTrue(is_identifiable(good), good)
        for bad in ("scan0001", "download (3)", "1-s2.0-S0140673620301835-main", "10.1016_j.cell.2020.01.001",
                    "paper_final", "x1", "Smith2020", "a1b2c3d4e5f6", "IMG_20240101_123456"):
            self.assertFalse(is_identifiable(bad), bad)

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "A.pdf").write_bytes(b"x")
            taken = set()
            p1 = unique_path(d, "A", ".pdf", taken)
            self.assertEqual(p1.name, "A (2).pdf")
            taken.add(str(p1).lower())
            self.assertEqual(unique_path(d, "A", ".pdf", taken).name, "A (3).pdf")
            self.assertEqual(unique_path(d, "A", ".pdf", set(), own=d / "A.pdf").name, "A.pdf")


class Extraction(unittest.TestCase):
    def test_doi(self):
        self.assertEqual(find_dois("doi: 10.1038/nature14539."), ["10.1038/nature14539"])
        self.assertEqual(find_dois("(10.1000/abc(1)2)"), ["10.1000/abc(1)2"])
        got = find_dois("https://doi.org/10.1038/nature14539Received: 1 May")
        self.assertEqual(got[-1], "10.1038/nature14539")
        self.assertEqual(find_arxiv_ids("arXiv:2101.00001v2 [cs.LG]"), ["2101.00001"])

    def test_meta_title(self):
        self.assertEqual(clean_meta_title("Microsoft Word - valami.docx"), "")
        self.assertEqual(clean_meta_title("A valódi cím itt van"), "A valódi cím itt van")


class Classify(unittest.TestCase):
    def test_dates(self):
        d = lambda s: [x[1] for x in classify.find_dates(s)]
        self.assertEqual(d("2024. március 5."), [date(2024, 3, 5)])
        self.assertEqual(d("17.01.2025"), [date(2025, 1, 17)])
        self.assertEqual(d("2024-03-05"), [date(2024, 3, 5)])
        self.assertEqual(d("5 March 2024"), [date(2024, 3, 5)])
        self.assertEqual(d("March 5, 2024"), [date(2024, 3, 5)])
        self.assertEqual(d("5. Dezember 2023"), [date(2023, 12, 5)])
        self.assertEqual(d("31.02.2024"), [])

    def test_issue_date_prefers_label(self):
        txt = "Fizetési határidő: 2024.04.01.\nSzámla kelte: 2024.03.05.\nTeljesítés dátuma: 2024.03.04."
        self.assertEqual(classify.find_issue_date(txt), (date(2024, 3, 5), ""))
        txt = "Invoice\nDue date 2024-05-01\nDate: 2024-04-02"
        self.assertEqual(classify.find_issue_date(txt)[0], date(2024, 4, 2))

    def test_invoice_fields(self):
        txt = "SZÁMLA\nSzámla sorszáma: ABC-2024/00123\nEladó: Példa Kft.\nÁFA bruttó nettó fizetési határidő"
        self.assertEqual(classify.classify_type(txt), "invoice")
        self.assertEqual(classify.find_reference(txt), "ABC-2024/00123")
        self.assertEqual(classify.find_issuer(txt), "Példa Kft")

    def test_no_type_for_plain_text(self):
        self.assertIsNone(classify.classify_type("Ez egy sima szöveg semmi különössel."))

    def test_compose(self):
        f = classify.Fields("invoice", dated=True, date=date(2024, 3, 5), issuer="X Kft", ref="12/3")
        self.assertEqual(classify.compose_name(f), "2024-03-05 - Számla - X Kft - 12-3")
        self.assertEqual(classify.compose_name(classify.Fields("other", title="Valami cím")), "Valami cím")


class Engine(unittest.TestCase):
    def test_scan_excludes(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for sub in ("ok", "AppData/x", "node_modules/y", ".hidden", "ok/mély"):
                (d / sub).mkdir(parents=True)
                (d / sub / "a.PDF").write_bytes(b"x")
            (d / "ok" / "b.txt").write_bytes(b"x")
            found = {p.relative_to(d).as_posix() for p in engine.scan_pdfs(d)}
            self.assertEqual(found, {"ok/a.PDF", "ok/mély/a.PDF"})
            self.assertEqual(len(engine.scan_pdfs(d, recursive=False)), 0)

    def test_apply_and_undo(self):
        with tempfile.TemporaryDirectory() as d:
            engine.APP_DIR = Path(d) / "cfg"
            a, b = Path(d) / "a.pdf", Path(d) / "b.pdf"
            a.write_bytes(b"1"); b.write_bytes(b"2")
            done, errors, log = engine.apply([(a, "Név"), (b, "Név")])
            self.assertEqual(sorted(n.name for _, n in done), ["Név (2).pdf", "Név.pdf"])
            ok, problems = engine.undo(log)
            self.assertEqual((ok, problems), (2, []))
            self.assertTrue(a.exists() and b.exists())


class Llm(unittest.TestCase):
    def test_parse_reply(self):
        f = llm.parse_reply('Itt: {"kind":"invoice","title":"","authors":[],"year":null,"date":"2024-03-05",'
                            '"issuer":"X Kft","reference":"12","dated":true}')
        self.assertEqual((f.kind, f.date, f.issuer, f.dated), ("invoice", date(2024, 3, 5), "X Kft", True))
        self.assertIsNone(llm.parse_reply("nincs json"))
        self.assertEqual(llm.parse_reply('{"kind":"valami"}').kind, "other")


if __name__ == "__main__":
    unittest.main()
