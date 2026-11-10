"""Download products from Upgates and build a compact search catalogue.

Usage:
    python3 -m ai_search.sync            # writes ai_search/data/catalog.json
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgates_client import UpgatesClient, UpgatesError  # noqa: E402
from ai_search.search_engine import fold, strip_html  # noqa: E402

BLOG_NAMES = {"blog", "clanky", "clanok", "novinky z blogu", "magazin", "cikkek", "cikk", "magazin"}

DATA_DIR = os.environ.get("AI_SEARCH_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CATALOG_PATH = os.path.join(DATA_DIR, "catalog.json")
DEFAULT_PRICELIST = os.environ.get("AI_SEARCH_PRICELIST", "Predvolené")


def _desc(item, lang):
    for d in item.get("descriptions") or []:
        if d.get("language") == lang:
            return d
    return {}


def _price(item, lang):
    for p in item.get("prices") or []:
        if p.get("language") != lang:
            continue
        lists = p.get("pricelists") or []
        chosen = next((pl for pl in lists if pl.get("name") == DEFAULT_PRICELIST), lists[0] if lists else None)
        if not chosen:
            return None, p.get("currency")
        price = chosen.get("price_sale") or chosen.get("price_with_vat")
        return price, p.get("currency")
    return None, None


def _image(item):
    imgs = item.get("images") or []
    main = next((i for i in imgs if i.get("main_yn")), imgs[0] if imgs else None)
    return main.get("url") if main else None


def normalize_product(p, lang, domain=""):
    """Turn one Upgates product into a flat search document, or None if not sellable."""
    if not p.get("active_yn") or p.get("archived_yn") or p.get("exclude_from_search_yn"):
        return None
    d = _desc(p, lang)
    title = d.get("title")
    if not title:
        return None
    price, currency = _price(p, lang)
    variants = p.get("variants") or []
    variant_labels, variant_codes, prices = [], [], []
    variants = [v for v in variants if v.get("active_yn") is not False]  # inactive sizes do not count
    variant_info = {}  # variant code / EAN -> [availability, in stock, price] of that exact size
    for v in variants:
        v_in_stock = (v.get("stock") or 0) > 0 or v.get("availability_type") == "InStock"
        v_price, _ = _price(v, lang)
        for x in (v.get("code"), v.get("ean")):
            if x:
                variant_codes.append(x)
                variant_info[str(x)] = [v.get("availability"), v_in_stock, v_price]
        vd = _desc(v, lang)
        label = vd.get("title") or ""
        params = " ".join(
            str(pv.get("value") or "")
            for prm in v.get("parameters") or []
            for pv in (prm.get("values") or [prm])
            if pv.get("language", lang) == lang
        )
        variant_labels.append(f"{label} {params}".strip())
        vp, _ = _price(v, lang)
        if vp:
            prices.append(vp)
    if price is None and prices:
        price = min(prices)
    stock = p.get("stock")
    if variants:
        in_stock = any(info[1] for info in variant_info.values())
    else:
        in_stock = (stock or 0) > 0 or p.get("availability_type") == "InStock"
    # Availability text: from the product, else from a size that is in stock (not just the first size).
    availability = p.get("availability")
    if not availability and variants:
        stocked = [info[0] for info in variant_info.values() if info[1] and info[0]]
        any_text = [info[0] for info in variant_info.values() if info[0]]
        availability = (stocked or any_text or [None])[0]
    url = d.get("url") or ""
    if url and not url.startswith("http"):
        url = domain.rstrip("/") + "/" + url.lstrip("/")
    return {
        "id": p.get("product_id"),
        "code": p.get("code"),
        "ean": p.get("ean"),
        "variant_codes": variant_codes,
        "title": title,
        "short_description": strip_html(d.get("short_description")),
        # the whole description incl. FAQ (it used to be cut at 3000 chars, losing FAQs at the end)
        "long_description": strip_html(d.get("long_description"))[:15000],
        "manufacturer": p.get("manufacturer") or "",
        "categories": [c["name"] for c in p.get("categories") or [] if c.get("name")],
        "category_ids": [c["category_id"] for c in p.get("categories") or [] if c.get("category_id")],
        "variants": variant_labels,
        "price": price,
        "price_max": max(prices) if prices else price,
        "currency": currency,
        "in_stock": bool(in_stock),
        "availability": availability,
        "variant_info": variant_info,
        "image": _image(p),
        "url": url,
    }


# Keys never used by the search; dropping them while parsing keeps memory low
# (variant "metas" and the full price-list matrix are ~99 % of the API response).
_DROP_KEYS = {"metas", "stocks", "groups", "related_products", "parameters_groups"}


def _slim(pairs):
    """json object_pairs_hook: drop unused fields and keep only the shop's default price list."""
    obj = {}
    for k, v in pairs:
        if k in _DROP_KEYS:
            continue
        if k == "pricelists" and isinstance(v, list) and len(v) > 1:
            v = [next((pl for pl in v if pl.get("name") == DEFAULT_PRICELIST), v[0])]
        obj[k] = v
    return obj


def _load_categories(client, lang_codes):
    """Category / brand / info-page URLs per language. Needs the "Kategórie" read permission;
    without it the search still works, the suggestions just are not clickable links."""
    out = {code: {"categories": {}, "brands": {}, "pages": [], "category_names": {}} for code in lang_codes}
    try:
        cats = list(client.paginate("categories", object_pairs_hook=_slim))
    except UpgatesError as e:
        print(f"categories not loaded (missing API permission?): HTTP {e.status}", file=sys.stderr, flush=True)
        return out
    print(f"categories loaded: {len(cats)}", file=sys.stderr, flush=True)
    # Pages that are only menu folders (they have sub-pages), the blog and everything under it,
    # and articles are never offered in the search.
    parents = {c.get("parent_id") for c in cats if c.get("parent_id")}
    by_id = {c["category_id"]: c for c in cats}

    def is_blog(c, depth=0):
        if depth > 10 or c is None:
            return False
        names = {fold(d.get("name") or "").strip() for d in c.get("descriptions") or []}
        if "article" in (c.get("type") or "") or names & BLOG_NAMES:
            return True
        return is_blog(by_id.get(c.get("parent_id")), depth + 1)

    for c in cats:
        if not c.get("active_yn") or c.get("exclude_from_search_yn"):
            continue
        hidden_page = c.get("type") != "siteWithProducts" and (c["category_id"] in parents or is_blog(c))
        for d in c.get("descriptions") or []:
            lang, name, url = d.get("language"), (d.get("name") or "").strip(), d.get("url")
            if lang not in out or not name:
                continue
            out[lang]["category_names"][str(c["category_id"])] = name
            if not url:
                continue
            if c.get("manufacturer"):
                out[lang]["brands"][c["manufacturer"]] = url
            if c.get("type") == "siteWithProducts":
                out[lang]["categories"][str(c["category_id"])] = {"name": name, "url": url}
            elif c.get("type") in ("site", "contact") and not hidden_page:
                out[lang]["pages"].append({"title": name, "url": url})
    return out


def build_catalog(client=None):
    """Stream products page by page so a 500 MB+ API response never sits in memory at once."""
    client = client or UpgatesClient()
    langs = client.get("languages")["languages"]
    catalog = {"generated_at": int(time.time()), "languages": {
        l["language_id"]: {"domain": l.get("domain"), "currency": l.get("currency_id"), "products": []}
        for l in langs
    }}
    for code, extra in _load_categories(client, list(catalog["languages"])).items():
        catalog["languages"][code].update(extra)
    for p in client.paginate("products", object_pairs_hook=_slim):
        for code, lang in catalog["languages"].items():
            doc = normalize_product(p, code, lang["domain"] or "")
            if doc:
                lang["products"].append(doc)
    default_lang = langs[0]["language_id"] if langs else None
    for code, lang in catalog["languages"].items():
        localize_categories(lang, keep_untranslated=(code == default_lang))
    return catalog


def localize_categories(lang, keep_untranslated):
    """Upgates returns product category names only in the shop's main language. Replace them
    with this language's names from the categories API. Without those (no "Kategórie" API
    permission) other languages get no category names rather than Slovak ones."""
    names = lang.get("category_names") or {}
    for doc in lang["products"]:
        ids = [str(i) for i in doc.get("category_ids", [])]
        localized = []
        for cid, original in zip(ids, doc.get("categories", [])):
            if cid in names:
                localized.append(names[cid])
            elif keep_untranslated:
                localized.append(original)
        doc["categories"] = localized
        doc["category_ids"] = [cid for cid in ids if cid in names or keep_untranslated]


def save_catalog(catalog, path=CATALOG_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_catalog(path=CATALOG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    t = time.time()
    catalog = build_catalog()
    save_catalog(catalog)
    for code, lang in catalog["languages"].items():
        print(f"{code}: {len(lang['products'])} products")
    print(f"Saved {CATALOG_PATH} in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
