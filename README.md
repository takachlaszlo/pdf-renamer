# PDF átnevező

PDF-ek átnevezése a tartalmuk alapján. Csak azokat érinti, amelyeknek a neve nem azonosítható (pl. `scan0001.pdf`, `download (3).pdf`, `1-s2.0-S0140673620301835-main.pdf`).

| Dokumentum | Mit csinál | Példa az új névre |
|---|---|---|
| **Tudományos cikk** | DOI / arXiv-azonosító kiolvasása a metaadatból és az első oldalakról, majd Crossref / doi.org / arXiv lekérdezés. A DOI-t ellenőrzi: a cikk címének szerepelnie kell a PDF szövegében, így a hivatkozott művek DOI-ját nem fogadja el. | `LeCun et al 2015 - Deep learning.pdf` |
| **Számla, nyugta, szerződés, kivonat, bérjegyzék, igazolás, levél, lelet…** | Típus, **dátum**, kiállító és hivatkozási szám kiolvasása a szövegből (magyar, német, angol). | `2024-03-05 - Számla - Példa Kereskedelmi Kft - ABC-2024-00123.pdf` |
| **Egyéb** | Cím a legnagyobb betűméretű szövegből vagy a metaadatból. | `Házirend és adatkezelési tájékoztató.pdf` |
| **Szkennelt (nincs szövegréteg)** | OCR nélkül nem azonosítható → jelzi, nem nevezi át. | |

Alapelvek: **előnézet először** (átnevezés csak jóváhagyás után), minden átnevezés **visszavonható**, a bizonytalan javaslatok (sárga sor) alapból nincsenek kijelölve, ütközésnél ` (2)`, ` (3)` kerül a név végére.

## Windows – grafikus program (.exe)

1. A kiadásokból (Releases) töltsd le a `PdfRenamer.exe`-t, vagy építsd meg magad: `build_exe.bat` → `dist\PdfRenamer.exe`. Python nem kell hozzá.
2. Indításkor **nem fut le semmi magától**: válaszd ki a mappát (alapból a saját mappád, `C:\Users\<te>`), és kattints az **Átnézés** gombra. A **Tallózás…** gomb kijelölés után azonnal átnézi a mappát, a **Munkamappa** gomb visszaáll a sajátodra. Az utoljára használt mappát megjegyzi.
3. A táblázatban jelöld ki, amit át akarsz nevezni (kattintás a ☐/☑ jelre vagy szóköz). Dupla kattintás a jelenlegi néven megnyitja a PDF-et, az új néven szerkeszthető a javaslat.
4. **Kijelöltek átnevezése**. **Utolsó átnevezés visszavonása** visszaállítja az előző kört.

A teljes profil bejárásakor kihagyja: `AppData`, rejtett/rendszer/csatolt mappák, `.`-tal kezdődő mappák, `node_modules`, `venv`, `site-packages`, Windows- és Program Files-mappák. A felhőben lévő (OneDrive „csak online”) fájlokat nem tölti le, jelzi.

Ha szeretnéd, hogy induláskor magától átnézze a mappát, jelöld be az „Induláskor automatikus átnézés” négyzetet (alapból ki van kapcsolva).

## Linux (és macOS, Windows) – parancssor, GitHubról telepítve

```bash
sudo apt install pipx            # ha még nincs (Debian/Ubuntu); vagy: python3 -m pip install --user pipx
pipx install git+https://github.com/takachlaszlo/pdf-renamer.git
```

Használat:

```bash
pdfrenamer ~/Dokumentumok             # előnézet (nem nevez át semmit)
pdfrenamer ~/Dokumentumok --apply     # a biztos javaslatok átnevezése
pdfrenamer --undo                     # az utolsó --apply visszavonása
pdfrenamer --help
```

Kapcsolók: `-n` almappák nélkül · `--all` a jó nevűeket is átnézi · `--offline` nincs hálózati lekérdezés · `--include-uncertain` a bizonytalanokat is átnevezi · `--llm` Claude használata (lásd lent).
Frissítés: `pipx upgrade pdf-renamer`. Eltávolítás: `pipx uninstall pdf-renamer`.
A grafikus felület Linuxon is elindítható (`pdfrenamer-gui`), ha van `python3-tk`.

## Mi hagyja el a gépet?

- **Mindig (online módban):** a PDF-ben talált **DOI / arXiv-azonosító** (nyilvános azonosító), és – csak ha a PDF tudományos cikknek látszik (Abstract + Keywords/References…) – a cikk címe a Crossref-nek. Számlák, levelek, leletek tartalma **nem** megy sehova. `--offline`-nal semmi.
- **Csak ha kéred** (`--llm` / jelölőnégyzet, és az `ANTHROPIC_API_KEY` környezeti változó be van állítva): a nem azonosítható PDF-ek első 3 oldalának szövege az Anthropic API-hoz kerül, hogy a „miről szól” pontosabb legyen. Érzékeny anyagnál (betegadat) ne használd. Modell: `claude-haiku-4-5-20251001`, felülírható a `PDFRENAMER_MODEL` változóval.

## Fejlesztés

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python tests/make_samples.py ./tests/samples   # mintafájlok (reportlab + Windows-betűtípus kell)
python run.py                                  # GUI
```

A GitHub Actions (`.github/workflows/ci.yml`) Linuxon és Windowson futtatja a teszteket; `v*` címkénél megépíti és a kiadáshoz csatolja a `PdfRenamer.exe`-t.

## Korlátok

- Szkennelt PDF-ekhez OCR nincs.
- Dátum/kiállító/számlaszám szövegminták alapján készül; szokatlan számlaformátumnál hiányozhat – ilyenkor a sor sárga, és a név kézzel javítható.
- A számlákon a kiállító-felismerés jogi formára (Kft., Zrt., GmbH, AG, Ltd…) és „Eladó/Szállító” címkére épül.
- A `--llm` útvonalat valódi API-kulcs nélkül nem lehetett végigpróbálni; a válaszfeldolgozás tesztelt, a hívás nem.
