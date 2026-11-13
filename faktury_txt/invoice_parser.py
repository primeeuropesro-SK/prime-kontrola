"""Prevod PDF faktúr od dodávateľov na TXT pre import príjemky (pevná dĺžka).

Formát výstupu (podľa "Štruktúra súboru TXT", pevná dĺžka položiek):

    pozícia  1, dĺžka 14 – EAN kód (zarovnaný doľava)
    pozícia 15, dĺžka 15 – počet MJ (zarovnaný doprava, 6 desatinných miest)
    pozícia 30, dĺžka 15 – cena MJ  (zarovnaná doprava, 6 desatinných miest)
    pozícia 45, dĺžka  3 – mena

Parser nepotrebuje šablónu pre každého dodávateľa. Pre každý platný EAN-13
na faktúre (overuje sa kontrolná číslica, takže IČO, účty a pod. sa ignorujú)
nájde v tom istom riadku (alebo v susednom riadku tej istej položky) dvojicu
čísel množstvo × cena, ktorej súčin sa rovná ďalšiemu číslu v riadku
(hodnota položky). Tým sa spoľahlivo odlíši cena od zľavy, DPH, colného
kódu a pod. bez ohľadu na poradie stĺpcov.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

CURRENCIES = ("EUR", "CZK", "PLN", "USD", "HUF", "GBP", "CHF", "RON")

EAN_RE = re.compile(r"(?<!\d)(\d{13})(?!\d)")
# Čísla: 1 234,56 | 1.234,56 | 1,234.56 | 19,26 | 19.26 | 3
NUM_RE = re.compile(
    r"(?<![\w.,])"
    r"(-?\d{1,3}(?:[  ]\d{3})+[.,]\d+"   # tisíce oddelené medzerou (len s desatinnou časťou)
    r"|-?\d{1,3}(?:\.\d{3})+,\d+"              # 1.234,56
    r"|-?\d{1,3}(?:,\d{3})+\.\d+"              # 1,234.56
    r"|-?\d+(?:[.,]\d+)?)"
    r"(?![\w%]|[.,]\d)"
)
# Kódy, ktoré nie sú množstvo ani cena: PKWiU 15.20.12.0, dátumy, percentá...
NOISE_RE = re.compile(
    r"\d+(?:\.\d+){2,}"            # 15.20.12.0, 06.11.2026
    r"|\d{4}-\d{2}-\d{2}"          # 2026-11-06
    r"|\d+(?:[.,]\d+)?\s*%"        # 23 %, 0%
)
POSITION_RE = re.compile(r"^\s*\d{1,4}\s*[.)]?\s+(?=\D)")


def ean_valid(code: str) -> bool:
    if len(code) != 13 or not code.isdigit():
        return False
    digits = [int(c) for c in code]
    total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == digits[12]


def to_decimal(token: str) -> Decimal | None:
    t = token.replace(" ", " ").strip()
    if " " in t:
        t = t.replace(" ", "")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def numbers_in(text: str) -> list[Decimal]:
    text = NOISE_RE.sub(" ", text)
    # „2pc.“, „10pair“, „3ks“ – množstvo zlepené s jednotkou
    text = re.sub(r"(\d)([A-Za-zÀ-ž]{1,5}\.?)(?=\s|$)", r"\1 \2", text)
    out = []
    for m in NUM_RE.finditer(text):
        tok = m.group(1)
        digits = re.sub(r"\D", "", tok)
        # dlhé celé čísla bez desatinnej časti = kódy (colný kód 62033310, EAN...)
        if re.fullmatch(r"-?\d+", tok) and len(digits) >= 6:
            continue
        val = to_decimal(tok)
        if val is not None:
            out.append(val)
    return out


def find_qty_price(nums: list[Decimal]) -> tuple[Decimal, Decimal] | None:
    """Nájde (množstvo, cena) také, že množstvo × cena = iné číslo za nimi."""
    best = None
    for i, q in enumerate(nums):
        if q <= 0:
            continue
        for j in range(i + 1, len(nums)):
            p = nums[j]
            if p <= 0:
                continue
            prod = q * p
            tol = max(Decimal("0.011"), prod * Decimal("0.0005"))
            if any(abs(prod - v) <= tol for v in nums[j + 1:]):
                score = (q == q.to_integral_value(), -i, -j)
                if best is None or score > best[0]:
                    best = (score, q, p)
        if best and best[0][0]:
            break  # prvé celé množstvo s nájdenou hodnotou vyhráva
    return (best[1], best[2]) if best else None


@dataclass
class Item:
    ean: str
    qty: Decimal
    price: Decimal
    line: str = ""
    page: int = 0

    @property
    def amount(self) -> Decimal:
        return (self.qty * self.price).quantize(Decimal("0.01"))


@dataclass
class Invoice:
    source: str
    currency: str
    items: list[Item] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    supplier: str = ""
    number: str = ""
    doc_totals: list[Decimal] = field(default_factory=list)

    @property
    def total_ok(self) -> bool | None:
        """True ak sa súčet položiek zhoduje s niektorou sumou „Total/Spolu“ na faktúre."""
        if not self.doc_totals:
            return None
        return any(abs(self.total - t) <= Decimal("0.05") for t in self.doc_totals)

    @property
    def total(self) -> Decimal:
        return sum((i.amount for i in self.items), Decimal("0"))


def extract_pages(pdf_path: str | Path) -> list[str]:
    import pdfplumber

    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text(layout=True) or "")
    return pages


def detect_currency(text: str) -> str:
    counts = {c: len(re.findall(rf"\b{c}\b", text)) for c in CURRENCIES}
    if "€" in text:
        counts["EUR"] += text.count("€")
    cur, n = max(counts.items(), key=lambda kv: kv[1])
    return cur if n else "EUR"


def detect_number(text: str) -> str:
    m = re.search(
        r"(?:invoice|faktura|faktúra|faktury|rachunek|proforma|pro forma invoice)"
        r"[^\n]{0,40}?\b([A-Z]{0,6}[/\-]?\d[\w/\-]{4,})",
        text, re.I)
    return m.group(1) if m else ""


TOTAL_WORDS = re.compile(
    r"total|summe|suma|spolu|celkem|celkom|razem|do zap[łl]aty|amount due|k [úu]hrad[ěe]", re.I)


def detect_totals(text: str) -> list[Decimal]:
    vals = []
    for line in text.splitlines():
        if TOTAL_WORDS.search(line):
            vals.extend(v for v in numbers_in(line) if v > 0)
    return vals


def parse_pages(pages: list[str], source: str = "", currency: str | None = None) -> Invoice:
    full = "\n".join(pages)
    inv = Invoice(source=source, currency=currency or detect_currency(full),
                  number=detect_number(full), doc_totals=detect_totals(full))
    for pno, text in enumerate(pages, 1):
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            for m in EAN_RE.finditer(line):
                ean = m.group(1)
                if not ean_valid(ean):
                    continue
                rest = line[:m.start()] + " " + line[m.end():]
                rest = POSITION_RE.sub(" ", rest, count=1)
                found = find_qty_price(numbers_in(rest))
                if not found:
                    # množstvo/cena môže byť v susednom riadku tej istej položky
                    for off in (-1, 1, -2, 2):
                        k = idx + off
                        if 0 <= k < len(lines) and not any(
                                ean_valid(e) for e in EAN_RE.findall(lines[k])):
                            cand = POSITION_RE.sub(" ", lines[k], count=1)
                            found = find_qty_price(numbers_in(cand))
                            if found:
                                break
                if found:
                    inv.items.append(Item(ean, found[0], found[1], line.strip(), pno))
                else:
                    inv.warnings.append(
                        f"Str. {pno}: EAN {ean} – nenašiel som množstvo a cenu: {line.strip()[:90]}")
    if not inv.items:
        if not full.strip():
            inv.warnings.append("PDF neobsahuje text (asi sken) – treba OCR.")
        else:
            inv.warnings.append("Na faktúre sa nenašiel žiadny platný EAN.")
    return inv


def parse_pdf(pdf_path: str | Path, currency: str | None = None) -> Invoice:
    return parse_pages(extract_pages(pdf_path), source=str(pdf_path), currency=currency)


def format_line(ean: str, qty: Decimal, price: Decimal, currency: str) -> str:
    return f"{ean:<14.14}{qty:>15.6f}{price:>15.6f}{currency[:3]:<3}"


def to_txt(items: list[Item], currency: str) -> str:
    return "".join(format_line(i.ean, i.qty, i.price, currency) + "\r\n" for i in items)


def write_txt(items: list[Item], currency: str, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.write_bytes(to_txt(items, currency).encode("ascii"))
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="PDF faktúra -> TXT pre príjemku")
    ap.add_argument("pdf", nargs="+", help="PDF faktúry")
    ap.add_argument("-o", "--out-dir", default=None, help="priečinok pre TXT (predvolene vedľa PDF)")
    ap.add_argument("-c", "--currency", default=None, help="vynútiť menu (napr. EUR)")
    ap.add_argument("--skip-ean", action="append", default=[], help="EAN, ktorý vynechať (napr. doprava)")
    args = ap.parse_args(argv)

    rc = 0
    for pdf in args.pdf:
        inv = parse_pdf(pdf, args.currency)
        items = [i for i in inv.items if i.ean not in set(args.skip_ean)]
        out_dir = Path(args.out_dir) if args.out_dir else Path(pdf).parent
        out = write_txt(items, inv.currency, out_dir / (Path(pdf).stem + ".TXT"))
        total = sum((i.amount for i in items), Decimal(0))
        check = {True: "súčet sedí s faktúrou", False: "SÚČET NESEDÍ s faktúrou", None: "súčet na faktúre nenájdený"}[inv.total_ok]
        print(f"{pdf}: {len(items)} položiek, spolu {total} {inv.currency} ({check}) -> {out}")
        if inv.total_ok is False:
            rc = 1
        for w in inv.warnings:
            print("  POZOR:", w)
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
