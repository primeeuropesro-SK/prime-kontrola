"""Fast lexical product search (BM25 + diacritics folding + prefix "stemming").

No external dependencies. Designed for a catalogue of a few thousand products,
so everything lives in memory and a query takes ~1 ms.
"""
import bisect
import math
import re
import unicodedata
from collections import defaultdict

# Field weights: a hit in the title counts much more than one in the long description.
FIELD_WEIGHTS = {
    "title": 3.0,
    "categories": 2.0,
    "manufacturer": 2.0,
    "short_description": 1.0,
    "variants": 1.0,
    "long_description": 0.4,
}

STOPWORDS = {
    # sk
    "a", "aj", "alebo", "na", "do", "pre", "pri", "s", "so", "v", "vo", "z", "zo", "k", "ku",
    "o", "od", "po", "za", "je", "su", "ktore", "ktory", "ako", "co", "nieco", "chcem",
    "hladam", "potrebujem", "mi", "ma", "som", "by", "bol", "nejake", "nejaku", "nejaky",
    "kde", "aky", "aka", "ake", "najlepsie", "dobre", "dobry",
    # hu
    "es", "egy", "az", "a", "vagy", "hogy", "nem", "kell", "keresek", "valami",
}

_TAG_RE = re.compile(r"<[^>]+>")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def fold(text):
    """Lowercase and strip diacritics: 'Pracovné Rukavice' -> 'pracovne rukavice'."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def strip_html(html):
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def tokenize(text):
    return [t for t in _TOKEN_RE.findall(fold(text)) if t not in STOPWORDS]


def stem(token):
    """Very small Slovak/Hungarian-friendly stem: keep the beginning of the word.

    Inflected forms share a prefix (rukavice / rukavic / rukaviciach), so a query
    term matches any indexed word that starts with its stem.
    """
    if token.isdigit() or len(token) <= 4:
        return token
    return token[: max(4, len(token) - 2)]


class SearchIndex:
    def __init__(self, docs, k1=1.2, b=0.75):
        """docs: list of dicts produced by sync.normalize_product()."""
        self.docs = docs
        self.k1, self.b = k1, b
        self.postings = defaultdict(dict)  # term -> {doc_idx: weighted tf}
        self.doc_len = []
        self.exact = {}  # folded code / ean -> doc_idx
        for i, d in enumerate(docs):
            length = 0.0
            for field, w in FIELD_WEIGHTS.items():
                value = d.get(field) or ""
                if isinstance(value, list):
                    value = " ".join(value)
                for tok in tokenize(value):
                    self.postings[tok][i] = self.postings[tok].get(i, 0.0) + w
                    length += w
            self.doc_len.append(length or 1.0)
            for key in (d.get("code"), d.get("ean"), *d.get("variant_codes", [])):
                if key:
                    self.exact[fold(str(key))] = i
        self.vocab = sorted(self.postings)
        self.avg_len = sum(self.doc_len) / max(1, len(self.doc_len))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}
        self.categories = sorted({c for d in docs for c in d.get("categories", [])})
        self.manufacturers = sorted({d["manufacturer"] for d in docs if d.get("manufacturer")})

    def _expand(self, token):
        """All vocabulary terms that start with the stem of `token`."""
        s = stem(token)
        lo = bisect.bisect_left(self.vocab, s)
        out = []
        for j in range(lo, len(self.vocab)):
            term = self.vocab[j]
            if not term.startswith(s):
                break
            out.append(term)
            if len(out) >= 50:
                break
        return out

    def score(self, query_terms):
        scores = defaultdict(float)
        for qt in query_terms:
            best = {}  # per query term, count the best-matching variant once per doc
            for term in self._expand(qt):
                # Exact word beats a prefix match.
                bonus = 1.0 if term == qt else 0.7
                idf = self.idf[term]
                for i, tf in self.postings[term].items():
                    norm = tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avg_len))
                    s = idf * norm * bonus
                    if s > best.get(i, 0.0):
                        best[i] = s
            for i, s in best.items():
                scores[i] += s
        # Reward documents that match all query terms.
        if len(query_terms) > 1:
            for i in scores:
                hits = sum(1 for qt in query_terms if any(i in self.postings[t] for t in self._expand(qt)))
                scores[i] *= 0.5 + 0.5 * hits / len(query_terms)
        return scores

    def search(self, query, limit=10, filters=None, extra_terms=None):
        """Return (total, [docs]) sorted by relevance.

        filters: dict with optional keys categories (list), manufacturers (list),
                 min_price, max_price, in_stock_only.
        extra_terms: additional keywords (e.g. synonyms from the AI step) with lower weight.
        """
        filters = filters or {}
        q = fold(query).strip()
        if q in self.exact:
            return 1, [self.docs[self.exact[q]]]

        terms = tokenize(query)
        scores = self.score(terms) if terms else defaultdict(float)
        if extra_terms:
            extra = [t for t in tokenize(" ".join(extra_terms)) if t not in terms]
            for i, s in self.score(extra).items():
                scores[i] += 0.6 * s

        if not scores and filters.get("categories"):
            # Pure filter query ("lacné rukavice do 5 €" might reduce to a category only).
            scores = {i: 1.0 for i in range(len(self.docs))}

        results = []
        for i, s in scores.items():
            d = self.docs[i]
            if not self._passes(d, filters):
                continue
            if filters.get("categories") and set(filters["categories"]) & set(d.get("categories", [])):
                s *= 1.5
            if d.get("in_stock"):
                s *= 1.05
            results.append((s, i))
        results.sort(key=lambda x: (-x[0], self.docs[x[1]].get("title", "")))
        return len(results), [self.docs[i] for _, i in results[:limit]]

    @staticmethod
    def _passes(d, f):
        price = d.get("price")
        if f.get("min_price") is not None and (price is None or price < f["min_price"]):
            return False
        if f.get("max_price") is not None and (price is None or price > f["max_price"]):
            return False
        if f.get("in_stock_only") and not d.get("in_stock"):
            return False
        if f.get("manufacturers") and d.get("manufacturer") not in f["manufacturers"]:
            return False
        if f.get("categories") and f.get("strict_categories"):
            if not set(f["categories"]) & set(d.get("categories", [])):
                return False
        return True

    def suggest_categories(self, query, limit=5):
        """Categories most common among the top hits (brand/"Výrobca" pages skipped)."""
        _, top = self.search(query, limit=30)
        counts = defaultdict(int)
        for rank, d in enumerate(top):
            for c in d.get("categories", []):
                if "výrobca" not in c.lower() and "gyártó" not in c.lower():
                    counts[c] += 30 - rank
        return [c for c, _ in sorted(counts.items(), key=lambda x: -x[1])[:limit]]
