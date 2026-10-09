"""Smoke test for the Upgates API (read-only GET requests).

Usage: python3 test_upgates_api.py
Exit code 0 = all checks passed, 1 = at least one failed.
"""
import sys

from upgates_client import UpgatesClient, UpgatesError

PAGED_ENDPOINTS = ["products", "orders", "customers", "categories"]


def main():
    client = UpgatesClient()
    print(f"Base URL: {client.base_url}\n")
    failed = 0

    try:
        langs = client.get("languages")["languages"]
        assert langs, "no languages returned"
        desc = ", ".join(f"{l['language_id']} ({l['currency_id']}, {l['domain']})" for l in langs)
        print(f"OK    languages   {len(langs)}: {desc}")
    except (UpgatesError, AssertionError, KeyError) as e:
        failed += 1
        print(f"FAIL  languages   {e}")

    for ep in PAGED_ENDPOINTS:
        try:
            data = client.get(ep, page=1)
            items = data[ep]
            assert data["number_of_items"] >= len(items), "inconsistent counts"
            print(f"OK    {ep:<11} {data['number_of_items']} items, "
                  f"{data['number_of_pages']} pages ({data['current_page_items']} on page 1)")
        except (UpgatesError, AssertionError, KeyError) as e:
            failed += 1
            print(f"FAIL  {ep:<11} {e}")

    # `limit` is not supported by Upgates; expect a 400.
    try:
        client.get("products", limit=1)
        failed += 1
        print("FAIL  limit-param  expected HTTP 400, got 200")
    except UpgatesError as e:
        ok = e.status == 400
        failed += not ok
        print(f"{'OK  ' if ok else 'FAIL'}  limit-param  rejected with HTTP {e.status} as expected")

    print(f"\n{'All checks passed' if not failed else f'{failed} check(s) failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
