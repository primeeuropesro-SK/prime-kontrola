// ===== Parser faktúr (rovnaká logika ako faktury_txt/invoice_parser.py) =====
const FP = (() => {
  const CURRENCIES = ["EUR", "CZK", "PLN", "USD", "HUF", "GBP", "CHF", "RON"];
  const NUM_RE = /(?<![\w.,])(-?\d{1,3}(?:[  ]\d{3})+[.,]\d+|-?\d{1,3}(?:\.\d{3})+,\d+|-?\d{1,3}(?:,\d{3})+\.\d+|-?\d+(?:[.,]\d+)?)(?![\w%]|[.,]\d)/g;
  const NOISE_RE = /\d+(?:\.\d+){2,}|\d{4}-\d{2}-\d{2}|\d+(?:[.,]\d+)?\s*%/g;
  const POSITION_RE = /^\s*\d{1,4}\s*[.)]?\s+(?=\D)/;
  const EAN_RE = /(?<!\d)(\d{13})(?!\d)/g;
  const TOTAL_WORDS = /total|summe|suma|spolu|celkem|celkom|razem|do zap[łl]aty|amount due|k [úu]hrad[ěe]/i;

  // Desatinné čísla ako celé čísla v 1/10^6 (presne, bez chýb float)
  const SCALE = 1000000n;
  function toFixed(token) {
    let t = token.replace(/[  ]/g, "");
    if (t.includes(",") && t.includes(".")) {
      t = t.lastIndexOf(",") > t.lastIndexOf(".") ? t.replace(/\./g, "").replace(",", ".") : t.replace(/,/g, "");
    } else t = t.replace(",", ".");
    const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(t);
    if (!m) return null;
    const frac = (m[3] || "").slice(0, 6).padEnd(6, "0");
    const v = BigInt(m[2]) * SCALE + BigInt(frac);
    return m[1] ? -v : v;
  }
  const fmt = (v, d = 6) => {
    const neg = v < 0n; if (neg) v = -v;
    let s = (v / SCALE).toString() + "." + (v % SCALE).toString().padStart(6, "0");
    if (d < 6) s = s.slice(0, s.length - (6 - d));
    return (neg ? "-" : "") + s;
  };
  const round2 = v => { const q = 10000n; const r = (v >= 0n ? v + q / 2n : v - q / 2n) / q; return r * q; };
  const abs = v => (v < 0n ? -v : v);

  function eanValid(c) {
    if (!/^\d{13}$/.test(c)) return false;
    let s = 0;
    for (let i = 0; i < 12; i++) s += +c[i] * (i % 2 ? 3 : 1);
    return (10 - (s % 10)) % 10 === +c[12];
  }

  function numbersIn(text) {
    text = text.replace(NOISE_RE, " ");
    // „2pc.“, „10pair“, „3ks“ – množstvo zlepené s jednotkou
    text = text.replace(/(\d)([A-Za-zÀ-ž]{1,5}\.?)(?=\s|$)/g, "$1 $2");
    const out = [];
    for (const m of text.matchAll(NUM_RE)) {
      const tok = m[1];
      if (/^-?\d+$/.test(tok) && tok.replace("-", "").length >= 6) continue;
      const v = toFixed(tok);
      if (v !== null) out.push(v);
    }
    return out;
  }

  function findQtyPrice(nums) {
    let best = null;
    for (let i = 0; i < nums.length; i++) {
      const q = nums[i];
      if (q <= 0n) continue;
      for (let j = i + 1; j < nums.length; j++) {
        const p = nums[j];
        if (p <= 0n) continue;
        const prod = (q * p) / SCALE;
        let tol = prod / 2000n; if (tol < 11000n) tol = 11000n;
        if (nums.slice(j + 1).some(v => abs(prod - v) <= tol)) {
          const isInt = q % SCALE === 0n;
          const score = [isInt ? 1 : 0, -i, -j];
          if (!best || cmp(score, best.score) > 0) best = { score, q, p, v: nums.slice(j + 1).find(v => abs(prod - v) <= tol) };
        }
      }
      if (best && best.score[0]) break;
    }
    return best ? [best.q, best.p, best.v] : null;
  }
  const cmp = (a, b) => { for (let k = 0; k < a.length; k++) if (a[k] !== b[k]) return a[k] - b[k]; return 0; };

  function detectCurrency(text) {
    let best = "EUR", n = 0;
    for (const c of CURRENCIES) {
      let k = (text.match(new RegExp("\\b" + c + "\\b", "g")) || []).length;
      if (c === "EUR") k += (text.match(/€/g) || []).length;
      if (k > n) { n = k; best = c; }
    }
    return best;
  }

  function detectTotals(text) {
    const vals = [];
    for (const line of text.split("\n")) if (TOTAL_WORDS.test(line)) vals.push(...numbersIn(line).filter(v => v > 0n));
    return vals;
  }

  function detectNumber(text) {
    const m = /(?:invoice|faktura|faktúra|faktury|rachunek|proforma|pro forma invoice)[^\n]{0,40}?\b([A-Z]{0,6}[/\-]?\d[\w/\-]{4,})/i.exec(text);
    return m ? m[1] : "";
  }

  function detectDate(text) {
    const m = /(?:date of issue|invoice date|issue date|data wystawienia|d[áa]tum vystavenia|datum vystaven[íi]|rechnungsdatum|data)[^\n\d]{0,60}(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{4})/i.exec(text)
      || /(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})/.exec(text);
    return m ? m[1] : "";
  }

  // pages: pole textov (riadky oddelené \n)
  function parsePages(pages) {
    const full = pages.join("\n");
    const inv = { currency: detectCurrency(full), number: detectNumber(full), date: detectDate(full), totals: detectTotals(full), items: [], warnings: [], orphans: [] };
    pages.forEach((text, pi) => {
      const lines = text.split("\n");
      const used = new Set();
      lines.forEach((line, idx) => {
        for (const m of line.matchAll(EAN_RE)) {
          const ean = m[1];
          if (!eanValid(ean)) continue;
          let rest = line.slice(0, m.index) + " " + line.slice(m.index + 13);
          rest = rest.replace(POSITION_RE, " ");
          let found = findQtyPrice(numbersIn(rest));
          if (!found) {
            for (const off of [-1, 1, -2, 2]) {
              const k = idx + off;
              if (k < 0 || k >= lines.length) continue;
              if ([...lines[k].matchAll(EAN_RE)].some(x => eanValid(x[1]))) continue;
              found = findQtyPrice(numbersIn(lines[k].replace(POSITION_RE, " ")));
              if (found) { used.add(k); break; }
            }
          }
          if (found) used.add(idx);
          if (found) inv.items.push({ ean, qty: found[0], price: found[1], value: found[2], line: line.trim().replace(/\s{2,}/g, "  "), page: pi + 1, on: true });
          else inv.warnings.push(`Str. ${pi + 1}: EAN ${ean} – nenašiel som množstvo a cenu.`);
        }
      });
      // Riadky, ktoré vyzerajú ako položka (počet × cena = hodnota), ale nemajú platný EAN
      lines.forEach((line, idx) => {
        if (used.has(idx) || TOTAL_WORDS.test(line)) return;
        if ([...line.matchAll(EAN_RE)].some(x => eanValid(x[1]))) return;
        const f = findQtyPrice(numbersIn(line.replace(POSITION_RE, " ")));
        if (!f || f[2] === undefined) return;
        let codes = [...line.matchAll(/(?<!\d)\d{8,14}(?!\d)/g)].map(x => x[0]);
        if (!codes.some(c => c.length === 13))
          for (const off of [1, -1, 2, -2]) {
            const near = [...(lines[idx + off] || "").matchAll(EAN_RE)].map(x => x[1]).filter(c => !eanValid(c));
            if (near.length) { codes = codes.concat(near); break; }
          }
        inv.orphans.push({ qty: f[0], price: f[1], value: f[2], code: codes.find(c => c.length >= 12) || "", badEan: codes.some(c => c.length === 13), line: line.trim().replace(/\s{2,}/g, "  "), page: pi + 1 });
      });
    });
    if (!inv.items.length) inv.warnings.push(full.trim() ? "Na faktúre sa nenašiel žiadny platný EAN." : "PDF neobsahuje text (asi sken) – treba ho najprv dať cez OCR.");
    return inv;
  }

  const amount = it => round2((it.qty * it.price) / SCALE);
  const total = items => items.reduce((s, it) => s + amount(it), 0n);
  const TOLERANCE = 50000n; // 0,05 – rozdiel zo zaokrúhľovania
  // Suma na faktúre najbližšia k súčtu položiek a rozdiel
  function totalCheck(inv, items) {
    const sum = total(items);
    if (!inv.totals.length) return { ok: null, sum };
    let best = inv.totals[0];
    for (const t of inv.totals) if (abs(sum - t) < abs(sum - best)) best = t;
    const diff = best - sum;
    return { ok: abs(diff) <= TOLERANCE, sum, doc: best, diff };
  }
  const totalOk = (inv, items) => totalCheck(inv, items).ok;

  // pevná dĺžka: EAN 1/14, počet 15/15, cena 30/15, mena 45/3, CRLF
  function formatLine(it, cur) {
    return it.ean.slice(0, 14).padEnd(14) + fmt(it.qty).padStart(15) + fmt(it.price).padStart(15) + cur.slice(0, 3).padEnd(3);
  }
  const toTxt = (items, cur) => items.map(it => formatLine(it, cur) + "\r\n").join("");

  // Poskladanie riadkov z textových položiek pdf.js ({str, x, y, w, h})
  function linesFromItems(items) {
    const its = items.filter(i => i.str && i.str.trim()).sort((a, b) => b.y - a.y || a.x - b.x);
    const rows = [];
    for (const it of its) {
      const tol = Math.max(2, (it.h || 8) * 0.35);
      let row = rows.find(r => Math.abs(r.y - it.y) <= tol);
      if (!row) rows.push(row = { y: it.y, items: [] });
      row.items.push(it);
    }
    rows.sort((a, b) => b.y - a.y);
    return rows.map(r => {
      r.items.sort((a, b) => a.x - b.x);
      let s = "", end = null;
      for (const it of r.items) {
        if (end !== null) {
          const gap = it.x - end;
          const cw = (it.h || 8) * 0.5;
          s += gap > cw * 1.2 ? "   " : gap > cw * 0.15 ? " " : "";
        }
        s += it.str;
        end = it.x + (it.w || it.str.length * (it.h || 8) * 0.5);
      }
      return s;
    }).join("\n");
  }

  return { totalCheck, TOLERANCE, parsePages, linesFromItems, toTxt, formatLine, amount, total, totalOk, fmt, toFixed, eanValid, CURRENCIES };
})();
if (typeof module !== "undefined") module.exports = FP;
