"""Offline tests for the AI search (no network, Claude is replaced by a fake client).

Run: python3 -m unittest discover -s tests
"""
import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_search import ai as ai_mod  # noqa: E402
from ai_search.search_engine import SearchIndex, edit_distance, fold, stem, tokenize  # noqa: E402
from ai_search.sync import normalize_product  # noqa: E402


def product(pid, title, cats, price, stock=10, manufacturer="Prime", short="", active=True):
    return {
        "product_id": pid, "code": f"C{pid}", "ean": f"590{pid:010d}", "active_yn": active, "archived_yn": False,
        "exclude_from_search_yn": False, "manufacturer": manufacturer, "stock": stock,
        "availability": "Skladom", "availability_type": "InStock" if stock else "OutOfStock",
        "descriptions": [{"language": "sk", "title": title, "short_description": f"<p>{short}</p>",
                          "long_description": "", "url": f"https://www.primework.sk/p/{pid}"}],
        "prices": [{"language": "sk", "currency": "EUR",
                    "pricelists": [{"name": "Predvolené", "price_with_vat": price, "price_sale": None}]}],
        "categories": [{"name": c} for c in cats], "images": [{"url": f"https://cdn/{pid}.webp", "main_yn": True}],
        "variants": [],
    }


RAW = [
    product(1, "Zimné pracovné rukavice zateplené", ["Zimné rukavice"], 6.5, short="Teplé rukavice na prácu vonku"),
    product(2, "Pracovné rukavice z lícovej kože", ["Kožené Rukavice"], 3.1),
    product(3, "Bakanče so špicou S3", ["Bakanče so špicou"], 45.0, manufacturer="Urgent"),
    product(4, "Pracovná poltopánka S1P", ["Poltopánky so špicou"], 29.9, manufacturer="Reis"),
    product(5, "Reflexná vesta žltá", ["Reflexné oblečenie"], 2.3, stock=0),
    product(6, "Neaktívny produkt", ["Zimné rukavice"], 1.0, active=False),
]


class FakeAnthropic:
    """Mimics client.beta.messages.create and returns canned JSON."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.messages = types.SimpleNamespace(create=self._create)
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        text = json.dumps(self.replies.pop(0), ensure_ascii=False)
        return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=text)])


class TextTests(unittest.TestCase):
    def test_fold_and_tokenize(self):
        self.assertEqual(fold("Pracovné Rukavice ŽLTÉ"), "pracovne rukavice zlte")
        self.assertEqual(tokenize("hľadám rukavice na zimu"), ["rukavice", "zimu"])
        self.assertTrue("rukaviciach".startswith(stem("rukavice")))


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = [d for d in (normalize_product(p, "sk") for p in RAW) if d]
        cls.idx = SearchIndex(cls.docs)

    def test_inactive_products_are_skipped(self):
        self.assertEqual(len(self.docs), 5)

    def test_inflection_and_diacritics(self):
        _, res = self.idx.search("rukavic zateplenych")
        self.assertEqual(res[0]["id"], 1)

    def test_exact_code(self):
        total, res = self.idx.search("C3")
        self.assertEqual((total, res[0]["id"]), (1, 3))

    def test_filters(self):
        _, res = self.idx.search("rukavice", filters={"max_price": 5})
        self.assertEqual([d["id"] for d in res], [2])
        _, res = self.idx.search("vesta", filters={"in_stock_only": True})
        self.assertEqual(res, [])

    def test_extra_terms_from_ai(self):
        # "topánky s oceľovou špičkou" alone does not match well; AI adds catalogue words.
        _, res = self.idx.search("topánky s oceľovou špičkou", extra_terms=["bakanče", "poltopánka", "S3", "S1P"])
        self.assertEqual({d["id"] for d in res[:2]}, {3, 4})


class TypoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = RAW + [
            product(7, "Procera Ragnar S3 - Pracovná členková obuv", ["Obuv"], 59.0, manufacturer="Procera"),
            product(8, "Pracovná mikina fleece", ["Mikiny"], 19.0),
        ]
        cls.idx = SearchIndex([d for d in (normalize_product(p, "sk") for p in raw) if d])

    def first(self, q):
        _, res = self.idx.search(q)
        return res[0]["id"] if res else None

    def test_digits_instead_of_letters(self):
        self.assertEqual(self.first("pr0cera"), 7)
        self.assertEqual(self.idx.corrections("pr0cera"), {"pr0cera": "procera"})

    def test_swapped_missing_and_doubled_letters(self):
        for q in ("porcera", "prcera", "procerra", "proceras"):
            self.assertEqual(self.first(q), 7, q)

    def test_y_i_grammar_errors(self):
        self.assertEqual(self.first("mykina"), 8)
        self.assertEqual(self.first("zymne rukavyce"), 1)

    def test_wrong_letter(self):
        self.assertEqual(self.first("rukavuce zateplene"), 1)

    def test_correct_words_are_not_corrected(self):
        self.assertEqual(self.idx.corrections("pracovná mikina"), {})
        self.assertEqual(self.idx.corrections("mik"), {})  # unfinished word while typing

    def test_short_words_need_exact_prefix(self):
        self.assertEqual(edit_distance("porcera", "procera"), 1)
        self.assertIsNone(self.first("xyz"))


class AITests(unittest.TestCase):
    def test_understand_and_rerank(self):
        docs = [d for d in (normalize_product(p, "sk") for p in RAW) if d]
        idx = SearchIndex(docs)
        fake = FakeAnthropic([
            {"keywords": ["bakanče", "poltopánka", "špica"], "categories": ["Bakanče so špicou"], "manufacturers": [],
             "min_price": None, "max_price": 40, "in_stock_only": False, "summary": "Hľadám obuv so špicou do 40 €."},
            {"results": [{"id": 4, "reason": "Poltopánka so špicou S1P do 40 €"}]},
        ])
        q = ai_mod.QueryAI(client=fake)
        info = q.understand("topánky s oceľovou špičkou do 40 €", "sk", idx)
        self.assertEqual(info["max_price"], 40)
        schema = fake.calls[0]["output_config"]["format"]["schema"]
        self.assertIn("Bakanče so špicou", schema["properties"]["categories"]["items"]["enum"])
        # Default model is the cheap Haiku, which has no server-side fallback parameter.
        self.assertEqual(fake.calls[0]["model"], "claude-haiku-5-5")
        self.assertNotIn("fallbacks", fake.calls[0])

        _, cands = idx.search("topánky", filters={"max_price": 40}, extra_terms=info["keywords"])
        ranked = q.rerank("topánky s oceľovou špičkou do 40 €", "sk", cands, 5)
        self.assertEqual(ranked, [(4, "Poltopánka so špicou S1P do 40 €")])

        # Second identical query is served from cache (no new API call).
        q.understand("topánky s oceľovou špičkou do 40 €", "sk", idx)
        self.assertEqual(len(fake.calls), 2)

    def test_ai_failure_is_swallowed(self):
        class Broken(FakeAnthropic):
            def _create(self, **kw):
                raise RuntimeError("network down")
        q = ai_mod.QueryAI(client=Broken([]))
        self.assertIsNone(q.understand("rukavice", "sk", SearchIndex([])))


if __name__ == "__main__":
    unittest.main()
