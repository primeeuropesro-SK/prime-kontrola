"""Corrections the shop owner makes from the report: instructions for the AI, products pinned to
or hidden from a search, and ratings of AI answers. Stored in DATA_DIR/rules.json.

A pin/hide rule applies to every search that contains all words of its query, e.g. the rule
"zimné rukavice" also applies to "zimne rukavice do 10 €" (diacritics and case ignored).
"""
import hashlib
import json
import os
import threading
import time
import uuid

from ai_search.search_engine import fold, tokenize

KINDS = ("instructions", "pins", "hides")


class Rules:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"instructions": [], "pins": [], "hides": [], "ratings": {}}
        try:
            with open(path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (FileNotFoundError, ValueError):
            pass

    # ------------------------------------------------------------------ storage
    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def _add(self, kind, item):
        item = dict(item, id=uuid.uuid4().hex[:10], t=int(time.time()))
        with self.lock:
            self.data[kind].append(item)
            self._save()
        return item

    def add_instruction(self, lang, text):
        text = " ".join((text or "").split())[:500]
        return self._add("instructions", {"lang": lang, "text": text}) if text else None

    def add_pin(self, lang, query, pid):
        return self._add("pins", {"lang": lang, "query": query.strip()[:100], "pid": int(pid)})

    def add_hide(self, lang, query, pid):
        return self._add("hides", {"lang": lang, "query": query.strip()[:100], "pid": int(pid)})

    def remove(self, rule_id):
        with self.lock:
            for kind in KINDS:
                self.data[kind] = [r for r in self.data[kind] if r.get("id") != rule_id]
            self._save()

    def rate(self, key, rating, note=""):
        with self.lock:
            if rating in ("good", "bad"):
                self.data["ratings"][key] = {"rating": rating, "note": (note or "").strip()[:500], "t": int(time.time())}
            else:
                self.data["ratings"].pop(key, None)
            self._save()

    # ------------------------------------------------------------------ queries
    def list(self, kind, lang=None):
        with self.lock:
            return [dict(r) for r in self.data.get(kind, []) if lang is None or r.get("lang") == lang]

    def rating(self, key):
        with self.lock:
            return self.data["ratings"].get(key)

    def instructions(self, lang):
        return [r["text"] for r in self.list("instructions", lang)]

    def version(self, lang):
        """Changes whenever the AI instructions change (part of the AI cache key)."""
        return hashlib.sha256("\n".join(self.instructions(lang)).encode()).hexdigest()[:12]

    @staticmethod
    def matches(rule_query, query):
        rt = set(tokenize(rule_query))
        return bool(rt) and rt <= set(tokenize(query))

    def apply(self, lang, query, docs, by_id):
        """Hide and pin products for this query. by_id: {product id: doc} of the whole catalogue.
        Returns (docs, set of pinned ids)."""
        hidden = {r["pid"] for r in self.list("hides", lang) if self.matches(r["query"], query)}
        pins = [r["pid"] for r in self.list("pins", lang) if self.matches(r["query"], query)]
        pinned_docs = [by_id[p] for p in dict.fromkeys(pins) if p in by_id and p not in hidden]
        pinned_ids = {d["id"] for d in pinned_docs}
        rest = [d for d in docs if d["id"] not in hidden and d["id"] not in pinned_ids]
        return pinned_docs + rest, pinned_ids


def answer_key(event):
    """Stable id of one AI answer in the event log (to attach a rating to it)."""
    raw = f"{event.get('t')}|{event.get('lang')}|{event.get('sid')}|{fold(event.get('q', ''))}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
