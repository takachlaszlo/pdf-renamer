"""Belépési pont: argumentumok nélkül a grafikus felület; mappával parancssori mód."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, engine


def cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="pdfrenamer", description="PDF-ek átnevezése tartalmuk/metaadataik alapján.")
    ap.add_argument("folder", type=Path, nargs="?", default=Path.home(), help="átnézendő mappa (alapból: a saját mappád)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("-n", "--no-recursive", action="store_true", help="almappák nélkül")
    ap.add_argument("--all", action="store_true", help="a már azonosítható nevűeket is átnézi")
    ap.add_argument("--offline", action="store_true", help="nincs online lekérdezés (Crossref/arXiv)")
    ap.add_argument("--llm", action="store_true", help="Claude API használata (ANTHROPIC_API_KEY kell)")
    ap.add_argument("--apply", action="store_true", help="tényleges átnevezés (alapból csak előnézet)")
    ap.add_argument("--undo", action="store_true", help="az utolsó --apply visszavonása")
    ap.add_argument("--include-uncertain", action="store_true", help="a bizonytalan javaslatokat is átnevezi")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # ne haljon el egyetlen ékezetes fájlnévtől sem
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    if a.undo:
        log = engine.latest_undo_log()
        if not log:
            print("Nincs visszavonható átnevezés.")
            return 1
        ok, problems = engine.undo(log)
        print(f"{ok} fájl visszaállítva ({log.name}).")
        for pr in problems:
            print(f"  GOND: {pr}")
        return 0

    opts = engine.Options(recursive=not a.no_recursive, force_all=a.all, use_llm=a.llm, online=not a.offline)
    todo = []
    for r in engine.analyze_all(a.folder, opts):
        if r.status == "ok":
            continue
        mark = {"rename": "->", "unknown": "??", "error": "!!", "skip": "--"}[r.status]
        print(f"{mark} {r.path}")
        if r.new_stem:
            print(f"     {r.new_stem}{r.path.suffix}   [{r.kind}; {r.source}{'; BIZONYTALAN' if r.warn else ''}]")
        if r.note:
            print(f"     ({r.note})")
        if r.status == "rename" and (a.include_uncertain or not r.warn):
            todo.append((r.path, r.new_stem))
    print(f"\n{len(todo)} átnevezhető.")
    if a.apply and todo:
        done, errors, log = engine.apply(todo)
        print(f"{len(done)} átnevezve, {len(errors)} hiba. Napló: {log}")
        for p, m in errors:
            print(f"  HIBA {p}: {m}")
    elif todo:
        print("Előnézet – az átnevezéshez add meg: --apply")
    return 0


def main_cli() -> None:
    """`pdfrenamer` parancs (Linux/Windows/macOS): mindig parancssori, tkinter nem kell hozzá."""
    sys.exit(cli(sys.argv[1:]))


def main_gui() -> None:
    from .gui import main as gui_main
    gui_main()


def main() -> None:
    """Windows .exe belépési pont: argumentum nélkül GUI, mappa-argumentummal CLI."""
    if len(sys.argv) > 1:
        main_cli()
    main_gui()
