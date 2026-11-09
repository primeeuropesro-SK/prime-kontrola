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


class AutocompleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = RAW + [
            product(7, "Procera Silus Winter KRT - Zimná pracovná bunda", ["Bundy"], 59.0, manufacturer="Procera"),
            product(8, "Procera Luma Winter KRT - Zimná pracovná bunda", ["Bundy"], 49.0, manufacturer="Procera"),
            product(9, "Procera Valor KRT - Softshellová pracovná bunda", ["Bundy"], 39.0, manufacturer="Procera"),
        ]
        docs = [d for d in (normalize_product(p, "sk") for p in raw) if d]
        for d in docs:
            d["category_ids"] = [1 if c == "Bundy" else 2 for c in d["categories"]]
        extras = {"categories": {"1": {"name": "Bundy", "url": "https://shop/bundy"}},
                  "pages": [{"title": "Záruka, reklamácie", "url": "https://shop/reklamacie"}]}
        cls.idx = SearchIndex(docs, extras)

    def test_completes_brand_and_phrase(self):
        self.assertEqual(self.idx.suggest_queries("proc")[0], "procera")
        self.assertIn("procera zimná pracovná bunda", self.idx.suggest_queries("procera z"))

    def test_completion_tolerates_typos(self):
        self.assertIn("procera zimná pracovná bunda", self.idx.suggest_queries("procere zimne"))

    def test_category_and_page_links(self):
        self.assertEqual(self.idx.suggest_categories("bunda")[0], {"name": "Bundy", "url": "https://shop/bundy"})
        self.assertEqual(self.idx.suggest_pages("reklamacia")[0]["url"], "https://shop/reklamacie")

    def test_brand_suggestion(self):
        self.assertEqual(self.idx.suggest_brands("proc")[0]["name"], "Procera")


class PopularTests(unittest.TestCase):
    def test_needs_real_words_and_several_visitors(self):
        import tempfile
        from ai_search import server
        idx = SearchIndex([d for d in (normalize_product(p, "sk") for p in RAW) if d])
        pop = server.Popular(os.path.join(tempfile.mkdtemp(), "popular.json"))
        for ip in ("1.1.1.1", "2.2.2.2"):
            pop.record("sk", "Reflexná vesta", ip, idx)
        self.assertEqual(pop.top("sk"), [])  # only 2 visitors so far
        pop.record("sk", "reflexná vesta", "3.3.3.3", idx)
        pop.record("sk", "reflexná vesta", "3.3.3.3", idx)  # same visitor again does not count
        self.assertEqual(pop.top("sk"), ["reflexná vesta"])
        for ip in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
            pop.record("sk", "kúpte si lacné xyz", ip, idx)  # not catalogue words -> never shown
        self.assertEqual(pop.top("sk"), ["reflexná vesta"])


class SynonymTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = RAW + [
            product(10, "Multi Master Red - Overal na traky", ["Overaly"], 49.0),
            product(11, "EM5002B - Mušlový chránič sluchu", ["Chrániče sluchu"], 10.3),
            product(12, "Kariban 466 - Pracovná mikina", ["Mikiny"], 25.0, short="otvor na slúchadlá"),
        ]
        cls.idx = SearchIndex([d for d in (normalize_product(p, "sk") for p in raw) if d])
        cls.idx.set_synonyms({"kombinezón": ["overal"], "slúchadlá": ["chránič sluchu"], "sveter": ["mikina"]})

    def first(self, q):
        _, res = self.idx.search(q)
        return res[0]["id"] if res else None

    def test_word_missing_in_catalogue(self):
        self.assertEqual(self.first("kombinezón"), 10)
        self.assertEqual(self.first("kombinezonu"), 10)  # inflected, no diacritics

    def test_synonym_beats_incidental_mention(self):
        self.assertEqual(self.first("slúchadlá"), 11)  # not the hoodie that mentions headphones

    def test_synonym_offered_as_suggestion(self):
        self.assertEqual(self.idx.suggest_queries("kombinezón")[0], "overal")

    def test_no_false_trigger(self):
        self.assertEqual(self.idx.synonym_hits("svetlo")[1], [])

    def test_manual_file_overrides_auto(self):
        import tempfile
        from ai_search import synonyms
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "synonyms_sk.json"), "w", encoding="utf-8") as f:
            json.dump({"items": [{"customer": "sveter", "catalog": "tričko"}, {"customer": "gumáky", "catalog": "čižmy"}]}, f)
        manual = os.path.join(d, "manual.json")
        with open(manual, "w", encoding="utf-8") as f:
            json.dump({"sk": {"sveter": ["mikina"]}}, f)
        orig = synonyms.MANUAL_PATH
        synonyms.MANUAL_PATH = manual
        try:
            m = synonyms.merged(d, "sk")
        finally:
            synonyms.MANUAL_PATH = orig
        self.assertEqual(m, {"sveter": ["mikina"], "gumáky": ["čižmy"]})

    def test_auto_generation_is_cached(self):
        import tempfile
        from ai_search import synonyms

        class FakeAI:
            enabled, calls = True, 0

            def synonyms(self, lang, phrases):
                FakeAI.calls += 1
                return [{"customer": "kombinezón", "catalog": phrases[0]}]

        d = tempfile.mkdtemp()
        self.assertTrue(synonyms.ensure_auto(d, "sk", self.idx, FakeAI()))
        self.assertFalse(synonyms.ensure_auto(d, "sk", self.idx, FakeAI()))  # unchanged catalogue -> no new call
        self.assertEqual(FakeAI.calls, 1)


class AnalyticsTests(unittest.TestCase):
    def events(self):
        e = lambda t, typ, q, n=5, sid="a", pid=None, lang="sk": dict(t=t, type=typ, q=q, n=n, sid=sid, lang=lang, **({"pid": pid} if pid else {}))
        return [
            e(0, "search", "proc"), e(2, "search", "procera"), e(3, "suggestion", "procera zimná bunda"),
            e(5, "click", "procera zimná bunda", pid=7),                       # 1 successful search
            e(60, "search", "kombinezon", n=0),                                 # 1 not found
            e(0, "search", "kombinezon", n=0, sid="b"),                         # same word, other visitor
            e(9, "ai", "topánky so špicou do 40 €", sid="b"), e(12, "click", "topánky so špicou do 40 €", sid="b", pid=8),
            e(20, "search", "vesta", sid="c"),                                  # results, no click
            e(1, "search", "kesztyű", lang="hu", sid="d"), e(4, "click", "kesztyű", lang="hu", sid="d", pid=7),
        ]

    def test_grouping_and_summary(self):
        from ai_search import analytics
        searches = analytics.group_searches(self.events())
        rep = analytics.summarize(searches, {"sk": {7: ("Procera Silus", "https://shop/p/7")}})
        sk = rep["sk"]
        self.assertEqual(sk["searches"], 5)  # proc→procera→suggestion→click is one search
        self.assertEqual(sk["successful"], 2)
        self.assertEqual(sk["success_rate"], 40.0)
        self.assertEqual([(x["q"], x["count"], x["first"], x["last"]) for x in sk["not_found"]], [("kombinezon", 2, 0, 60)])
        self.assertEqual([x["t"] for x in sk["not_found_events"]], [60, 0])  # each search with its time, newest first
        self.assertEqual(sk["no_click_queries"][0]["q"], "vesta")
        self.assertEqual((sk["ai_searches"], sk["ai_success_rate"]), (1, 100.0))
        self.assertEqual(sk["top_products"][0]["title"], "Procera Silus")
        self.assertEqual(rep["hu"]["searches"], 1)

    def test_report_files_and_html(self):
        import tempfile
        from datetime import timedelta
        from ai_search import analytics
        log = analytics.EventLog(tempfile.mkdtemp())
        for ev in self.events():
            log.append(ev)
        today = analytics.now_local().date()
        week = analytics.iso_week(today)
        rep = analytics.build_report(log, {}, week)
        self.assertGreater(rep["langs"]["sk"]["searches"], 0)
        page = analytics.render_html(rep, {"sk": "https://www.primework.sk"})
        self.assertIn("Top 20 produktov", page)
        csv_text = analytics.not_found_csv(rep)
        self.assertIn("kombinezon", csv_text)
        self.assertRegex(csv_text, r"Slovensko;\d\d\.\d\d\.\d{4};\d\d:\d\d;kombinezon")
        self.assertIn("Naposledy hľadané", page)
        self.assertIn("Top 20 hľadaných výrazov", page)
        self.assertGreater(rep["langs"]["sk"]["top_queries"][0]["last"], 0)
        all_csv = analytics.searches_csv(rep)
        self.assertRegex(all_csv, r"Slovensko;\d\d\.\d\d\.\d{4};\d\d:\d\d;kombinezon;nenašli;")
        self.assertIn(";klik na produkt;", all_csv)
        self.assertEqual(analytics.week_range(week)[0], today - timedelta(days=today.weekday()))


class DemandTests(unittest.TestCase):
    def test_groups_missing_products_and_caches(self):
        import tempfile
        from ai_search import analytics

        class FakeAI:
            enabled, calls = True, 0

            def product_demand(self, lang, queries, phrases):
                FakeAI.calls += 1
                return [
                    {"product": "Zváračská kukla", "queries": ["zvaracska kukla", "kukla na zvaranie"], "status": "missing",
                     "catalog_phrase": "", "note": "Samostmievacia kukla, norma EN 175."},
                    {"product": "Overal", "queries": ["kombinezon"], "status": "synonym", "catalog_phrase": "overal", "note": ""},
                    {"product": "?", "queries": ["xyzzy"], "status": "unclear", "catalog_phrase": "", "note": ""},
                ]

        report = {"week": "2026-W46", "langs": {"sk": {
            "not_found": [{"q": "zvaracska kukla", "count": 3}, {"q": "kukla na zvaranie", "count": 2},
                          {"q": "kombinezon", "count": 4}, {"q": "xyzzy", "count": 1}],
            "no_click_queries": []}}, "prev": {}}
        d = tempfile.mkdtemp()
        analytics.add_demand(report, FakeAI(), d, {"sk": ["overal"]})
        dem = report["langs"]["sk"]["demand"]
        self.assertEqual((dem[0]["product"], dem[0]["count"], dem[0]["status"]), ("Zváračská kukla", 5, "missing"))
        self.assertEqual(dem[1]["status"], "synonym")
        analytics.add_demand(report, FakeAI(), d, {"sk": ["overal"]})  # same data -> cached, no new AI call
        self.assertEqual(FakeAI.calls, 1)
        csv_text = analytics.demand_csv(report)
        self.assertIn("Zváračská kukla;chýba v sortimente;5;", csv_text)

    def test_without_ai_report_still_works(self):
        import tempfile
        from ai_search import analytics
        report = {"week": "2026-W46", "langs": {"sk": {"not_found": [{"q": "kukla", "count": 1}], "no_click_queries": []}}, "prev": {}}
        analytics.add_demand(report, None, tempfile.mkdtemp(), {})
        self.assertEqual(report["langs"]["sk"]["demand"], [])


class VariantStockTests(unittest.TestCase):
    def product(self):
        p = product(20, "Urgent 229 S1 - Pracovná športová poltopánka", ["Obuv"], 22.19, manufacturer="Urgent")
        p.update(stock=None, availability=None, availability_type=None)
        def v(code, ean, stock, avail, typ, active):
            return {"code": code, "ean": ean, "stock": stock, "availability": avail, "availability_type": typ,
                    "active_yn": active, "prices": p["prices"], "descriptions": None}
        p["variants"] = [v("109673", "5902365222446", 0, "Nie je na sklade", "NotAvailable", False),
                         v("109675", "5902365222460", 1000000, "2-5 pracovné dni", "InStock", True),
                         v("109676", "5902365222477", 0, "Na objednávku", "OnOrder", True)]
        return p

    def test_inactive_first_size_does_not_decide_availability(self):
        d = normalize_product(self.product(), "sk")
        self.assertTrue(d["in_stock"])
        self.assertEqual(d["availability"], "2-5 pracovné dni")

    def test_variant_code_and_ean_show_that_size(self):
        idx = SearchIndex([normalize_product(self.product(), "sk")])
        for q in ("5902365222460", "109675"):
            _, res = idx.search(q)
            self.assertEqual((res[0]["in_stock"], res[0]["availability"]), (True, "2-5 pracovné dni"))
        _, res = idx.search("109676")
        self.assertEqual((res[0]["in_stock"], res[0]["availability"]), (False, "Na objednávku"))
        self.assertEqual(idx.search("5902365222446")[0], 0)  # inactive size is not offered


class LocalizeTests(unittest.TestCase):
    def test_hungarian_shop_gets_hungarian_category_names(self):
        from ai_search.sync import localize_categories
        doc = {"categories": ["Oblečenie", "Bundy"], "category_ids": [1, 2]}
        hu = {"products": [dict(doc)], "category_names": {"1": "Ruházat", "2": "Kabátok"}}
        localize_categories(hu, keep_untranslated=False)
        self.assertEqual(hu["products"][0]["categories"], ["Ruházat", "Kabátok"])

    def test_without_permission_no_slovak_names_in_hungarian_shop(self):
        from ai_search.sync import localize_categories
        doc = {"categories": ["Oblečenie"], "category_ids": [1]}
        hu, sk = {"products": [dict(doc)]}, {"products": [dict(doc)]}
        localize_categories(hu, keep_untranslated=False)
        localize_categories(sk, keep_untranslated=True)
        self.assertEqual(hu["products"][0]["categories"], [])
        self.assertEqual(sk["products"][0]["categories"], ["Oblečenie"])


class RulesTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from ai_search.rules import Rules
        self.rules = Rules(os.path.join(tempfile.mkdtemp(), "rules.json"))
        self.docs = [d for d in (normalize_product(p, "sk") for p in RAW) if d]
        self.by_id = {d["id"]: d for d in self.docs}

    def test_pin_and_hide_apply_to_queries_containing_all_words(self):
        self.rules.add_pin("sk", "zimné rukavice", 2)
        self.rules.add_hide("sk", "rukavice", 1)
        docs, pinned = self.rules.apply("sk", "zimne rukavice do 10 €", list(self.docs), self.by_id)
        self.assertEqual(docs[0]["id"], 2)
        self.assertNotIn(1, [d["id"] for d in docs])
        self.assertEqual(pinned, {2})
        docs, _ = self.rules.apply("sk", "vesta", list(self.docs), self.by_id)  # other query: untouched
        self.assertEqual([d["id"] for d in docs], [d["id"] for d in self.docs])
        docs, _ = self.rules.apply("hu", "zimne rukavice", list(self.docs), self.by_id)  # other language
        self.assertEqual(docs[0]["id"], self.docs[0]["id"])

    def test_instructions_ratings_persist_and_delete(self):
        from ai_search.rules import Rules
        r = self.rules.add_instruction("sk", "  Pri slove zimné uprednostni zateplené.  ")
        self.rules.rate("abc", "bad", "ukázalo letné")
        again = Rules(self.rules.path)
        self.assertEqual(again.instructions("sk"), ["Pri slove zimné uprednostni zateplené."])
        self.assertEqual(again.rating("abc")["note"], "ukázalo letné")
        v1 = again.version("sk")
        again.remove(r["id"])
        self.assertEqual(again.instructions("sk"), [])
        self.assertNotEqual(again.version("sk"), v1)

    def test_owner_instruction_reaches_the_ai(self):
        docs = [d for d in (normalize_product(p, "sk") for p in RAW) if d]
        fake = FakeAnthropic([{"keywords": ["rukavice"], "categories": [], "manufacturers": [], "min_price": None,
                               "max_price": None, "in_stock_only": False, "summary": "x"}] * 2)
        q = ai_mod.QueryAI(client=fake)
        q.understand("rukavice", "sk", SearchIndex(docs), instructions=("Uprednostni zateplené.",))
        self.assertIn("Uprednostni zateplené.", fake.calls[0]["system"][0]["text"])
        q.understand("rukavice", "sk", SearchIndex(docs), instructions=("Iný pokyn.",))  # new rule -> no stale cache
        self.assertEqual(len(fake.calls), 2)


class AdminPagesTests(unittest.TestCase):
    def test_answers_joined_with_clicks_feedback_and_rating(self):
        import tempfile
        from ai_search import admin_pages, analytics
        from ai_search.rules import Rules, answer_key
        log = analytics.EventLog(tempfile.mkdtemp())
        rules = Rules(os.path.join(tempfile.mkdtemp(), "rules.json"))
        log.append({"type": "ai_result", "lang": "sk", "q": "Topánky do 40 €", "sid": "s1", "ok": True,
                    "summary": "Hľadám obuv", "keywords": ["poltopánka"], "filters": {"max_price": 40},
                    "products": [[4, "S1P do 40 €"], [3, "S3"]], "pinned": []})
        log.append({"type": "click", "lang": "sk", "q": "topánky do 40 €", "sid": "s1", "pid": 4})
        log.append({"type": "ai_feedback", "lang": "sk", "q": "topánky do 40 €", "sid": "s1", "v": "up"})
        today = analytics.now_local().date()
        answers = admin_pages.ai_answers(log, today, today, rules)
        self.assertEqual((answers[0]["clicked"], answers[0]["customer"]), ({4}, "up"))
        rules.rate(answers[0]["key"], "good")
        answers = admin_pages.ai_answers(log, today, today, rules)
        self.assertEqual(answers[0]["owner"]["rating"], "good")
        page = admin_pages.render_ai_page(answers, analytics.iso_week(today), {"sk": {4: ("Reis S1P", "https://shop/p/4")}}, "tok", "all")
        self.assertIn("Reis S1P", page)
        self.assertIn("Pripnúť", page)
        self.assertIn("👍 zákazníkovi pomohlo", page)
        self.assertIn("Pravidlá a pokyny", admin_pages.render_rules_page(rules, {}, "tok", ["sk"]))
        self.assertEqual(answer_key(answers[0]), answers[0]["key"])


class TokenTests(unittest.TestCase):
    def test_plus_in_token_survives_url(self):
        from urllib.parse import parse_qs
        from ai_search import server
        orig = server.ADMIN_TOKEN
        server.ADMIN_TOKEN = "lWZa+T3kb/49="
        try:
            typed = parse_qs("token=lWZa+T3kb/49=")["token"][0]  # what the server receives: "lWZa T3kb/49="
            self.assertTrue(server._token_ok(typed))
            self.assertFalse(server._token_ok("wrong"))
            self.assertFalse(server._token_ok(""))
        finally:
            server.ADMIN_TOKEN = orig


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
