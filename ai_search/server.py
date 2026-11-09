"""HTTP API + widget hosting for the AI product search (stdlib only, plus optional `anthropic`).

Run:  python3 -m ai_search.server        (PORT=8080 by default)

Endpoints
  GET  /api/search?q=...&lang=sk&limit=8&ai=1   search (ai=0 -> instant lexical only)
  GET  /widget.js                               script to embed into the Upgates shop
  GET  /demo                                    test page with a search box
  GET  /healthz                                 status
  POST /admin/sync   (header X-Admin-Token)     reload products from Upgates now
"""
import hashlib
import hmac
import json
import logging
import os
import sys
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_search import analytics, mailer, sync, synonyms  # noqa: E402
from ai_search.ai import QueryAI  # noqa: E402
from ai_search.search_engine import SearchIndex, tokenize  # noqa: E402

log = logging.getLogger("ai_search")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

PORT = int(os.environ.get("PORT", "8080"))
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "https://www.primework.sk,https://primework.sk,https://www.munkaruhazatolcson.hu"
).split(",") if o.strip()]
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
SYNC_INTERVAL_MIN = int(os.environ.get("SYNC_INTERVAL_MIN", "60"))
AI_RATE_PER_MIN = int(os.environ.get("AI_RATE_PER_MIN", "20"))  # per IP, protects API costs
POPULAR_MIN_USERS = int(os.environ.get("POPULAR_MIN_USERS", "3"))
TRACK_RATE_PER_MIN = int(os.environ.get("TRACK_RATE_PER_MIN", "120"))
PUBLIC_FIELDS = ("id", "code", "title", "url", "image", "price", "price_max", "currency",
                 "in_stock", "availability", "manufacturer", "categories")


class Store:
    """Holds one SearchIndex per language and swaps them atomically after a sync."""

    def __init__(self):
        self.indexes, self.meta, self.lock = {}, {}, threading.Lock()
        self.domains = {}
        self.ai = QueryAI()

    def load(self, catalog):
        indexes = {lang: SearchIndex(data["products"], data) for lang, data in catalog["languages"].items()}
        with self.lock:
            self.indexes = indexes
            self.meta = {"generated_at": catalog.get("generated_at"),
                         "products": {k: len(v.docs) for k, v in indexes.items()}}
        self.domains = {k: v.get("domain") for k, v in catalog["languages"].items()}
        log.info("catalog loaded: %s", self.meta["products"])
        self.apply_synonyms()

    def apply_synonyms(self):
        with self.lock:
            indexes = dict(self.indexes)
        for lang, idx in indexes.items():
            idx.set_synonyms(synonyms.merged(sync.DATA_DIR, lang))

    def refresh_synonyms(self):
        """Create / refresh the automatic synonym lists (one cheap AI call per language)."""
        with self.lock:
            indexes = dict(self.indexes)
        changed = False
        for lang, idx in indexes.items():
            try:
                changed |= synonyms.ensure_auto(sync.DATA_DIR, lang, idx, self.ai)
            except Exception as e:
                log.warning("synonyms for %s failed: %s", lang, e)
        if changed:
            self.apply_synonyms()

    def phrases_by_lang(self):
        with self.lock:
            return {lang: [ph for ph, _ in idx.phrases] for lang, idx in self.indexes.items()}

    def report(self, week=None):
        report = analytics.build_report(EVENTS, self.products_by_id(), week)
        return analytics.add_demand(report, self.ai, os.path.join(sync.DATA_DIR, "demand"), self.phrases_by_lang())

    def products_by_id(self):
        with self.lock:
            return {lang: {d["id"]: (d["title"], d.get("url")) for d in idx.docs} for lang, idx in self.indexes.items()}

    def sync_now(self):
        catalog = sync.build_catalog()
        sync.save_catalog(catalog)
        self.load(catalog)
        self.refresh_synonyms()

    def index(self, lang):
        with self.lock:
            return self.indexes.get(lang) or next(iter(self.indexes.values()), None)

    def search(self, q, lang, limit, use_ai):
        idx = self.index(lang)
        if idx is None:
            return {"error": "catalog not loaded"}
        t0 = time.time()
        ai_info = self.ai.understand(q, lang, idx) if use_ai else None
        filters, extra = {}, None
        if ai_info:
            filters = {
                "categories": ai_info.get("categories") or None,
                "manufacturers": ai_info.get("manufacturers") or None,
                "min_price": ai_info.get("min_price"),
                "max_price": ai_info.get("max_price"),
                "in_stock_only": ai_info.get("in_stock_only"),
            }
            extra = ai_info.get("keywords")
        pool = max(limit, 25) if ai_info else limit
        total, docs = idx.search(q, limit=pool, filters=filters, extra_terms=extra)
        if ai_info and total == 0 and any(filters.values()):
            # Filters were too strict (e.g. price) - fall back to keywords only.
            total, docs = idx.search(q, limit=pool, extra_terms=extra)

        reasons = {}
        if ai_info and docs:
            ranked = self.ai.rerank(q, lang, docs, limit)
            if ranked:
                by_id = {d["id"]: d for d in docs}
                reasons = dict(ranked)
                docs = [by_id[i] for i, _ in ranked if i in by_id] or docs
        products = []
        for d in docs[:limit]:
            item = {k: d.get(k) for k in PUBLIC_FIELDS}
            if d["id"] in reasons:
                item["reason"] = reasons[d["id"]]
            products.append(item)
        return {
            "query": q,
            "lang": lang,
            "total": total,
            "products": products,
            "suggestions": idx.suggest_queries(q),
            "categories": idx.suggest_categories(q),
            "brands": idx.suggest_brands(q),
            "pages": idx.suggest_pages(q),
            "corrections": idx.corrections(q),
            "ai": {"summary": ai_info.get("summary"), "keywords": ai_info.get("keywords")} if ai_info else None,
            "took_ms": int((time.time() - t0) * 1000),
        }


class Popular:
    """Popular searches shown when the search box is empty.

    Only queries made of real catalogue words, typed by at least POPULAR_MIN_USERS
    different visitors, are shown - so nobody can push arbitrary text to other customers.
    """

    def __init__(self, path):
        self.path, self.lock, self.dirty = path, threading.Lock(), 0
        self.data = defaultdict(dict)  # lang -> {query: [ip hashes]}
        try:
            with open(path, encoding="utf-8") as f:
                for lang, qs in json.load(f).items():
                    self.data[lang] = qs
        except (FileNotFoundError, ValueError):
            pass

    def record(self, lang, q, ip, idx):
        q = " ".join(q.lower().split())[:60]
        terms = q.split()
        if not (1 <= len(terms) <= 5) or idx is None:
            return
        if any(t not in idx.postings for t in tokenize(q)) or not tokenize(q):
            return
        h = hashlib.sha256((ip + "|prime").encode()).hexdigest()[:10]
        with self.lock:
            users = self.data[lang].setdefault(q, [])
            if h not in users and len(users) < 200:
                users.append(h)
                self.dirty += 1
            if self.dirty >= 10:
                self._save()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
            os.replace(self.path + ".tmp", self.path)
            self.dirty = 0
        except OSError as e:
            log.warning("cannot save popular searches: %s", e)

    def top(self, lang, limit=8):
        with self.lock:
            items = [(q, len(u)) for q, u in self.data.get(lang, {}).items() if len(u) >= POPULAR_MIN_USERS]
        return [q for q, _ in sorted(items, key=lambda x: -x[1])[:limit]]


STORE = Store()
POPULAR = Popular(os.path.join(sync.DATA_DIR, "popular.json"))
EVENTS = analytics.EventLog(os.path.join(sync.DATA_DIR, "events"))
_track_rate = defaultdict(deque)


def _track_allowed(ip):
    now = time.time()
    with _rate_lock:
        q = _track_rate[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= TRACK_RATE_PER_MIN:
            return False
        q.append(now)
        return True


def _token_ok(token):
    """A '+' in a generated token arrives as a space in a URL query string - accept both."""
    if not ADMIN_TOKEN:
        return False
    token = token or ""
    return any(hmac.compare_digest(t.encode(), ADMIN_TOKEN.encode()) for t in (token, token.replace(" ", "+")))
_rate = defaultdict(deque)
_rate_lock = threading.Lock()


def _ai_allowed(ip):
    now = time.time()
    with _rate_lock:
        q = _rate[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= AI_RATE_PER_MIN:
            return False
        q.append(now)
        return True


class Handler(BaseHTTPRequestHandler):
    server_version = "PrimeAISearch/1.0"

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin and (origin in ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")

    def _send(self, status, body, ctype="application/json; charset=utf-8", cache=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", cache)
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name, ctype):
        try:
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                self._send(200, f.read(), ctype, cache="public, max-age=300")
        except FileNotFoundError:
            self._send(404, {"error": "not found"})

    def _client_ip(self):
        fwd = self.headers.get("X-Forwarded-For")
        return fwd.split(",")[0].strip() if fwd else self.client_address[0]

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/search":
            qs = parse_qs(url.query)
            q = (qs.get("q", [""])[0] or "").strip()[:200]
            lang = qs.get("lang", ["sk"])[0]
            try:
                limit = max(1, min(30, int(qs.get("limit", ["8"])[0])))
            except ValueError:
                limit = 8
            use_ai = qs.get("ai", ["0"])[0] == "1" and len(q) >= 3
            ai_limited = use_ai and not _ai_allowed(self._client_ip())
            if not q:
                idx = STORE.index(lang)
                return self._send(200, {
                    "query": "", "total": 0, "products": [], "suggestions": [], "brands": [], "pages": [],
                    "corrections": {}, "ai": None,
                    "popular": POPULAR.top(lang),
                    "categories": idx.top_categories() if idx else [],
                }, cache="no-store")
            result = STORE.search(q, lang, limit, use_ai and not ai_limited)
            if ai_limited:
                result["ai_rate_limited"] = True
            return self._send(200 if "error" not in result else 503, result, cache="no-store")
        if url.path == "/api/track":
            # The widget reports what customers search and click (for statistics and popular searches).
            qs = parse_qs(url.query)
            lang = qs.get("lang", ["sk"])[0][:5]
            q = (qs.get("q", [""])[0] or "").strip()[:100]
            kind = qs.get("type", ["enter"])[0]
            kind = kind if kind in analytics.EVENT_TYPES else "all"
            ip = self._client_ip()
            idx = STORE.index(lang)
            if q and idx is not None and _track_allowed(ip):
                event = {"type": kind, "lang": lang, "q": q, "sid": (qs.get("sid", [""])[0] or "")[:16],
                         "n": idx.strict_count(q)}
                try:
                    pid = int(qs.get("pid", [""])[0])
                    event["pid"] = pid
                except ValueError:
                    pass
                try:
                    EVENTS.append(event)
                except OSError as e:
                    log.warning("cannot write event: %s", e)
                if kind != "search":
                    POPULAR.record(lang, q, ip, idx)
            self.send_response(204)
            self._cors()
            self.end_headers()
            return
        if url.path == "/admin/sync":
            # Reload products from Upgates now (e.g. after changing API permissions); opened in a browser.
            if not _token_ok(parse_qs(url.query).get("token", [""])[0]):
                return self._send(403, b"<h1>403</h1><p>Chyba alebo chybny token.</p>", "text/html; charset=utf-8")
            threading.Thread(target=_initial_sync, daemon=True).start()
            return self._send(200, "<meta charset='utf-8'><p>Aktualizácia katalógu z Upgates sa spustila. Potrvá asi "
                                   "3–5 minút, potom stránku e-shopu obnovte.</p>".encode("utf-8"), "text/html; charset=utf-8")
        if url.path in ("/report", "/report/not-found.csv", "/report/demand.csv"):
            qs = parse_qs(url.query)
            token = qs.get("token", [""])[0]
            if not _token_ok(token):
                return self._send(403, b"<h1>403</h1><p>Chyba alebo chybny token.</p>", "text/html; charset=utf-8")
            try:
                report = STORE.report(qs.get("week", [None])[0])
            except ValueError:
                return self._send(400, {"error": "week must look like 2026-W45"})
            if url.path.endswith(".csv"):
                body = analytics.demand_csv(report) if "demand" in url.path else analytics.not_found_csv(report)
                return self._send(200, body.encode("utf-8"), "text/csv; charset=utf-8", cache="no-store")
            page = analytics.render_html(report, STORE.domains, "/report", token)
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8", cache="no-store")
        if url.path == "/widget.js":
            return self._static("widget.js", "application/javascript; charset=utf-8")
        if url.path in ("/", "/demo"):
            return self._static("demo.html", "text/html; charset=utf-8")
        if url.path == "/healthz":
            return self._send(200, {"ok": bool(STORE.indexes), "ai": bool(STORE.ai.enabled), **STORE.meta})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path == "/admin/sync":
            if not ADMIN_TOKEN or self.headers.get("X-Admin-Token") != ADMIN_TOKEN:
                return self._send(403, {"error": "forbidden"})
            try:
                STORE.sync_now()
            except Exception as e:
                return self._send(500, {"error": str(e)[:300]})
            return self._send(200, {"ok": True, **STORE.meta})
        self._send(404, {"error": "not found"})


def _sync_loop():
    while True:
        time.sleep(SYNC_INTERVAL_MIN * 60)
        try:
            STORE.sync_now()
        except Exception as e:
            log.warning("periodic sync failed: %s", e)


def _weekly_loop():
    """Every Monday morning: e-mail last week's report (when SMTP is configured) and clean old events."""
    state_path = os.path.join(sync.DATA_DIR, "report_state.json")
    while True:
        try:
            now = analytics.now_local()
            if now.weekday() == 0 and now.hour >= mailer.SEND_HOUR:
                try:
                    with open(state_path, encoding="utf-8") as f:
                        state = json.load(f)
                except (FileNotFoundError, ValueError):
                    state = {}
                report = STORE.report()
                if state.get("sent_week") != report["week"]:
                    if mailer.configured():
                        mailer.send(f"Report vyhľadávania {report['week']}", analytics.render_html(report, STORE.domains))
                        log.info("weekly report %s e-mailed", report["week"])
                    EVENTS.cleanup()
                    with open(state_path, "w", encoding="utf-8") as f:
                        json.dump({"sent_week": report["week"]}, f)
        except Exception as e:
            log.warning("weekly report failed: %s", e)
        time.sleep(900)


def _initial_sync():
    try:
        STORE.sync_now()
    except Exception as e:
        log.error("initial sync from Upgates failed: %s", e)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        STORE.load(sync.load_catalog())
        threading.Thread(target=STORE.refresh_synonyms, daemon=True).start()
    except FileNotFoundError:
        # Start listening right away (hosting health checks), load products in the background.
        log.info("no cached catalog, syncing from Upgates in the background (takes a few minutes)...")
        threading.Thread(target=_initial_sync, daemon=True).start()
    if SYNC_INTERVAL_MIN > 0:
        threading.Thread(target=_sync_loop, daemon=True).start()
    threading.Thread(target=_weekly_loop, daemon=True).start()
    log.info("AI %s (model %s)", "enabled" if STORE.ai.enabled else "DISABLED - set ANTHROPIC_API_KEY",
             os.environ.get("AI_MODEL", "claude-haiku-5-5"))
    log.info("listening on :%d", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
