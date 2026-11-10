"""Minimal Upgates API v2 client (stdlib only).

Configuration via environment variables:
  UPGATES_BASE_URL  e.g. https://prime-work.admin.s35.upgates.com/api/v2
  UPGATES_LOGIN     API login (optional if auth is injected by a proxy)
  UPGATES_API_KEY   API key   (optional if auth is injected by a proxy)
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://prime-work.admin.s35.upgates.com/api/v2"


class UpgatesError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never follow redirects: Upgates echoes credentials in the Location header.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UpgatesClient:
    def __init__(self, base_url=None, login=None, api_key=None, timeout=60):
        self.base_url = (base_url or os.environ.get("UPGATES_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        login = login or os.environ.get("UPGATES_LOGIN")
        api_key = api_key or os.environ.get("UPGATES_API_KEY")
        self.timeout = timeout
        self.headers = {"Accept": "application/json"}
        if login and api_key:
            token = base64.b64encode(f"{login}:{api_key}".encode()).decode()
            self.headers["Authorization"] = f"Basic {token}"
        self._opener = urllib.request.build_opener(_NoRedirect)

    def get(self, endpoint, object_pairs_hook=None, **params):
        """GET an endpoint. `object_pairs_hook` is passed to json.loads (e.g. to drop
        unneeded fields while parsing large responses)."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read(), object_pairs_hook=object_pairs_hook)
        except urllib.error.HTTPError as e:
            raise UpgatesError(e.code, e.read().decode(errors="replace")[:500]) from None

    def stream_items(self, endpoint, key, object_pairs_hook=None, **params):
        """GET one page and yield the objects of its `key` array one by one while downloading.

        A page of products is ~40 MB of JSON; parsing it whole needs several times that in memory.
        Here only one product is held at a time. Returns the other top-level fields (e.g.
        number_of_pages) via the generator's return value.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self.headers)
        try:
            resp = self._opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise UpgatesError(e.code, e.read().decode(errors="replace")[:500]) from None
        with resp:
            meta = yield from _iter_array(resp, key.encode(), object_pairs_hook)
        return meta

    def paginate(self, endpoint, key=None, max_pages=None, object_pairs_hook=None, **params):
        """Yield items from all pages. Upgates paginates only via `page` (no `limit`)."""
        key = key or endpoint.split("/")[0]
        page = 1
        while True:
            data = yield from self.stream_items(endpoint, key, object_pairs_hook=object_pairs_hook, page=page, **params)
            if page >= data.get("number_of_pages", 1) or (max_pages and page >= max_pages):
                break
            page += 1


_SPECIAL = re.compile(rb'["{}\]]')
_STR_END = re.compile(rb'["\\]')


def _iter_array(fp, key, object_pairs_hook, chunk=1 << 18):
    """Stream-parse `{"...": ..., "<key>": [ {...}, {...} ], ...}` from a file object.

    Yields each array element (parsed with json.loads) and returns the other top-level
    fields as a dict. Strings and escapes are respected, so braces inside text are safe.
    """
    buf = bytearray()
    outside = bytearray()          # the JSON around the array, for number_of_pages etc.
    state = "before"               # before -> in_array -> after
    marker = b'"' + key + b'"'
    depth = 0
    in_str = esc = False
    start = None
    pos = 0
    while True:
        data = fp.read(chunk)
        if data:
            buf += data
        if state == "before":
            i = buf.find(marker)
            j = buf.find(b"[", i + len(marker)) if i >= 0 else -1
            if j < 0:
                if not data:
                    break
                continue
            outside += buf[:i] + marker + b":[]"
            del buf[:j + 1]
            state, pos = "in_array", 0
        if state == "in_array":
            while True:
                if in_str:
                    m = _STR_END.search(buf, pos)       # jump to the next quote / backslash
                    if not m:
                        pos = len(buf)
                        break
                    pos = m.start()
                    if buf[pos] == 0x5C:               # backslash: skip the escaped byte
                        if pos + 1 >= len(buf):
                            break                      # need more data
                        pos += 2
                        continue
                    in_str = False
                    pos += 1
                    continue
                m = _SPECIAL.search(buf, pos)          # jump to the next " { } ]
                if not m:
                    pos = len(buf)
                    break
                pos = m.start()
                c = buf[pos]
                if c == 0x22:
                    in_str = True
                elif c == 0x7B:
                    if depth == 0:
                        start = pos
                    depth += 1
                elif c == 0x7D:
                    depth -= 1
                    if depth == 0:
                        yield json.loads(bytes(buf[start:pos + 1]), object_pairs_hook=object_pairs_hook)
                        del buf[:pos + 1]
                        pos, start = -1, None
                elif c == 0x5D and depth == 0:
                    del buf[:pos + 1]
                    state = "after"
                    break
                pos += 1
        if state == "after":
            outside += buf
            buf = bytearray()
            if not data:
                break
            outside += fp.read()
            break
        if not data:
            break
    try:
        meta = json.loads(bytes(outside))
    except ValueError:
        meta = {}
    meta.pop(key.decode(), None)
    return meta
