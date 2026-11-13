"""Okno aplikácie: PDF faktúry dodávateľov -> TXT pre príjemku na sklad.

Spustenie:  python app.py   (alebo FakturyTXT.exe)
"""
from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import invoice_parser as ip  # noqa: E402

SETTINGS = Path(os.environ.get("APPDATA") or Path.home()) / "faktury_txt_nastavenia.json"
COLS = ("on", "ean", "qty", "price", "amount", "line")
HEAD = {"on": "✔", "ean": "EAN", "qty": "Počet MJ", "price": "Cena MJ",
        "amount": "Spolu", "line": "Riadok z faktúry"}


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    try:
        SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


class Doc:
    def __init__(self, path: str, inv: ip.Invoice):
        self.path = path
        self.inv = inv
        self.enabled = [i.ean not in App.skip_eans for i in inv.items]
        self.out_name = Path(path).stem + ".TXT"


class App(tk.Tk):
    skip_eans: set[str] = set()

    def __init__(self):
        super().__init__()
        self.title("Faktúry PDF → TXT príjemka")
        self.geometry("1150x650")
        self.settings = load_settings()
        App.skip_eans = set(self.settings.get("skip_eans", []))
        self.docs: list[Doc] = []
        self._build()

    # ---------- UI ----------
    def _build(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Button(top, text="Pridať PDF faktúry…", command=self.add_pdfs).pack(side="left")
        ttk.Button(top, text="Odstrániť zo zoznamu", command=self.remove_doc).pack(side="left", padx=4)
        ttk.Label(top, text="   Výstupný priečinok:").pack(side="left")
        self.out_dir = tk.StringVar(value=self.settings.get("out_dir", str(Path.home() / "Desktop")))
        ttk.Entry(top, textvariable=self.out_dir, width=45).pack(side="left", padx=2)
        ttk.Button(top, text="…", width=3, command=self.pick_dir).pack(side="left")
        ttk.Button(top, text="Uložiť TXT (vybraná)", command=self.save_current).pack(side="right")
        ttk.Button(top, text="Uložiť všetky", command=self.save_all).pack(side="right", padx=4)

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6)

        left = ttk.Frame(body)
        self.doclist = tk.Listbox(left, width=38, exportselection=False)
        self.doclist.pack(fill="both", expand=True)
        self.doclist.bind("<<ListboxSelect>>", lambda e: self.show_doc())
        body.add(left, weight=1)

        right = ttk.Frame(body)
        info = ttk.Frame(right)
        info.pack(fill="x", pady=(0, 4))
        ttk.Label(info, text="Mena:").pack(side="left")
        self.currency = tk.StringVar()
        cur = ttk.Combobox(info, textvariable=self.currency, values=ip.CURRENCIES, width=5)
        cur.pack(side="left", padx=(2, 12))
        cur.bind("<<ComboboxSelected>>", lambda e: self._store_meta())
        cur.bind("<FocusOut>", lambda e: self._store_meta())
        ttk.Label(info, text="Názov TXT:").pack(side="left")
        self.out_name = tk.StringVar()
        ne = ttk.Entry(info, textvariable=self.out_name, width=28)
        ne.pack(side="left", padx=2)
        ne.bind("<FocusOut>", lambda e: self._store_meta())
        self.summary = ttk.Label(info, text="", font=("Segoe UI", 10, "bold"))
        self.summary.pack(side="left", padx=12)

        frame = ttk.Frame(right)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=COLS, show="headings", selectmode="browse")
        widths = {"on": 30, "ean": 120, "qty": 80, "price": 90, "amount": 90, "line": 520}
        for c in COLS:
            self.tree.heading(c, text=HEAD[c])
            self.tree.column(c, width=widths[c], anchor="e" if c in ("qty", "price", "amount") else "w",
                             stretch=(c == "line"))
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("off", foreground="#999")
        self.tree.bind("<Double-1>", self.on_double)
        self.tree.bind("<space>", lambda e: self.toggle_selected())

        bottom = ttk.Frame(right)
        bottom.pack(fill="x", pady=4)
        ttk.Button(bottom, text="Zapnúť/vypnúť riadok (medzerník)", command=self.toggle_selected).pack(side="left")
        ttk.Button(bottom, text="Vždy vynechať tento EAN", command=self.always_skip).pack(side="left", padx=4)
        ttk.Label(bottom, text="Dvojklik na EAN / počet / cenu = úprava").pack(side="left", padx=8)
        body.add(right, weight=4)

        self.warn = tk.Text(self, height=4, foreground="#a00")
        self.warn.pack(fill="x", padx=6, pady=(0, 6))

    # ---------- akcie ----------
    def pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_dir.get() or None)
        if d:
            self.out_dir.set(d)

    def add_pdfs(self):
        files = filedialog.askopenfilenames(
            title="Vyber PDF faktúry", filetypes=[("PDF", "*.pdf *.PDF"), ("Všetky", "*.*")],
            initialdir=self.settings.get("pdf_dir") or None)
        if not files:
            return
        self.settings["pdf_dir"] = str(Path(files[0]).parent)
        for f in files:
            self.load_pdf(f)
        self.doclist.selection_clear(0, "end")
        self.doclist.selection_set("end")
        self.show_doc()

    def load_pdf(self, f: str):
        try:
            inv = ip.parse_pdf(f)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Chyba", f"{Path(f).name}:\n{e}")
            return
        doc = Doc(f, inv)
        self.docs.append(doc)
        mark = {True: "✔", False: "⚠", None: "?"}[inv.total_ok]
        self.doclist.insert("end", f"{mark} {Path(f).name}  ({len(inv.items)})")

    def remove_doc(self):
        d = self.current_index()
        if d is None:
            return
        del self.docs[d]
        self.doclist.delete(d)
        self.tree.delete(*self.tree.get_children())

    def current_index(self):
        sel = self.doclist.curselection()
        return sel[0] if sel else None

    def current(self) -> Doc | None:
        i = self.current_index()
        return self.docs[i] if i is not None else None

    def _store_meta(self):
        doc = self.current()
        if doc:
            doc.inv.currency = (self.currency.get() or "EUR").upper()[:3]
            doc.out_name = self.out_name.get().strip() or doc.out_name
            self.refresh_summary()

    def show_doc(self):
        doc = self.current()
        self.tree.delete(*self.tree.get_children())
        self.warn.delete("1.0", "end")
        if not doc:
            return
        self.currency.set(doc.inv.currency)
        self.out_name.set(doc.out_name)
        for n, it in enumerate(doc.inv.items):
            self.tree.insert("", "end", iid=str(n), values=self.row_values(doc, n),
                             tags=() if doc.enabled[n] else ("off",))
        msgs = list(doc.inv.warnings)
        if doc.inv.total_ok is False:
            msgs.insert(0, "Súčet položiek nesedí so sumou na faktúre – skontroluj riadky! "
                           f"Sumy na faktúre: {', '.join(map(str, doc.inv.doc_totals[:6]))}")
        self.warn.insert("1.0", "\n".join(msgs))
        self.refresh_summary()

    def row_values(self, doc: Doc, n: int):
        it = doc.inv.items[n]
        return ("✔" if doc.enabled[n] else "", it.ean, f"{it.qty:f}".rstrip("0").rstrip("."),
                f"{it.price:f}", f"{it.amount:.2f}", it.line)

    def refresh_summary(self):
        doc = self.current()
        if not doc:
            return
        items = [it for it, on in zip(doc.inv.items, doc.enabled) if on]
        total = sum((i.amount for i in items), Decimal(0))
        state = {True: "✔ sedí s faktúrou", False: "⚠ NESEDÍ s faktúrou", None: "(súčet faktúry nenájdený)"}
        ok = None if not doc.inv.doc_totals else any(abs(total - t) <= Decimal("0.02") for t in doc.inv.doc_totals)
        self.summary.config(text=f"{len(items)} položiek · spolu {total:.2f} {doc.inv.currency}  {state[ok]}",
                            foreground={True: "#070", False: "#a00", None: "#555"}[ok])

    def toggle_selected(self):
        doc = self.current()
        sel = self.tree.selection()
        if not doc or not sel:
            return
        n = int(sel[0])
        doc.enabled[n] = not doc.enabled[n]
        self.tree.item(sel[0], values=self.row_values(doc, n), tags=() if doc.enabled[n] else ("off",))
        self.refresh_summary()

    def always_skip(self):
        doc = self.current()
        sel = self.tree.selection()
        if not doc or not sel:
            return
        ean = doc.inv.items[int(sel[0])].ean
        App.skip_eans.add(ean)
        self.settings["skip_eans"] = sorted(App.skip_eans)
        save_settings(self.settings)
        for d in self.docs:
            for n, it in enumerate(d.inv.items):
                if it.ean == ean:
                    d.enabled[n] = False
        self.show_doc()

    def on_double(self, event):
        doc = self.current()
        row = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not doc or not row:
            return
        cname = COLS[int(col[1:]) - 1]
        n = int(row)
        if cname == "on":
            self.tree.selection_set(row)
            self.toggle_selected()
            return
        if cname not in ("ean", "qty", "price"):
            return
        x, y, w, h = self.tree.bbox(row, col)
        var = tk.StringVar(value=self.tree.set(row, cname))
        ent = ttk.Entry(self.tree, textvariable=var)
        ent.place(x=x, y=y, width=w, height=h)
        ent.focus_set()
        ent.select_range(0, "end")

        def commit(_=None):
            val = var.get().strip()
            it = doc.inv.items[n]
            try:
                if cname == "ean":
                    if val and not val.isdigit():
                        raise ValueError
                    it.ean = val
                else:
                    num = Decimal(val.replace(" ", "").replace(",", "."))
                    setattr(it, cname, num)
            except (ValueError, InvalidOperation):
                messagebox.showwarning("Neplatná hodnota", val)
            ent.destroy()
            self.tree.item(row, values=self.row_values(doc, n))
            self.refresh_summary()

        ent.bind("<Return>", commit)
        ent.bind("<FocusOut>", commit)
        ent.bind("<Escape>", lambda e: ent.destroy())

    def _save(self, doc: Doc) -> Path:
        out_dir = Path(self.out_dir.get() or Path(doc.path).parent)
        out_dir.mkdir(parents=True, exist_ok=True)
        name = doc.out_name if doc.out_name.lower().endswith(".txt") else doc.out_name + ".TXT"
        items = [it for it, on in zip(doc.inv.items, doc.enabled) if on]
        return ip.write_txt(items, doc.inv.currency, out_dir / name)

    def save_current(self):
        self._store_meta()
        doc = self.current()
        if not doc:
            messagebox.showinfo("Info", "Najprv vyber faktúru vľavo.")
            return
        out = self._save(doc)
        self._remember()
        messagebox.showinfo("Uložené", f"Uložené:\n{out}")

    def save_all(self):
        self._store_meta()
        outs = [str(self._save(d)) for d in self.docs]
        self._remember()
        messagebox.showinfo("Uložené", "\n".join(outs) or "Nič na uloženie.")

    def _remember(self):
        self.settings["out_dir"] = self.out_dir.get()
        save_settings(self.settings)


def main():
    app = App()
    for f in sys.argv[1:]:  # podpora "Otvoriť pomocou" / pretiahnutia PDF na .exe
        if f.lower().endswith(".pdf"):
            app.load_pdf(f)
    if app.docs:
        app.doclist.selection_set(0)
        app.show_doc()
    app.mainloop()


if __name__ == "__main__":
    main()
