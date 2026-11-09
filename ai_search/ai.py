"""AI layer: Claude turns a natural-language query into search terms + filters,
and optionally re-ranks the candidates the lexical engine found.

The search keeps working without it (no API key / SDK missing -> lexical only).
"""
import json
import logging
import os
import threading
from collections import OrderedDict

log = logging.getLogger("ai_search.ai")

MODEL = os.environ.get("AI_MODEL", "claude-haiku-5-5")  # cheapest; e.g. claude-sonnet-5-5 for higher quality
EFFORT = os.environ.get("AI_EFFORT", "low")  # search must be quick; raise for better reasoning
RERANK = os.environ.get("AI_RERANK", "1") == "1"
RERANK_CANDIDATES = int(os.environ.get("AI_RERANK_CANDIDATES", "25"))

# Models that support the server-side refusal fallback (Claude Haiku 5.5 does not).
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

LANG_NAMES = {"sk": "slovenčina", "hu": "maďarčina (magyar)", "cs": "čeština", "en": "English"}
# Said in the customer's own language, so the AI does not drift into the (Slovak) prompt language.
ANSWER_IN = {
    "sk": "Vetu summary napíš po slovensky.",
    "hu": "Vetu summary napíš VÝHRADNE po maďarsky. Az összefoglaló mondatot kizárólag magyarul írd meg.",
    "cs": "Vetu summary napíš po česky. Shrnutí napiš česky.",
}
REASONS_IN = {
    "sk": "Dôvody napíš po slovensky.",
    "hu": "Dôvody (reason) napíš VÝHRADNE po maďarsky. Az indoklást kizárólag magyarul írd.",
    "cs": "Dôvody napíš po česky.",
}

try:
    import anthropic
except ImportError:  # pragma: no cover - optional dependency
    anthropic = None


def _nullable_number():
    return {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _owner_rules(instructions):
    if not instructions:
        return ""
    return ("\n\nPokyny majiteľa e-shopu (dodrž ich, ak sa týkajú dopytu):\n"
            + "\n".join(f"- {i}" for i in instructions))


class _LRU:
    def __init__(self, size=500):
        self.size, self.data, self.lock = size, OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                return self.data[key]
        return None

    def put(self, key, value):
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)


class QueryAI:
    def __init__(self, client=None):
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
        self.enabled = client is not None or (anthropic is not None and has_key)
        self.client = client or (anthropic.Anthropic(max_retries=1, timeout=20.0) if self.enabled else None)
        self.cache = _LRU()

    # ------------------------------------------------------------------ helpers
    def _call(self, system, user, schema, max_tokens=2000):
        params = dict(
            model=MODEL,
            max_tokens=max_tokens,
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        if MODEL in FALLBACK_MODELS:
            response = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        else:
            response = self.client.messages.create(**params)
        if response.stop_reason in ("refusal", "max_tokens"):
            log.warning("AI stopped with %s", response.stop_reason)
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        return json.loads(text) if text else None

    # -------------------------------------------------------- query understanding
    def understand(self, query, lang, index, instructions=()):
        """Return {"keywords", "categories", "manufacturers", "min_price", "max_price",
        "in_stock_only", "summary"} or None when AI is unavailable.
        instructions: the shop owner's own rules for the AI (from the report)."""
        if not self.enabled:
            return None
        instructions = tuple(instructions or ())
        key = ("u", lang, query.strip().lower(), instructions)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        schema = {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}},
                "categories": {"type": "array", "items": {"type": "string", "enum": index.categories or [""]}},
                "manufacturers": {"type": "array", "items": {"type": "string", "enum": index.manufacturers or [""]}},
                "min_price": _nullable_number(),
                "max_price": _nullable_number(),
                "in_stock_only": {"type": "boolean"},
                "summary": {"type": "string"},
            },
            "required": ["keywords", "categories", "manufacturers", "min_price", "max_price", "in_stock_only", "summary"],
            "additionalProperties": False,
        }
        system = (
            "Si vyhľadávací asistent e-shopu s pracovným oblečením, obuvou, rukavicami a ochrannými "
            "pomôckami (OOPP). Zákazník napíše, čo hľadá, často voľne a bez presných názvov. "
            "Preveď dopyt na parametre pre fulltextové vyhľadávanie v katalógu.\n\n"
            "Pravidlá:\n"
            "- Zákazníci robia preklepy, gramatické chyby a píšu bez diakritiky (pr0cera, porcera, mykina, "
            "rukavyce, zateplene). Vždy ich oprav na správny tvar podľa katalógu a výrobcov.\n"
            "- keywords: 3–10 krátkych slov alebo fráz v jazyku katalógu, ako by boli v názve alebo popise "
            "produktu (synonymá, odborné výrazy, normy – napr. S1P, S3, EN388, EN ISO 20471). Napr. "
            "'topánky s oceľovou špičkou' -> poltopánka, bakanče, špica, S1, S3. Bez výplňových slov.\n"
            "- categories: iba kategórie zo zoznamu, ktoré zjavne zodpovedajú dopytu; inak prázdne pole.\n"
            "- manufacturers: iba ak zákazník spomína značku.\n"
            "- min_price/max_price: iba ak zákazník uvedie cenu (v mene e-shopu, s DPH); inak null.\n"
            "- in_stock_only: true iba ak zákazník chce tovar skladom/ihneď.\n"
            "- summary: jedna krátka veta pre zákazníka v jeho jazyku, čo hľadáme "
            "(napr. 'Hľadám zimné zateplené pracovné rukavice do 10 €.').\n\n"
            f"Kategórie katalógu: {json.dumps(index.categories, ensure_ascii=False)}\n"
            f"Výrobcovia: {json.dumps(index.manufacturers, ensure_ascii=False)}"
        ) + _owner_rules(instructions)
        user = (f"Jazyk katalógu a zákazníka: {LANG_NAMES.get(lang, lang)}\nDopyt zákazníka: {query}\n"
                + ANSWER_IN.get(lang, f"Vetu summary napíš v jazyku: {LANG_NAMES.get(lang, lang)}."))
        try:
            result = self._call(system, user, schema, max_tokens=2000)
        except Exception as e:  # never break search because of the AI step
            log.warning("AI understand failed: %s", e)
            return None
        if result:
            self.cache.put(key, result)
        return result

    # --------------------------------------------------------------- synonyms
    def synonyms(self, lang, phrases):
        """Words customers use for the catalogue's products that the catalogue itself does not use.
        Returns [{"customer": "...", "catalog": "<one of phrases>"}] or None."""
        if not (self.enabled and phrases):
            return None
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "customer": {"type": "string"},
                            "catalog": {"type": "string", "enum": phrases},
                        },
                        "required": ["customer", "catalog"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        }
        system = (
            "Pomáhaš vyhľadávaniu e-shopu s pracovným oblečením, obuvou, rukavicami a OOPP. "
            "Dostaneš zoznam výrazov, ktoré používa katalóg. Vypíš slová a krátke frázy, ktoré zákazníci "
            "bežne píšu do vyhľadávania pre tie isté produkty, ale v katalógu nie sú: synonymá, hovorové "
            "a nárečové názvy, zastarané alebo nepresné pomenovania, anglicizmy, iné tvary slov. "
            "Ku každému priraď najbližší výraz z katalógu. Píš v jazyku katalógu, malými písmenami, "
            "s diakritikou. Bez značiek, bez výrazov, ktoré už v zozname sú, bez zjavne nesúvisiacich slov. "
            "Najviac 250 položiek."
        )
        user = f"Jazyk katalógu: {LANG_NAMES.get(lang, lang)}\nVýrazy katalógu:\n" + "\n".join(phrases)
        try:
            result = self._call(system, user, schema, max_tokens=16000)
        except Exception as e:
            log.warning("AI synonyms failed: %s", e)
            return None
        if not result:
            return None
        seen, out = set(), []
        for it in result["items"]:
            c = " ".join(it["customer"].lower().split())[:60]
            if c and c not in seen and c != it["catalog"].lower():
                seen.add(c)
                out.append({"customer": c, "catalog": it["catalog"]})
        return out

    # --------------------------------------------------------- product demand
    def product_demand(self, lang, queries, phrases):
        """Group searches that found nothing into products the shop could add.

        queries: [str] typed by customers; phrases: the catalogue's own phrases.
        Returns [{"product", "queries", "status", "catalog_phrase", "note"}] or None.
        status: missing = the shop does not sell it, synonym = it does but customers call it
        differently (catalog_phrase = the catalogue's word), unclear = nonsense / not a product."""
        if not (self.enabled and queries):
            return None
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product": {"type": "string"},
                            "queries": {"type": "array", "items": {"type": "string", "enum": queries}},
                            "status": {"type": "string", "enum": ["missing", "synonym", "unclear"]},
                            "catalog_phrase": {"type": "string", "enum": [""] + phrases},
                            "note": {"type": "string"},
                        },
                        "required": ["product", "queries", "status", "catalog_phrase", "note"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        }
        system = (
            "Si nákupca e-shopu s pracovným oblečením, obuvou, rukavicami a OOPP. Dostaneš výrazy, ktoré "
            "zákazníci hľadali a e-shop k nim nenašiel vhodný produkt, a zoznam výrazov, ktoré katalóg používa. "
            "Zoskup výrazy, ktoré znamenajú ten istý produkt (preklepy, synonymá, iné tvary, iný jazyk). "
            "Pre každú skupinu: product = krátky výstižný názov produktu PO SLOVENSKY (aj keď zákazníci písali "
            "po maďarsky), status = 'synonym' ak e-shop taký produkt podľa zoznamu katalógu zjavne predáva a "
            "zákazník ho len nazval inak (catalog_phrase = zodpovedajúci výraz z katalógu), 'missing' ak ho "
            "katalóg nemá (catalog_phrase = ''), 'unclear' pre nezmysly, testy a výrazy, ktoré nie sú produkt "
            "(catalog_phrase = ''). note = jedna krátka veta po slovensky pre majiteľa e-shopu (napr. čo by "
            "malo byť v sortimente: typ, norma, použitie). Každý výraz zaraď do najviac jednej skupiny."
        )
        user = (f"Jazyk zákazníkov: {LANG_NAMES.get(lang, lang)}\nHľadané výrazy:\n" + "\n".join(queries)
                + "\n\nVýrazy katalógu:\n" + "\n".join(phrases))
        try:
            result = self._call(system, user, schema, max_tokens=16000)
        except Exception as e:
            log.warning("AI product demand failed: %s", e)
            return None
        return result["items"] if result else None

    # ----------------------------------------------------------------- rerank
    def rerank(self, query, lang, candidates, limit, instructions=()):
        """Return [(product_id, reason)] ordered by relevance, or None."""
        if not (self.enabled and RERANK and candidates):
            return None
        instructions = tuple(instructions or ())
        ids = [c["id"] for c in candidates]
        key = ("r", lang, query.strip().lower(), tuple(ids), instructions)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        listing = [
            {
                "id": c["id"],
                "title": c["title"],
                "categories": c.get("categories", [])[:4],
                "price": c.get("price"),
                "in_stock": c.get("in_stock"),
                "info": (c.get("short_description") or c.get("long_description") or "")[:240],
            }
            for c in candidates
        ]
        schema = {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer", "enum": ids},
                            "reason": {"type": "string"},
                        },
                        "required": ["id", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["results"],
            "additionalProperties": False,
        }
        system = (
            "Si predajca v e-shope s pracovným oblečením a OOPP. Z kandidátov vyber produkty, ktoré najlepšie "
            f"zodpovedajú dopytu zákazníka, zoradené od najvhodnejšieho (najviac {limit}). Vynechaj tie, ktoré "
            "zjavne nesedia. Ku každému napíš krátky dôvod (max 12 slov) v jazyku zákazníka. "
            "Nevymýšľaj vlastnosti, ktoré nie sú v údajoch."
        ) + _owner_rules(instructions)
        user = (f"Dopyt: {query}\nJazyk zákazníka: {LANG_NAMES.get(lang, lang)}\n"
                + REASONS_IN.get(lang, f"Dôvody napíš v jazyku: {LANG_NAMES.get(lang, lang)}.")
                + f"\nKandidáti:\n{json.dumps(listing, ensure_ascii=False)}")
        try:
            result = self._call(system, user, schema, max_tokens=3000)
        except Exception as e:
            log.warning("AI rerank failed: %s", e)
            return None
        if not result:
            return None
        out = [(r["id"], r["reason"]) for r in result["results"]][:limit]
        self.cache.put(key, out)
        return out
