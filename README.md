# prime-kontrola

Nástroje na kontrolu e-shopu **prime-work** cez Upgates API v2.

## Súbory

- `upgates_client.py` – jednoduchý klient (len štandardná knižnica Pythonu), metódy `get()` a `paginate()`.
- `test_upgates_api.py` – smoke test, ktorý overí dostupnosť hlavných endpointov (iba GET).

## Konfigurácia

| Premenná | Popis |
|---|---|
| `UPGATES_BASE_URL` | predvolene `https://prime-work.admin.s35.upgates.com/api/v2` |
| `UPGATES_LOGIN` | API login (nepovinné, ak autentifikáciu dopĺňa proxy) |
| `UPGATES_API_KEY` | API kľúč (nepovinné, ak autentifikáciu dopĺňa proxy) |

## Spustenie

```bash
python3 test_upgates_api.py
```

## Poznámky k API

- Stránkuje sa iba parametrom `page`; parameter `limit` vráti HTTP 400.
- Veľkosť stránky je pevná: produkty 50, objednávky/zákazníci/kategórie 100.
- Nepoužívajte `api.upgates.com` – presmeruje inam a v hlavičke `Location` vráti prihlasovacie údaje. Klient preto presmerovania nenasleduje.

## Príklad

```python
from upgates_client import UpgatesClient

client = UpgatesClient()
for product in client.paginate("products", max_pages=1):
    print(product["code"])
```
