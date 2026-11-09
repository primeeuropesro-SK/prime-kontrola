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


_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "y": "i", "w": "v", "q": "k"})


def canon(token):
    """Spelling-insensitive form used for typo matching.

    pr0cera -> procera, mykina -> mikina, rukavyce -> rukavice, kommbinovane -> kombinovane.
    Pure numbers (sizes, codes) are left alone.
    """
    if token.isdigit():
        return token
    t = token.translate(_LEET)
    return re.sub(r"(.)\1+", r"\1", t)


def edit_distance(a, b, limit=3):
    """Damerau-Levenshtein (optimal string alignment) distance, capped at `limit`."""
    if abs(len(a) - len(b)) >= limit:
        return limit
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) >= limit:
            return limit
        prev2, prev = prev, cur
    return min(prev[-1], limit)


def max_typos(token):
    """How many typos we tolerate: none for short words, 1 for 4-5 letters, 2 for longer."""
    n = len(token)
    return 0 if n <= 3 or token.isdigit() else 1 if n <= 5 else 2


def _deletes(word, depth):
    out, frontier = {word}, {word}
    for _ in range(depth):
        frontier = {w[:i] + w[i + 1:] for w in frontier for i in range(len(w))}
        out |= frontier
    return out


# Weight of a matched word by number of typos (exact word = 1.0).
TYPO_WEIGHT = {0: 0.8, 1: 0.6, 2: 0.35}


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
        self.display = {}  # folded word -> how it is written in product titles (zimna -> zimná)
        for i, d in enumerate(docs):
            for word in re.findall(r"\w+", d.get("title") or ""):
                self.display.setdefault(fold(word), word.lower())
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
        # Typo tolerance: spelling-normalised vocabulary + SymSpell-style delete index.
        self.canon_terms = defaultdict(list)  # canon form -> original terms
        for term in self.vocab:
            self.canon_terms[canon(term)].append(term)
        self.canon_vocab = sorted(self.canon_terms)
        self.delete_index = defaultdict(set)
        for c in self.canon_vocab:
            if len(c) >= 4 and not c.isdigit():
                for d in _deletes(c, 1):
                    self.delete_index[d].add(c)
        self._expand_cache = {}
        self.avg_len = sum(self.doc_len) / max(1, len(self.doc_len))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}
        self.categories = sorted({c for d in docs for c in d.get("categories", [])})
        self.manufacturers = sorted({d["manufacturer"] for d in docs if d.get("manufacturer")})

    @staticmethod
    def _prefix_range(sorted_list, prefix, cap=60):
        lo = bisect.bisect_left(sorted_list, prefix)
        out = []
        for j in range(lo, min(lo + cap, len(sorted_list))):
            if not sorted_list[j].startswith(prefix):
                break
            out.append(sorted_list[j])
        return out

    def _expand(self, token):
        """Map a query word to indexed words with a weight in (0, 1].

        Handles inflection (prefix of the stem), unfinished words while typing,
        spelling variants (pr0cera, mykina) and real typos (porcera, rukavuce).
        """
        cached = self._expand_cache.get(token)
        if cached is not None:
            return cached
        cq = canon(token)
        maxd = max_typos(cq)

        def weigh(terms, out):
            for term in terms:
                if term in out:
                    continue
                if term == token:
                    out[term] = 1.0
                    continue
                ct = canon(term)
                # Compare with the whole word and with its beginning (unfinished word / inflection).
                d = min(edit_distance(cq, ct), edit_distance(cq, ct[: len(cq)]))
                if d <= maxd:
                    # Same word after spelling normalisation (mykina = mikina) ranks above other forms.
                    out[term] = 0.9 if ct == cq else TYPO_WEIGHT[d]

        out = {}
        prefix = set(self._prefix_range(self.vocab, stem(token)))
        for c in self._prefix_range(self.canon_vocab, stem(cq)):
            prefix.update(self.canon_terms[c])
        weigh(prefix, out)
        # Real typo search only when the word (after spelling normalisation, pr0cera -> procera)
        # is rare or missing in the catalogue. A typo can also be in a product text itself.
        strong_df = sum(len(self.postings[t]) for t, w in out.items() if w >= 0.8)
        if maxd and strong_df < 3:
            fuzzy = set()
            for d in _deletes(cq, maxd):
                if d in self.canon_terms:
                    fuzzy.add(d)
                fuzzy |= self.delete_index.get(d, set())
            weigh((t for c in fuzzy for t in self.canon_terms[c]), out)
        if len(out) > 60:
            out = dict(sorted(out.items(), key=lambda x: -x[1])[:60])
        if len(self._expand_cache) > 20000:
            self._expand_cache.clear()
        self._expand_cache[token] = out
        return out

    def corrections(self, query):
        """{typed word: catalogue word} for words that were not found as typed."""
        out = {}
        for tok in tokenize(query):
            if tok in self.postings or tok.isdigit():
                continue
            matches = self._expand(tok)
            if not matches:
                continue
            best = max(matches.items(), key=lambda x: (x[1], len(self.postings[x[0]])))
            if best[1] < 0.8 or (canon(tok) != tok and not best[0].startswith(tok)):
                out[tok] = self.display.get(best[0], best[0])
        return out

    def score(self, query_terms):
        scores = defaultdict(float)
        for qt in query_terms:
            best = {}  # per query term, count the best-matching variant once per doc
            for term, bonus in self._expand(qt).items():
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
