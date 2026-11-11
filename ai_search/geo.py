"""IP addresses of searching visitors: where they are (city, region, country) and how often they came.

* Location comes from ipinfo.io (set IPINFO_TOKEN for its free 50 000 lookups / month; without a
  token it allows a smaller number). Each IP is looked up once, in a background thread, and cached
  in DATA_DIR/geo_cache.json, so the report never waits for it.
* Visits: a visit is a new page view (widget session) of an IP; counted in DATA_DIR/ip_stats.json.
* GDPR: IP addresses are personal data. They are kept IP_RETENTION_DAYS (default 90) and then
  removed from the event log and from these files - mention this in the shop's privacy policy.
"""
import ipaddress
import json
import logging
import os
import queue
import threading
import time
import urllib.request

log = logging.getLogger("ai_search.geo")
IPINFO_TOKEN = os.environ.get("IPINFO_TOKEN", "")
IP_RETENTION_DAYS = int(os.environ.get("IP_RETENTION_DAYS", "90"))


def is_public(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_reserved or a.is_link_local or a.is_multicast)


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


class GeoCache:
    """ip -> "Bratislava, Bratislava, SK". Unknown IPs are looked up in the background."""

    def __init__(self, path, fetch=None):
        self.path = path
        self.lock = threading.Lock()
        self.data = _load_json(path)
        self.fetch = fetch or self._ipinfo
        self.todo = queue.Queue()
        self.pending = set()
        self.dirty = 0
        threading.Thread(target=self._worker, daemon=True).start()

    @staticmethod
    def _ipinfo(ip):
        url = f"https://ipinfo.io/{ip}/json" + (f"?token={IPINFO_TOKEN}" if IPINFO_TOKEN else "")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=8) as r:
            d = json.loads(r.read())
        parts = [d.get("city"), d.get("region"), d.get("country")]
        place = ", ".join(dict.fromkeys(p for p in parts if p))
        return place or "neznáma"

    def get(self, ip):
        """Cached location, or None (then it is queued and appears on the next report load)."""
        if not ip:
            return ""
        if not is_public(ip):
            return "vnútorná sieť"
        with self.lock:
            hit = self.data.get(ip)
            if hit is None and ip not in self.pending:
                self.pending.add(ip)
                self.todo.put(ip)
        return hit["place"] if hit else None

    def _worker(self):
        while True:
            ip = self.todo.get()
            try:
                place = self.fetch(ip)
            except Exception as e:  # rate limit, network... try again later
                log.warning("geo lookup %s failed: %s", ip, e)
                with self.lock:
                    self.pending.discard(ip)
                time.sleep(5)
                continue
            with self.lock:
                self.data[ip] = {"place": place, "t": int(time.time())}
                self.pending.discard(ip)
                self.dirty += 1
                if self.dirty >= 5 or self.todo.empty():
                    _save_json(self.path, self.data)
                    self.dirty = 0
            time.sleep(0.2)  # be gentle with the free API

    def forget_older_than(self, seconds):
        cutoff = time.time() - seconds
        with self.lock:
            self.data = {ip: v for ip, v in self.data.items() if v.get("t", 0) >= cutoff}
            _save_json(self.path, self.data)


class VisitStats:
    """How many times each IP has come (a visit = a new widget page view), first / last seen."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = _load_json(path)  # ip -> {"visits", "first", "last", "sid"}
        self.dirty = 0

    def record(self, ip, sid):
        if not ip:
            return
        now = int(time.time())
        with self.lock:
            s = self.data.setdefault(ip, {"visits": 0, "first": now, "last": now, "sid": None})
            if sid and sid != s.get("sid"):
                s["visits"] += 1
                s["sid"] = sid
            s["last"] = now
            self.dirty += 1
            if self.dirty >= 20:
                self._save()

    def _save(self):
        try:
            _save_json(self.path, self.data)
            self.dirty = 0
        except OSError as e:
            log.warning("cannot save visit stats: %s", e)

    def get(self, ip):
        with self.lock:
            return dict(self.data.get(ip) or {})

    def flush(self):
        with self.lock:
            self._save()

    def forget_older_than(self, seconds):
        cutoff = time.time() - seconds
        with self.lock:
            self.data = {ip: v for ip, v in self.data.items() if v.get("last", 0) >= cutoff}
            self._save()
