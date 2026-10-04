"""Tkinter grafikus felület: mappaválasztás, automatikus átnézés, előnézet, jóváhagyás utáni átnevezés, visszavonás."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import engine, llm
from .naming import sanitize

CHECK, UNCHECK = "☑", "☐"
STATUS_TAGS = {"ok": "ok", "unknown": "unknown", "error": "error", "skip": "unknown"}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PDF átnevező")
        self.geometry("1360x700")
        self.minsize(900, 480)
        self.settings = engine.load_settings()
        self.results: list[engine.Result] = []
        self.checked: dict[str, bool] = {}
        self.stems: dict[str, str] = {}
        self.q: queue.Queue = queue.Queue()
        self.stop_evt = threading.Event()
        self.worker: threading.Thread | None = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._poll)
        if self.settings["auto_scan"] and Path(self.settings["folder"]).is_dir():
            self.after(400, self.start_scan)

    # --- felépítés ---------------------------------------------------------------
    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Mappa:").pack(side="left")
        self.folder = tk.StringVar(value=self.settings["folder"])
        ttk.Entry(top, textvariable=self.folder).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Tallózás…", command=self.browse).pack(side="left")
        ttk.Button(top, text="Munkamappa", command=self.use_home).pack(side="left", padx=(6, 0))

        opts = ttk.Frame(self)
        opts.pack(fill="x", **pad)
        self.v_rec = tk.BooleanVar(value=self.settings["recursive"])
        self.v_all = tk.BooleanVar(value=self.settings["force_all"])
        self.v_auto = tk.BooleanVar(value=self.settings["auto_scan"])
        self.v_llm = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Almappákkal együtt", variable=self.v_rec).pack(side="left")
        ttk.Checkbutton(opts, text="A jó nevűeket is átnézi", variable=self.v_all).pack(side="left", padx=12)
        ttk.Checkbutton(opts, text="Induláskor automatikus átnézés", variable=self.v_auto).pack(side="left")
        self.cb_llm = ttk.Checkbutton(
            opts, text="Claude használata a tartalomhoz (az 1–3. oldal szövege az Anthropichoz kerül)",
            variable=self.v_llm, command=self._llm_toggled,
            state="normal" if llm.api_key() else "disabled")
        self.cb_llm.pack(side="left", padx=12)
        if not llm.api_key():
            ttk.Label(opts, text="(ANTHROPIC_API_KEY nincs beállítva)", foreground="gray").pack(side="left")

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.btn_scan = ttk.Button(bar, text="Átnézés", command=self.start_scan)
        self.btn_scan.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="Leállítás", command=self.stop_evt.set, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="Mind kijelöl", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(bar, text="Egyiket sem", command=lambda: self._set_all(False)).pack(side="left", padx=6)
        self.btn_apply = ttk.Button(bar, text="Kijelöltek átnevezése", command=self.apply_selected)
        self.btn_apply.pack(side="left", padx=(16, 0))
        ttk.Button(bar, text="Utolsó átnevezés visszavonása", command=self.undo_last).pack(side="right")

        cols = ("sel", "old", "new", "kind", "src", "note")
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, **pad)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for c, t, w in (("sel", "", 36), ("old", "Jelenlegi név", 330), ("new", "Új név", 430),
                        ("kind", "Típus", 90), ("src", "Forrás", 150), ("note", "Megjegyzés", 300)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=c in ("old", "new", "note"), anchor="center" if c == "sel" else "w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("ok", foreground="#808080")
        self.tree.tag_configure("unknown", foreground="#b36b00")
        self.tree.tag_configure("error", foreground="#c00000")
        self.tree.tag_configure("warn", background="#fff6d6")
        self.tree.tag_configure("done", foreground="#1a7f37")
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<Double-1>", self._double)
        self.tree.bind("<space>", self._space)

        self.status = tk.StringVar(value="Készen áll – válassz mappát, majd kattints az Átnézés gombra.")
        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=8)
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=8, pady=(2, 6))
        ttk.Label(self, foreground="gray", anchor="w",
                  text="Dupla kattintás: a „Jelenlegi név” megnyitja a PDF-et, az „Új név” szerkeszthető. "
                       "Sárga sor = bizonytalan (alapból nincs kijelölve). Átnevezés csak a jóváhagyásod után történik."
                  ).pack(fill="x", padx=8, pady=(0, 6))

    # --- mappa -------------------------------------------------------------------
    def browse(self) -> None:
        d = filedialog.askdirectory(initialdir=self.folder.get() or str(engine.DEFAULT_FOLDER),
                                    title="Válaszd ki az átnézendő mappát", mustexist=True)
        if d:
            self.folder.set(os.path.normpath(d))
            self.start_scan()

    def use_home(self) -> None:
        self.folder.set(str(engine.DEFAULT_FOLDER))
        self.v_rec.set(True)
        self.start_scan()

    def _llm_toggled(self) -> None:
        if self.v_llm.get() and not messagebox.askyesno(
                "Claude használata",
                "Bekapcsolva a nem azonosítható PDF-ek első oldalainak szövege elküldésre kerül az Anthropic API-nak.\n"
                "Ne használd érzékeny dokumentumokhoz (pl. betegadatok).\n\nBekapcsolod?"):
            self.v_llm.set(False)

    # --- elemzés (háttérszálon) ----------------------------------------------------
    def start_scan(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        folder = Path(self.folder.get().strip())
        if not folder.is_dir():
            messagebox.showerror("Hiba", f"Nem létező mappa:\n{folder}")
            return
        self._clear()
        opts = engine.Options(recursive=self.v_rec.get(), force_all=self.v_all.get(),
                              use_llm=self.v_llm.get(), mailto=self.settings.get("mailto", ""))
        self.stop_evt.clear()
        self.btn_scan.config(state="disabled")
        self.btn_apply.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.status.set(f"PDF-ek keresése: {folder} …")
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self.worker = threading.Thread(target=self._work, args=(folder, opts), daemon=True)
        self.worker.start()

    def _work(self, folder: Path, opts: engine.Options) -> None:
        try:
            for res in engine.analyze_all(
                    folder, opts, should_stop=self.stop_evt.is_set,
                    progress=lambda i, n, f: self.q.put(("progress", (i, n, f)))):
                self.q.put(("res", res))
        except Exception as e:
            self.q.put(("fatal", str(e)))
        self.q.put(("done", None))

    def _poll(self) -> None:
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "res":
                    self._add(data)
                elif kind == "progress":
                    i, n, f = data
                    if str(self.progress["mode"]) != "determinate":
                        self.progress.stop()
                        self.progress.config(mode="determinate", maximum=n)
                    self.progress["value"] = i
                    self.status.set(f"Elemzés {i}/{n}: {f.name}")
                elif kind == "fatal":
                    messagebox.showerror("Hiba", data)
                elif kind == "done":
                    self._finish()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finish(self) -> None:
        self.progress.stop()
        self.progress.config(mode="determinate")
        self.btn_scan.config(state="normal")
        self.btn_apply.config(state="normal")
        self.btn_stop.config(state="disabled")
        n = len(self.results)
        ren = sum(r.status == "rename" for r in self.results)
        unk = sum(r.status in ("unknown", "error", "skip") for r in self.results)
        self.status.set(f"Kész: {n} PDF, ebből {ren} átnevezési javaslat, {unk} nem azonosítható/hibás, "
                        f"{n - ren - unk} már rendben van.")

    # --- tábla -------------------------------------------------------------------
    def _clear(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.results.clear()
        self.checked.clear()
        self.stems.clear()

    def _add(self, r: engine.Result) -> None:
        if r.status == "ok" and not self.v_all.get():
            self.results.append(r)  # számoljuk, de nem zsúfoljuk a táblát
            return
        iid = str(len(self.results))
        self.results.append(r)
        can = r.status == "rename"
        self.checked[iid] = can and not r.warn
        self.stems[iid] = r.new_stem or ""
        tags = (STATUS_TAGS.get(r.status, ""),) + (("warn",) if r.warn else ())
        self.tree.insert("", "end", iid=iid, tags=tags, values=(
            (CHECK if self.checked[iid] else UNCHECK) if can else "",
            self._rel(r.path), (self.stems[iid] + r.path.suffix) if can else "", r.kind, r.source, r.note))

    def _rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.folder.get()))
        except ValueError:
            return str(p)

    def _set_all(self, on: bool) -> None:
        for iid in self.tree.get_children():
            if self.results[int(iid)].status == "rename":
                self._set(iid, on)

    def _set(self, iid: str, on: bool) -> None:
        self.checked[iid] = on
        self.tree.set(iid, "sel", CHECK if on else UNCHECK)

    def _click(self, e: tk.Event) -> None:
        if self.tree.identify_region(e.x, e.y) == "cell" and self.tree.identify_column(e.x) == "#1":
            iid = self.tree.identify_row(e.y)
            if iid and self.results[int(iid)].status == "rename":
                self._set(iid, not self.checked[iid])

    def _space(self, _e: tk.Event) -> None:
        sel = self.tree.selection()
        if sel and self.results[int(sel[0])].status == "rename":
            self._set(sel[0], not self.checked[sel[0]])

    def _double(self, e: tk.Event) -> None:
        iid, col = self.tree.identify_row(e.y), self.tree.identify_column(e.x)
        if not iid:
            return
        r = self.results[int(iid)]
        if col == "#2":
            try:
                os.startfile(r.path)  # type: ignore[attr-defined]
            except OSError as ex:
                messagebox.showerror("Hiba", str(ex))
        elif col == "#3" and r.status in ("rename", "unknown"):
            new = simpledialog.askstring("Új név", "Fájlnév (kiterjesztés nélkül):",
                                         initialvalue=self.stems.get(iid, "") or r.path.stem, parent=self)
            if new and sanitize(new):
                self.stems[iid] = sanitize(new)
                r.status = "rename"
                self.tree.set(iid, "new", self.stems[iid] + r.path.suffix)
                self._set(iid, True)

    # --- átnevezés / visszavonás ------------------------------------------------------
    def apply_selected(self) -> None:
        items = [(self.results[int(i)].path, self.stems[i]) for i in self.tree.get_children() if self.checked.get(i)]
        if not items:
            messagebox.showinfo("Átnevezés", "Nincs kijelölt elem.")
            return
        if not messagebox.askyesno("Átnevezés", f"{len(items)} fájlt nevezek át. Folytatod?\n"
                                                "(Az „Utolsó átnevezés visszavonása” gombbal visszaállítható.)"):
            return
        done, errors, _log = engine.apply(items)
        by_old = {o: n for o, n in done}
        for iid in self.tree.get_children():
            r = self.results[int(iid)]
            if r.path in by_old:
                r.path = by_old[r.path]
                self.tree.item(iid, tags=("done",))
                self.tree.set(iid, "sel", "✔")
                self.tree.set(iid, "old", self._rel(r.path))
                self.tree.set(iid, "note", "átnevezve")
                self.checked[iid] = False
                r.status = "ok"
        msg = f"{len(done)} fájl átnevezve."
        if errors:
            msg += f" {len(errors)} hiba: " + "; ".join(f"{p.name}: {m}" for p, m in errors[:3])
        self.status.set(msg)

    def undo_last(self) -> None:
        log = engine.latest_undo_log()
        if not log:
            messagebox.showinfo("Visszavonás", "Nincs visszavonható átnevezés.")
            return
        if not messagebox.askyesno("Visszavonás", f"Visszaállítom az utolsó átnevezést?\n({log.name})"):
            return
        ok, problems = engine.undo(log)
        self.status.set(f"{ok} fájl visszaállítva." + (f" Gondok: {'; '.join(problems[:3])}" if problems else ""))
        if messagebox.askyesno("Visszavonás", "Újra átnézzem a mappát?"):
            self.start_scan()

    def _close(self) -> None:
        self.settings.update(folder=self.folder.get(), recursive=self.v_rec.get(),
                             auto_scan=self.v_auto.get(), force_all=self.v_all.get())
        engine.save_settings(self.settings)
        self.stop_evt.set()
        self.destroy()


def main() -> None:
    try:  # éles megjelenítés magas DPI-n
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    App().mainloop()
