"""HTTP API + widget hosting for the AI product search (stdlib only, plus optional `anthropic`).

Run:  python3 -m ai_search.server        (PORT=8080 by default)

Endpoints
  GET  /api/search?q=...&lang=sk&limit=8&ai=1   search (ai=0 -> instant lexical only)
  GET  /widget.js                               script to embed into the Upgates shop
  GET  /demo                                    test page with a search box
  GET  /healthz                                 status
  POST /admin/sync   (header X-Admin-Token)     reload products from Upgates now
"""
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

from ai_search import sync  # noqa: E402
from ai_search.ai import QueryAI  # noqa: E402
from ai_search.search_engine import SearchIndex  # noqa: E402

log = logging.getLogger("ai_search")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

PORT = int(os.environ.get("PORT", "8080"))
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "https://www.primework.sk,https://primework.sk,https://www.munkaruhazatolcson.hu"
).split(",") if o.strip()]
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
SYNC_INTERVAL_MIN = int(os.environ.get("SYNC_INTERVAL_MIN", "60"))
AI_RATE_PER_MIN = int(os.environ.get("AI_RATE_PER_MIN", "20"))  # per IP, protects API costs
PUBLIC_FIELDS = ("id", "code", "title", "url", "image", "price", "price_max", "currency",
                 "in_stock", "availability", "manufacturer", "categories")


class Store:
    """Holds one SearchIndex per language and swaps them atomically after a sync."""

    def __init__(self):
        self.indexes, self.meta, self.lock = {}, {}, threading.Lock()
        self.ai = QueryAI()

    def load(self, catalog):
        indexes = {lang: SearchIndex(data["products"]) for lang, data in catalog["languages"].items()}
        with self.lock:
            self.indexes = indexes
            self.meta = {"generated_at": catalog.get("generated_at"),
                         "products": {k: len(v.docs) for k, v in indexes.items()}}
        log.info("catalog loaded: %s", self.meta["products"])

    def sync_now(self):
        catalog = sync.build_catalog()
        sync.save_catalog(catalog)
        self.load(catalog)

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
            "categories": idx.suggest_categories(q),
            "corrections": idx.corrections(q),
            "ai": {"summary": ai_info.get("summary"), "keywords": ai_info.get("keywords")} if ai_info else None,
            "took_ms": int((time.time() - t0) * 1000),
        }


STORE = Store()
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
                return self._send(200, {"query": "", "total": 0, "products": [], "categories": [], "corrections": {}, "ai": None})
            result = STORE.search(q, lang, limit, use_ai and not ai_limited)
            if ai_limited:
                result["ai_rate_limited"] = True
            return self._send(200 if "error" not in result else 503, result, cache="no-store")
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


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        STORE.load(sync.load_catalog())
    except FileNotFoundError:
        log.info("no cached catalog, syncing from Upgates (takes a few minutes)...")
        STORE.sync_now()
    if SYNC_INTERVAL_MIN > 0:
        threading.Thread(target=_sync_loop, daemon=True).start()
    log.info("AI %s (model %s)", "enabled" if STORE.ai.enabled else "DISABLED - set ANTHROPIC_API_KEY",
             os.environ.get("AI_MODEL", "claude-haiku-5-5"))
    log.info("listening on :%d", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
