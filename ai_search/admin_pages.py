"""Owner pages for reviewing AI answers and managing corrections (rules).

/report/ai     - every AI answer of the week: how the AI understood the query, which products it
                 showed and why, what the customer did; buttons to rate it, pin / hide a product
                 for that query or add an instruction for the AI.
/report/rules  - all corrections in one place, with delete buttons.
Both need the ADMIN_TOKEN; changes are POSTed to /admin/action.
"""
import html
from collections import defaultdict
from datetime import timedelta

from ai_search import analytics
from ai_search.rules import answer_key
from ai_search.search_engine import fold

COUNTRY = analytics.COUNTRY
CSS = """
body{font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f5f7;color:#222}
main{max-width:1000px;margin:0 auto;padding:20px 16px 40px}h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:26px 0 10px}
.sub{color:#666}.nav a{margin-right:14px;color:#e4572e}.card{background:#fff;border-radius:12px;padding:14px 16px;margin:12px 0;
box-shadow:0 1px 3px rgba(0,0,0,.08)}.card.good{border-left:4px solid #2f7d32}.card.bad{border-left:4px solid #c62828}
.q{font-size:16px;font-weight:700}.meta{color:#777;font-size:12px}.ai{background:#fff8ec;border-radius:8px;padding:8px 10px;margin:8px 0}
.kw{display:inline-block;background:#f1f1f1;border-radius:999px;padding:1px 8px;margin:2px 3px 0 0;font-size:12px}
ol{margin:6px 0 0;padding-left:22px}li{margin:4px 0}.r{color:#2f7d32;font-size:12px}.pin{color:#1f5fbf;font-size:12px}
form.inline{display:inline}button,.btn{font:inherit;font-size:12px;border:1px solid #ccc;background:#fff;border-radius:6px;padding:2px 8px;
cursor:pointer;margin-left:4px}button.good{border-color:#2f7d32;color:#2f7d32}button.bad{border-color:#c62828;color:#c62828}
button.on{background:#222;color:#fff;border-color:#222}input[type=text],textarea,select{font:inherit;font-size:13px;border:1px solid #ccc;
border-radius:6px;padding:4px 8px}textarea{width:100%;min-height:54px;box-sizing:border-box}.row{display:flex;gap:8px;flex-wrap:wrap;
align-items:center;margin-top:8px}.cust{font-size:12px;margin-top:6px}.tabs a{margin-right:10px}.tabs a.on{font-weight:700;color:#222}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden}th,td{text-align:left;padding:7px 10px;
border-bottom:1px solid #eee;vertical-align:top}th{background:#fafafa;font-size:12px;color:#666}.empty{color:#888;background:#fff;padding:10px;border-radius:10px}
"""


def _e(x):
    return html.escape(str(x if x is not None else ""))


def ai_answers(log, start, end, rules):
    """AI answers of the period with what the customer did afterwards, newest first."""
    events = list(log.read(start, end))
    clicks = defaultdict(set)    # (sid, folded q) -> clicked product ids
    feedback = {}                # (sid, folded q) -> up / down
    for e in events:
        k = (e.get("sid"), fold(e.get("q", "")).strip())
        if e.get("type") == "click" and e.get("pid"):
            clicks[k].add(e["pid"])
        elif e.get("type") == "ai_feedback":
            feedback[k] = e.get("v")
    out = []
    for e in events:
        if e.get("type") != "ai_result":
            continue
        k = (e.get("sid"), fold(e.get("q", "")).strip())
        key = answer_key(e)
        out.append(dict(e, key=key, clicked=clicks.get(k, set()), customer=feedback.get(k), owner=rules.rating(key)))
    out.sort(key=lambda a: -a.get("t", 0))
    return out


def _hidden(token, back, **fields):
    h = f'<input type="hidden" name="token" value="{_e(token)}"><input type="hidden" name="back" value="{_e(back)}">'
    return h + "".join(f'<input type="hidden" name="{_e(k)}" value="{_e(v)}">' for k, v in fields.items())


def _form(token, back, label, cls="", **fields):
    return (f'<form class="inline" method="post" action="/admin/action">{_hidden(token, back, **fields)}'
            f'<button class="{cls}">{label}</button></form>')


def render_ai_page(answers, week, products, token, flt, domains=None):
    start, end = analytics.week_range(week)
    wk = analytics.iso_week(start)
    back = f"/report/ai?token={token}&week={wk}&filter={flt}"
    tq = f"&token={_e(token)}"
    counts = {
        "all": len(answers),
        "unrated": sum(1 for a in answers if not a["owner"]),
        "bad": sum(1 for a in answers if (a["owner"] or {}).get("rating") == "bad" or a["customer"] == "down"),
        "noclick": sum(1 for a in answers if not a["clicked"]),
    }
    shown = {
        "all": answers,
        "unrated": [a for a in answers if not a["owner"]],
        "bad": [a for a in answers if (a["owner"] or {}).get("rating") == "bad" or a["customer"] == "down"],
        "noclick": [a for a in answers if not a["clicked"]],
    }.get(flt, answers)[:300]
    labels = {"all": "Všetky", "unrated": "Nehodnotené", "bad": "Zlé (👎)", "noclick": "Bez kliku"}
    tabs = "".join(f'<a class="{"on" if k == flt else ""}" href="/report/ai?week={wk}&filter={k}{tq}">{v} ({counts[k]})</a>'
                   for k, v in labels.items())
    parts = [f"""<!doctype html><html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI odpovede {wk}</title><style>{CSS}</style></head><body><main>
<h1>AI odpovede – týždeň {wk}</h1><div class="sub">{start:%d.%m.%Y} – {end:%d.%m.%Y}</div>
<p class="nav"><a href="/report?week={wk}{tq}">← report</a><a href="/report/ai?week={analytics.iso_week(start - timedelta(days=7))}&filter={flt}{tq}">predchádzajúci týždeň</a>
<a href="/report/ai?week={analytics.iso_week(start + timedelta(days=7))}&filter={flt}{tq}">nasledujúci týždeň</a><a href="/report/rules?{tq[1:]}">pravidlá a pokyny pre AI</a></p>
<p class="tabs">{tabs}</p>"""]
    if not shown:
        parts.append('<p class="empty">Žiadne AI odpovede v tomto výbere.</p>')
    for a in shown:
        lang = a.get("lang", "sk")
        catalog = products.get(lang, {})
        rating = (a["owner"] or {}).get("rating")
        cls = "good" if rating == "good" else "bad" if rating == "bad" else ""
        cust = {"up": "👍 zákazníkovi pomohlo", "down": "👎 zákazníkovi nepomohlo"}.get(a["customer"], "")
        clicked = [catalog.get(p, (f"#{p}", None))[0] for p in a["clicked"]]
        parts.append(f'<div class="card {cls}"><div class="meta">{_e(analytics.fmt_time(a.get("t")))} · {_e(COUNTRY.get(lang, lang))}</div>'
                     f'<div class="q">„{_e(a.get("q"))}“</div>')
        if a.get("ok"):
            kws = "".join(f'<span class="kw">{_e(k)}</span>' for k in a.get("keywords") or [])
            flt_txt = ", ".join(f"{_e(k)}: {_e(v)}" for k, v in (a.get("filters") or {}).items())
            parts.append(f'<div class="ai"><b>AI pochopila:</b> {_e(a.get("summary"))}<div>{kws}</div>'
                         + (f'<div class="meta">filtre: {flt_txt}</div>' if flt_txt else "") + "</div>")
        else:
            parts.append('<div class="ai"><b>AI neodpovedala</b> – zákazník dostal bežné výsledky.</div>')
        parts.append("<ol>")
        for pid, reason in a.get("products") or []:
            title, url = catalog.get(pid, (f"produkt #{pid} (už nie je v katalógu)", None))
            link = f'<a href="{_e(url)}" target="_blank">{_e(title)}</a>' if url else _e(title)
            mark = ' <span class="pin">📌 pripnutý</span>' if pid in (a.get("pinned") or []) else ""
            star = " ✅ <b>klikol</b>" if pid in a["clicked"] else ""
            parts.append(f'<li>{link}{mark}{star}' + (f'<div class="r">✔ {_e(reason)}</div>' if reason else "")
                         + _form(token, back, "📌 Pripnúť pre tento výraz", action="pin", lang=lang, q=a.get("q"), pid=pid)
                         + _form(token, back, "🚫 Skryť pre tento výraz", action="hide", lang=lang, q=a.get("q"), pid=pid) + "</li>")
        parts.append("</ol>")
        parts.append(f'<div class="cust">{_e(cust)}{" · " if cust and clicked else ""}'
                     f'{"klikol na: " + _e(", ".join(clicked)) if clicked else "" if cust else "zákazník neklikol na žiadny produkt"}</div>')
        note = (a["owner"] or {}).get("note", "")
        parts.append(f'<form method="post" action="/admin/action" class="row">{_hidden(token, back, action="rate", key=a["key"])}'
                     f'<button name="rating" value="good" class="good {"on" if rating == "good" else ""}">👍 Dobrá odpoveď</button>'
                     f'<button name="rating" value="bad" class="bad {"on" if rating == "bad" else ""}">👎 Zlá odpoveď</button>'
                     f'<input type="text" name="note" value="{_e(note)}" placeholder="poznámka (čo bolo zle)" style="flex:1;min-width:180px">'
                     f'</form>')
        parts.append(f'<form method="post" action="/admin/action" class="row">{_hidden(token, back, action="instruction", lang=lang)}'
                     f'<input type="text" name="text" placeholder="Pokyn pre AI, napr. Pri slove „zimné“ uprednostni zateplené produkty." '
                     f'style="flex:1;min-width:220px"><button>➕ Pridať pokyn pre AI</button></form>')
        parts.append(f'<form method="post" action="/admin/action" class="row">{_hidden(token, back, action="pin", lang=lang, q=a.get("q"))}'
                     f'<input type="text" name="code" placeholder="kód produktu, ktorý tu chýba" style="width:200px">'
                     f'<button>📌 Pripnúť iný produkt</button></form></div>')
    parts.append("</main></body></html>")
    return "".join(parts)


def render_rules_page(rules, products, token, langs):
    back = f"/report/rules?token={token}"
    tq = f"token={_e(token)}"

    def name(lang, pid):
        title, url = products.get(lang, {}).get(pid, (f"#{pid}", None))
        return f'<a href="{_e(url)}" target="_blank">{_e(title)}</a>' if url else _e(title)

    def delete(rule_id):
        return _form(token, back, "Zmazať", action="delete", rule_id=rule_id)

    lang_opts = "".join(f'<option value="{_e(l)}">{_e(COUNTRY.get(l, l))}</option>' for l in langs)
    parts = [f"""<!doctype html><html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pravidlá vyhľadávania</title><style>{CSS}</style></head><body><main>
<h1>Pravidlá a pokyny pre AI</h1><div class="sub">Opravy, ktoré platia pre vyhľadávanie na e-shope. Prejavia sa okamžite.</div>
<p class="nav"><a href="/report?{tq}">← report</a><a href="/report/ai?{tq}&filter=unrated">AI odpovede</a></p>
<h2>Pokyny pre AI</h2>"""]
    ins = rules.list("instructions")
    if ins:
        parts.append("<table><tr><th>Krajina</th><th>Pokyn</th><th>Pridané</th><th></th></tr>" + "".join(
            f"<tr><td>{_e(COUNTRY.get(r['lang'], r['lang']))}</td><td>{_e(r['text'])}</td>"
            f"<td>{_e(analytics.fmt_time(r['t']))}</td><td>{delete(r['id'])}</td></tr>" for r in ins) + "</table>")
    else:
        parts.append('<p class="empty">Zatiaľ žiadne pokyny.</p>')
    parts.append(f'<form method="post" action="/admin/action" class="row">{_hidden(token, back, action="instruction")}'
                 f'<select name="lang">{lang_opts}</select><input type="text" name="text" style="flex:1;min-width:240px" '
                 f'placeholder="napr. Keď zákazník hľadá „do zimy“, ponúkni iba zateplené produkty."><button>➕ Pridať</button></form>')
    for kind, title, action, help_text in (
        ("pins", "Pripnuté produkty", "pin", "Produkt sa zobrazí navrchu pri každom vyhľadávaní, ktoré obsahuje všetky slová výrazu."),
        ("hides", "Skryté produkty", "hide", "Produkt sa nezobrazí pri vyhľadávaní, ktoré obsahuje všetky slová výrazu."),
    ):
        parts.append(f"<h2>{title}</h2><p class='sub'>{help_text}</p>")
        items = rules.list(kind)
        if items:
            parts.append("<table><tr><th>Krajina</th><th>Výraz</th><th>Produkt</th><th>Pridané</th><th></th></tr>" + "".join(
                f"<tr><td>{_e(COUNTRY.get(r['lang'], r['lang']))}</td><td>{_e(r['query'])}</td><td>{name(r['lang'], r['pid'])}</td>"
                f"<td>{_e(analytics.fmt_time(r['t']))}</td><td>{delete(r['id'])}</td></tr>" for r in items) + "</table>")
        else:
            parts.append('<p class="empty">Zatiaľ žiadne.</p>')
        parts.append(f'<form method="post" action="/admin/action" class="row">{_hidden(token, back, action=action)}'
                     f'<select name="lang">{lang_opts}</select><input type="text" name="q" placeholder="výraz, napr. zimné rukavice">'
                     f'<input type="text" name="code" placeholder="kód produktu" style="width:160px"><button>➕ Pridať</button></form>')
    parts.append("<p class='sub' style='margin-top:24px'>Synonymá (slová, ktoré zákazníci používajú inak ako katalóg) sa upravujú "
                 "v súbore ai_search/synonyms.json na GitHube.</p></main></body></html>")
    return "".join(parts)
