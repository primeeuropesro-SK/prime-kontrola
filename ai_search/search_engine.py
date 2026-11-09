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
    """How many typos we tolerate: none for short words, 1 for 4-6 letters, 2 for longer."""
    n = len(token)
    return 0 if n <= 3 or token.isdigit() else 1 if n <= 6 else 2


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


_PAREN_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_SPLIT_RE = re.compile(r"\s+[-–—|]\s+")


def _generic_phrases(title):
    """Descriptive parts of a product title, lowercased.

    'Procera Silus Winter KRT - Zimná pracovná bunda' -> ['zimná pracovná bunda']
    'Ochranné okuliare B501 clear' -> ['ochranné okuliare']
    """
    out = []
    for part in _SPLIT_RE.split(_PAREN_RE.sub(" ", title or "")):
        words = part.split()
        # keep the leading run of real words (stop at model codes / numbers / ALLCAPS)
        run = []
        for w in words:
            if any(ch.isdigit() for ch in w) or (w.isupper() and len(w) > 1) or not re.search(r"[^\W\d_]", w):
                break
            run.append(w.strip(",.;:/"))
        if 2 <= len(run) <= 5:
            out.append(" ".join(run).lower())
    return out


_META_CATEGORY_WORDS = ("výrobca", "gyártó", "novinky", "újdonság", "posledné kusy", "utolsó darabok", "akci", "archive")


def _is_meta_category(name):
    """Brand pages, 'Novinky', 'Posledné kusy'... - not useful as a search suggestion."""
    n = name.lower()
    return any(w in n for w in _META_CATEGORY_WORDS)


class SearchIndex:
    def __init__(self, docs, extras=None, k1=1.2, b=0.75):
        """docs: list of dicts produced by sync.normalize_product().
        extras: {"categories": {id: {name, url}}, "brands": {name: url}, "pages": [{title, url}]}."""
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
        self.by_id = {d["id"]: d for d in docs}
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
        extras = extras or {}
        self.category_urls = {}
        for d in docs:
            for cid, name in zip(d.get("category_ids", []), d.get("categories", [])):
                info = (extras.get("categories") or {}).get(str(cid))
                if info:
                    self.category_urls.setdefault(name, info["url"])
        self.brand_urls = dict(extras.get("brands") or {})
        # Brand pages are often plain categories such as "Artmas Výrobca" / "Artmas Gyártó".
        for m in self.manufacturers:
            for name, url in self.category_urls.items():
                fn = fold(name)
                if m not in self.brand_urls and fn.startswith(fold(m) + " ") and ("vyrobca" in fn or "gyarto" in fn):
                    self.brand_urls[m] = url
        self.pages = extras.get("pages") or []
        self._build_phrases()
        self.synonyms = []  # [(customer tokens, [catalogue phrases])]

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
                d = edit_distance(cq, ct)
                if d > maxd:
                    # Beginning of a longer word: an unfinished word (exact start) or an inflected
                    # form with a short ending (rukavice ~ rukaviciach), not prilba ~ priľnavosť.
                    dp = edit_distance(cq, ct[: len(cq)])
                    if dp == 0 or (dp <= maxd and len(ct) <= len(cq) + 3):
                        d = dp
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
        syn_used, _ = self.synonym_hits(query)
        for tok in tokenize(query):
            if tok in self.postings or tok.isdigit() or tok in syn_used:
                continue
            matches = self._expand(tok)
            if not matches:
                continue
            best = max(matches.items(), key=lambda x: (x[1], len(self.postings[x[0]])))
            if best[1] < 0.8 or (canon(tok) != tok and not best[0].startswith(tok)):
                out[tok] = self.display.get(best[0], best[0])
        return out

    # --------------------------------------------------------------- synonyms
    def set_synonyms(self, mapping):
        """mapping: {customer phrase: [catalogue phrases]} (see synonyms.py)."""
        out = []
        for customer, targets in (mapping or {}).items():
            toks = tokenize(customer)
            targets = [t for t in targets if tokenize(t)]
            if toks and targets:
                out.append((toks, targets))
        self.synonyms = out

    @staticmethod
    def _syn_match(ct, qt):
        """Customer-synonym word `ct` vs typed word `qt`: same word, inflected form or one typo."""
        if ct == qt or canon(ct) == canon(qt):
            return True
        # inflected form: kombinezón / kombinezónu, slúchadlá / slúchadlách (not svetlo for sveter)
        if len(ct) >= 5 and len(qt) >= 5 and (qt.startswith(ct[:-1]) or ct.startswith(qt[:-1])):
            return True
        return len(ct) >= 5 and edit_distance(canon(ct), canon(qt), limit=2) <= 1

    def synonym_hits(self, query):
        """(typed words covered by a synonym, [catalogue phrases]) for the query."""
        qt = tokenize(query)
        used, phrases = set(), []
        for toks, targets in self.synonyms:
            matched = []
            for ct in toks:
                m = next((q for q in qt if self._syn_match(ct, q)), None)
                if m is None:
                    break
                matched.append(m)
            else:
                used.update(matched)
                phrases += [t for t in targets if t not in phrases]
        return used, phrases

    def strict_count(self, query):
        """How many products match every word of the query (typos, inflection and synonyms
        allowed). 0 means the shop has nothing for what the customer asked - used for statistics."""
        q = fold(query).strip()
        if q in self.exact:
            return 1
        syn_used, syn_phrases = self.synonym_hits(query)
        syn_docs = set()
        for t in tokenize(" ".join(syn_phrases)):
            for term in self._expand(t):
                syn_docs.update(self.postings[term])
        sets = []
        for t in tokenize(query):
            docs = set()
            for term in self._expand(t):
                docs.update(self.postings[term])
            if t in syn_used:
                docs |= syn_docs
            sets.append(docs)
        if not sets:
            return 0
        return len(set.intersection(*sets))

    def score(self, query_terms):
        scores = defaultdict(float)
        for qt in query_terms:
            best = {}  # per query term, count the best-matching variant once per doc
            expansion = self._expand(qt)
            # Variants (unfinished word, other forms, typos) share the rarity of the most common
            # variant: for "proc" the frequent "procera" should beat a rare "procesoch".
            shared_idf = min((self.idf[t] for t in expansion), default=0.0)
            for term, bonus in expansion.items():
                idf = self.idf[term] if term == qt else shared_idf
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
        syn_used, syn_phrases = self.synonym_hits(query)
        if syn_used:
            # A word covered by a synonym is searched as the catalogue word instead, unless the
            # catalogue itself uses it often (then both are searched).
            terms = [t for t in terms if t not in syn_used or len(self.postings.get(t, ())) >= 3]
        scores = self.score(terms) if terms else defaultdict(float)
        if syn_phrases:
            syn_terms = [t for t in tokenize(" ".join(syn_phrases)) if t not in terms]
            for i, s in self.score(syn_terms).items():
                scores[i] += 0.9 * s
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

    # ------------------------------------------------------------ autocomplete
    def _build_phrases(self):
        """Search phrases customers can be offered while typing (našepkávač)."""
        counts = defaultdict(int)
        brands = {m for m in self.manufacturers if fold(m) not in ("no name", "")}
        for d in self.docs:
            for ph in _generic_phrases(d.get("title")):
                counts[ph] += 1
                if d.get("manufacturer") in brands:
                    counts[f"{d['manufacturer'].lower()} {ph}"] += 1
        phrases = {ph: n for ph, n in counts.items() if n >= 2}
        # Categories and brands weigh as much as the number of products they contain.
        per_cat, per_brand = defaultdict(int), defaultdict(int)
        for d in self.docs:
            for c in d.get("categories", []):
                per_cat[c] += 1
            per_brand[d.get("manufacturer")] += 1
        for c, n in per_cat.items():
            if "výrobca" not in c.lower() and "gyártó" not in c.lower():
                phrases[c.lower()] = max(phrases.get(c.lower(), 0), n)
        for m in brands:
            phrases[m.lower()] = max(phrases.get(m.lower(), 0), per_brand[m])
        self.phrases = list(phrases.items())
        self.phrase_tokens = [tokenize(ph) for ph, _ in self.phrases]
        self.phrase_index = defaultdict(set)
        for i, toks in enumerate(self.phrase_tokens):
            for t in toks:
                self.phrase_index[t].add(i)
        self.phrase_vocab = sorted(self.phrase_index)

    def suggest_queries(self, query, limit=6):
        """Complete what the customer is typing: 'proc zim' -> 'procera zimná pracovná bunda'.
        A known synonym ('kombinezón') first offers the catalogue's own word ('overal')."""
        _, syn = self.synonym_hits(query)
        rest = self._complete(query, limit)
        lead = [p.lower() for p in syn[:2] if fold(p) != fold(query).strip()]
        return (lead + [r for r in rest if fold(r) not in {fold(x) for x in lead}])[:limit]

    def _complete(self, query, limit):
        terms = tokenize(query)
        words = _TOKEN_RE.findall(fold(query))
        typing = bool(words) and not query.endswith(" ")
        if typing and (not terms or terms[-1] != words[-1]):
            terms.append(words[-1])  # unfinished word, even a stop-word-like "z" or "pr"
        if not terms:
            return []
        expanded = [self._expand(t) for t in terms]
        if typing:
            # The last word is still being typed: complete it from words used in phrases.
            last, cl = terms[-1], canon(terms[-1])
            done = dict(expanded[-1])
            for t in self._prefix_range(self.phrase_vocab, last, cap=400):
                done[t] = max(done.get(t, 0), 0.9)
            for t in self.phrase_vocab:
                if t not in done and canon(t).startswith(cl):
                    done[t] = 0.85
            expanded[-1] = done
        if not all(expanded):
            return []
        # candidates: phrases containing a match of the rarest query term
        rare = min(expanded, key=lambda e: sum(len(self.phrase_index.get(t, ())) for t in e))
        cands = set()
        for t in rare:
            cands |= self.phrase_index.get(t, set())
        q_fold = " ".join(terms)
        scored = []
        for i in cands:
            toks = self.phrase_tokens[i]
            score, used = 1.0, set()
            for e in expanded:
                best = max(((w, j) for j, t in enumerate(toks) if j not in used and (w := e.get(t))), default=None)
                if not best:
                    break
                score *= best[0]
                used.add(best[1])
            else:
                phrase, n = self.phrases[i]
                if " ".join(toks) == q_fold:
                    continue
                if min(used) == 0:
                    score *= 2.0  # phrase starts with what was typed
                score *= math.log(2 + n) / (1 + 0.08 * len(toks))
                scored.append((score, phrase))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out, seen = [], set()
        for _, ph in scored:
            key = fold(ph)
            if key not in seen:
                seen.add(key)
                out.append(ph)
            if len(out) >= limit:
                break
        return out

    def suggest_brands(self, query, limit=3):
        terms = tokenize(query)
        out = []
        for m in self.manufacturers:
            mt = tokenize(m)
            if mt and fold(m) != "no name" and any(any(t in self._expand(q) for t in mt) for q in terms):
                out.append({"name": m, "url": self.brand_urls.get(m)})
        return out[:limit]

    @staticmethod
    def _word_match(q, t):
        """Does query word `q` (maybe unfinished or misspelled) match word `t`?"""
        cq, ct = canon(q), canon(t)
        if t.startswith(stem(q)) or ct.startswith(stem(cq)):
            return True
        maxd = max_typos(cq)
        return maxd > 0 and min(edit_distance(cq, ct), edit_distance(cq, ct[: len(cq)])) <= maxd

    def suggest_pages(self, query, limit=3):
        """Info pages (warranty, returns, contact...) whose title matches every typed word."""
        terms = tokenize(query)
        if not terms:
            return []
        out = []
        for p in self.pages:
            pt = tokenize(p["title"])
            if all(any(self._word_match(q, t) for t in pt) for q in terms):
                out.append(p)
        return out[:limit]

    def top_categories(self, limit=8):
        counts = defaultdict(int)
        for d in self.docs:
            for c in d.get("categories", []):
                counts[c] += 1
        cats = [c for c, _ in sorted(counts.items(), key=lambda x: -x[1]) if not _is_meta_category(c)]
        return [{"name": c, "url": self.category_urls.get(c)} for c in cats[:limit]]

    def suggest_categories(self, query, limit=5):
        """Categories most common among the top hits (brand/"Výrobca" pages skipped)."""
        _, top = self.search(query, limit=30)
        counts = defaultdict(int)
        for rank, d in enumerate(top):
            for c in d.get("categories", []):
                if not _is_meta_category(c):
                    counts[c] += 30 - rank
        return [{"name": c, "url": self.category_urls.get(c)} for c, _ in sorted(counts.items(), key=lambda x: -x[1])[:limit]]
