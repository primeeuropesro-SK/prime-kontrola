"""Minimal Upgates API v2 client (stdlib only).

Configuration via environment variables:
  UPGATES_BASE_URL  e.g. https://prime-work.admin.s35.upgates.com/api/v2
  UPGATES_LOGIN     API login (optional if auth is injected by a proxy)
  UPGATES_API_KEY   API key   (optional if auth is injected by a proxy)
"""
import base64
import json
import os
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

    def get(self, endpoint, **params):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise UpgatesError(e.code, e.read().decode(errors="replace")[:500]) from None

    def paginate(self, endpoint, key=None, max_pages=None, **params):
        """Yield items from all pages. Upgates paginates only via `page` (no `limit`)."""
        key = key or endpoint.split("/")[0]
        page = 1
        while True:
            data = self.get(endpoint, page=page, **params)
            yield from data.get(key, [])
            if page >= data.get("number_of_pages", 1) or (max_pages and page >= max_pages):
                break
            page += 1
