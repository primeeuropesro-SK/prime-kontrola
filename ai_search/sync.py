"""Download products from Upgates and build a compact search catalogue.

Usage:
    python3 -m ai_search.sync            # writes ai_search/data/catalog.json
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgates_client import UpgatesClient  # noqa: E402
from ai_search.search_engine import strip_html  # noqa: E402

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
    for v in variants:
        if v.get("active_yn") is False:
            continue
        variant_codes += [x for x in (v.get("code"), v.get("ean")) if x]
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
        in_stock = any((v.get("stock") or 0) > 0 or v.get("availability_type") == "InStock" for v in variants)
    else:
        in_stock = (stock or 0) > 0 or p.get("availability_type") == "InStock"
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
        "long_description": strip_html(d.get("long_description"))[:3000],
        "manufacturer": p.get("manufacturer") or "",
        "categories": [c["name"] for c in p.get("categories") or [] if c.get("name")],
        "variants": variant_labels,
        "price": price,
        "price_max": max(prices) if prices else price,
        "currency": currency,
        "in_stock": bool(in_stock),
        "availability": p.get("availability") or next((v.get("availability") for v in variants if v.get("availability")), None),
        "image": _image(p),
        "url": url,
    }


def build_catalog(client=None):
    client = client or UpgatesClient()
    langs = client.get("languages")["languages"]
    products = list(client.paginate("products"))
    catalog = {"generated_at": int(time.time()), "languages": {}}
    for lang in langs:
        code = lang["language_id"]
        docs = [x for x in (normalize_product(p, code, lang.get("domain", "")) for p in products) if x]
        catalog["languages"][code] = {"domain": lang.get("domain"), "currency": lang.get("currency_id"), "products": docs}
    return catalog


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
