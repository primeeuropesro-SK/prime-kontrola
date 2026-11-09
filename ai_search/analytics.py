"""Search statistics and the weekly report.

Events are appended to DATA_DIR/events/YYYY-MM-DD.jsonl (Bratislava time). No IP address or
other personal data is stored: only the query, shop language, number of results, the clicked
product and a random id of the page view (to tell one search from the next).
"""
import csv
import html
import io
import json
import os
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Bratislava")
except Exception:  # pragma: no cover - no tz database available
    TZ = None

from ai_search.search_engine import fold

EVENT_TYPES = {"search", "ai", "suggestion", "all", "click"}
RETENTION_DAYS = 400
COUNTRY = {"sk": "Slovensko", "hu": "Maďarsko", "cs": "Česko"}


def now_local():
    return datetime.now(TZ) if TZ else datetime.now()


class EventLog:
    def __init__(self, directory):
        self.dir = directory
        self.lock = threading.Lock()

    def append(self, event):
        event = dict(event, t=int(time.time()))
        day = now_local().date().isoformat()
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with self.lock:
            os.makedirs(self.dir, exist_ok=True)
            with open(os.path.join(self.dir, f"{day}.jsonl"), "a", encoding="utf-8") as f:
                f.write(line)

    def read(self, start, end):
        """Events from day `start` to day `end` inclusive (datetime.date)."""
        d = start
        while d <= end:
            path = os.path.join(self.dir, f"{d.isoformat()}.jsonl")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            yield json.loads(line)
                        except ValueError:
                            continue
            d += timedelta(days=1)

    def cleanup(self):
        cutoff = (now_local().date() - timedelta(days=RETENTION_DAYS)).isoformat()
        for name in os.listdir(self.dir) if os.path.isdir(self.dir) else []:
            if name.endswith(".jsonl") and name[:10] < cutoff:
                os.remove(os.path.join(self.dir, name))


# ---------------------------------------------------------------------- aggregation
def group_searches(events):
    """Turn raw events into searches.

    While typing, one search produces several events ('proc', 'procera', a suggestion, a click).
    Events of the same page view whose queries extend each other within 5 minutes are one search;
    its final query is the longest one typed (or the one picked / clicked).
    """
    by_view = defaultdict(list)
    for e in events:
        if e.get("type") in EVENT_TYPES and e.get("q"):
            by_view[(e.get("lang"), e.get("sid"))].append(e)
    searches = []
    for (lang, _), evs in by_view.items():
        evs.sort(key=lambda e: e.get("t", 0))
        cur = None
        for e in evs:
            qf = " ".join(fold(e["q"]).split())
            if cur and e["t"] - cur["t"] <= 300 and (qf.startswith(cur["qf"]) or cur["qf"].startswith(qf)):
                if len(qf) >= len(cur["qf"]) or e["type"] != "search":
                    cur.update(qf=qf, q=e["q"].strip(), n=e.get("n", cur["n"]))
                cur["t"] = e["t"]
            else:
                cur = {"lang": lang, "qf": qf, "q": e["q"].strip(), "n": e.get("n", 0), "t": e["t"],
                       "clicks": [], "ai": False}
                searches.append(cur)
            if e["type"] == "click" and e.get("pid"):
                cur["clicks"].append(e["pid"])
            if e["type"] == "ai":
                cur["ai"] = True
    return searches


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def summarize(searches, products=None, top=20):
    """Report numbers per language. products: {lang: {id: (title, url)}}."""
    products = products or {}
    out = {}
    for lang in sorted({s["lang"] for s in searches}):
        ss = [s for s in searches if s["lang"] == lang]
        ok = [s for s in ss if s["clicks"]]
        zero = [s for s in ss if not s["clicks"] and s["n"] == 0]
        no_click = [s for s in ss if not s["clicks"] and s["n"] > 0]
        ai = [s for s in ss if s["ai"]]
        clicks = Counter(pid for s in ss for pid in s["clicks"])
        display = {}
        for s in ss:
            display.setdefault(s["qf"], s["q"].lower())

        def top_queries(items, n):
            c = Counter(s["qf"] for s in items)
            return [{"q": display[q], "count": k} for q, k in c.most_common(n)]

        query_counts = Counter(s["qf"] for s in ss)
        query_ok = Counter(s["qf"] for s in ok)
        catalog = products.get(lang, {})
        out[lang] = {
            "searches": len(ss),
            "successful": len(ok),
            "success_rate": _pct(len(ok), len(ss)),
            "zero_results": len(zero),
            "zero_rate": _pct(len(zero), len(ss)),
            "no_click": len(no_click),
            "ai_searches": len(ai),
            "ai_success_rate": _pct(sum(1 for s in ai if s["clicks"]), len(ai)),
            "top_products": [
                {"id": pid, "clicks": n, "title": catalog.get(pid, (f"#{pid}", None))[0], "url": catalog.get(pid, (None, None))[1]}
                for pid, n in clicks.most_common(top)
            ],
            "top_queries": [
                {"q": display[q], "count": n, "success_rate": _pct(query_ok[q], n)}
                for q, n in query_counts.most_common(top)
            ],
            "not_found": top_queries(zero, 50),
            "no_click_queries": top_queries(no_click, top),
        }
    return out


def week_range(iso_week=None):
    """(monday, sunday) of an ISO week 'YYYY-Www'; default = last complete week."""
    if iso_week:
        y, w = iso_week.split("-W")
        monday = date.fromisocalendar(int(y), int(w), 1)
    else:
        today = now_local().date()
        monday = today - timedelta(days=today.weekday() + 7)
    return monday, monday + timedelta(days=6)


def iso_week(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def build_report(log, products, week=None):
    start, end = week_range(week)
    cur = summarize(group_searches(log.read(start, end)), products)
    prev_start = start - timedelta(days=7)
    prev = summarize(group_searches(log.read(prev_start, prev_start + timedelta(days=6))), products)
    return {"week": iso_week(start), "start": start.isoformat(), "end": end.isoformat(),
            "prev_week": iso_week(prev_start), "next_week": iso_week(start + timedelta(days=7)),
            "langs": cur, "prev": prev}


# ---------------------------------------------------------------------- rendering
def _delta(cur, prev, key, unit=""):
    if prev is None or key not in prev:
        return ""
    d = round(cur[key] - prev[key], 1)
    if d == 0:
        return '<span class="d">±0</span>'
    color = "#2f7d32" if (d > 0) != (key in ("zero_rate", "zero_results")) else "#c62828"
    return f'<span class="d" style="color:{color}">{"+" if d > 0 else ""}{d}{unit}</span>'


def render_html(report, domains=None, base_url="", token=""):
    e = html.escape
    domains = domains or {}
    parts = [f"""<!doctype html><html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Report vyhľadávania {e(report['week'])}</title>
<style>
body{{font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f5f7;color:#222}}
main{{max-width:980px;margin:0 auto;padding:20px 16px 40px}} h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:19px;margin:28px 0 10px}}
h3{{font-size:15px;margin:18px 0 8px}} .sub{{color:#666}} .nav a{{margin-right:12px;color:#e4572e}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.kpi{{background:#fff;border-radius:10px;padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.kpi b{{display:block;font-size:22px}} .kpi span{{color:#666;font-size:12px}} .d{{font-size:12px;margin-left:6px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid #eee;vertical-align:top}} th{{background:#fafafa;font-size:12px;color:#666}}
td.n{{text-align:right;white-space:nowrap}} a{{color:#1f5fbf}} .cols{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
@media(max-width:700px){{.cols{{grid-template-columns:1fr}}}} .empty{{color:#888;background:#fff;padding:10px;border-radius:10px}}
</style></head><body><main>
<h1>Report vyhľadávania – týždeň {e(report['week'])}</h1>
<div class="sub">{e(report['start'])} – {e(report['end'])} · porovnanie s predchádzajúcim týždňom</div>"""]
    if base_url:
        q = f"&token={e(token)}" if token else ""
        parts.append(f'<p class="nav"><a href="{e(base_url)}?week={e(report["prev_week"])}{q}">← predchádzajúci týždeň</a>'
                     f'<a href="{e(base_url)}?week={e(report["next_week"])}{q}">nasledujúci týždeň →</a>'
                     f'<a href="{e(base_url)}/not-found.csv?week={e(report["week"])}{q}">hľadali a nenašli (CSV)</a></p>')
    if not report["langs"]:
        parts.append('<p class="empty">V tomto týždni nie sú zaznamenané žiadne vyhľadávania.</p>')
    for lang, r in report["langs"].items():
        p = report["prev"].get(lang)
        parts.append(f"<h2>{e(COUNTRY.get(lang, lang.upper()))} <span class='sub'>{e(domains.get(lang, ''))}</span></h2>")
        parts.append('<div class="kpis">'
                     f'<div class="kpi"><b>{r["searches"]}{_delta(r, p, "searches")}</b><span>vyhľadávaní</span></div>'
                     f'<div class="kpi"><b>{r["success_rate"]} %{_delta(r, p, "success_rate", " b.")}</b><span>úspešnosť (klik na produkt)</span></div>'
                     f'<div class="kpi"><b>{r["zero_rate"]} %{_delta(r, p, "zero_rate", " b.")}</b><span>nenašli ({r["zero_results"]})</span></div>'
                     f'<div class="kpi"><b>{r["no_click"]}</b><span>s výsledkami, ale bez kliku</span></div>'
                     f'<div class="kpi"><b>{r["ai_searches"]}</b><span>AI vyhľadávaní, úspešnosť {r["ai_success_rate"]} %</span></div>'
                     "</div>")

        def table(title, head, rows):
            if not rows:
                return f"<h3>{e(title)}</h3><p class='empty'>Žiadne údaje.</p>"
            return (f"<h3>{e(title)}</h3><table><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>"
                    + "".join("<tr>" + "".join(rows_) + "</tr>" for rows_ in rows) + "</table>")

        prod_rows = [[f'<td class="n">{i}.</td>',
                      f'<td>{f"<a href={chr(34)}{e(x["url"])}{chr(34)}>{e(x["title"])}</a>" if x["url"] else e(x["title"])}</td>',
                      f'<td class="n">{x["clicks"]}</td>'] for i, x in enumerate(r["top_products"], 1)]
        parts.append(table("Top 20 produktov z vyhľadávania", ["#", "Produkt", "Kliknutia"], prod_rows))
        parts.append('<div class="cols"><div>')
        parts.append(table("Hľadali a nenašli", ["Výraz", "Počet"],
                           [[f"<td>{e(x['q'])}</td>", f'<td class="n">{x["count"]}</td>'] for x in r["not_found"]]))
        parts.append("</div><div>")
        parts.append(table("Našli, ale neklikli", ["Výraz", "Počet"],
                           [[f"<td>{e(x['q'])}</td>", f'<td class="n">{x["count"]}</td>'] for x in r["no_click_queries"]]))
        parts.append("</div></div>")
        parts.append(table("Top 20 hľadaných výrazov", ["Výraz", "Počet", "Úspešnosť"],
                           [[f"<td>{e(x['q'])}</td>", f'<td class="n">{x["count"]}</td>', f'<td class="n">{x["success_rate"]} %</td>']
                            for x in r["top_queries"]]))
    parts.append('<p class="sub" style="margin-top:28px">Úspešnosť = podiel vyhľadávaní, po ktorých zákazník klikol na produkt. '
                 '„Hľadali a nenašli“ = v e-shope nie je produkt, ktorý by obsahoval všetky hľadané slová '
                 '(preklepy a synonymá sa zohľadňujú). Tip: takéto výrazy doplňte do ai_search/synonyms.json, '
                 'do názvov či popisov produktov, alebo zvážte rozšírenie sortimentu.</p>'
                 "</main></body></html>")
    return "".join(parts)


def not_found_csv(report):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["krajina", "výraz", "počet"])
    for lang, r in report["langs"].items():
        for x in r["not_found"]:
            w.writerow([COUNTRY.get(lang, lang), x["q"], x["count"]])
    return "﻿" + buf.getvalue()  # BOM so Excel opens it with diacritics
