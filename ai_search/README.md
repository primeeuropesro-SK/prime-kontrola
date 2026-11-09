# Prime AI Search – AI vyhľadávanie produktov pre Upgates

Vlastná alternatíva k službám typu Magrano pre e-shopy **primework.sk** (SK) a **munkaruhazatolcson.hu** (HU).

Zákazník nemusí poznať presný názov produktu. Stačí, keď napíše, čo potrebuje, napr.
„topánky s oceľovou špičkou do 40 €“, „niečo reflexné pre cestárov“ alebo „zimné rukavice na prácu vonku“.

## Ako to funguje

```
Upgates API ──(každú hodinu)──▶ sync.py ──▶ katalóg v pamäti (BM25 index, SK + HU)
                                                   ▲
e-shop (widget.js) ──▶ /api/search ────────────────┤
                         │  ai=0: okamžité výsledky počas písania (~1–15 ms, bez AI)
                         └─ ai=1: Claude pochopí dopyt (synonymá, kategórie, cena, sklad)
                                 → vyhľadanie v katalógu → Claude zoradí výsledky a ku každému napíše dôvod
```

- **Počas písania** sa výsledky ukazujú okamžite (fulltext, ignoruje diakritiku, rozumie skloňovaniu:
  rukavice / rukavíc / rukaviciach, presná zhoda kódu produktu alebo EAN).
- **Preklepy a gramatické chyby** sa opravujú už v okamžitom vyhľadávaní, bez AI a zadarmo:
  číslice namiesto písmen (`pr0cera`), prehodené, chýbajúce alebo zdvojené písmená (`porcera`, `prcera`,
  `procerra`), i/y (`mykina`, `rukavyce`, `zymna`) a zlé písmeno (`rukavuce`). Krátke slová (do 3 znakov)
  musia sedieť presne, slová so 4–5 znakmi znesú 1 chybu, dlhšie 2. Widget ukáže
  „Zobrazujem výsledky pre: procera zimná bunda“.
- **Našepkávač** (ako Luigi's Box): počas písania dokončuje hľadané výrazy z katalógu
  („proc“ → „procera“, „procera z“ → „procera **zimná pracovná bunda**“, Tab výraz doplní), ponúka
  kategórie (odkazy na e-shop; značky a informačné stránky sa dajú zapnúť premennými `SHOW_BRANDS=1`
  a `SHOW_PAGES=1`, blog a články sa nezobrazujú nikdy) a vpravo produkty so zvýraznenou zhodou.
  Po kliknutí do prázdneho poľa ukáže populárne vyhľadávania a obľúbené kategórie. Populárne sa
  zobrazia až keď výraz hľadali aspoň 3 rôzni návštevníci a obsahuje iba slová z katalógu.
  Odkazy na kategórie potrebujú v Upgates API právo **Kategórie → Iba čítanie**.
- **Mobil:** po ťuknutí do vyhľadávania sa otvorí vyhľadávanie cez celú obrazovku (pole hore, ✕ vpravo).
  Tlačidlo Späť na telefóne ho zavrie a zákazník ostane na tej istej stránke. Najviac 4 návrhy,
  kategórie a značky v jednom vodorovnom páse, hneď pod nimi produkty. Pri posúvaní výsledkov sa
  skryje klávesnica. Nezávisí od toho, kde má šablóna Upgates vyhľadávacie pole.
- **Synonymá** po slovensky aj po maďarsky: automaticky (Claude Haiku, raz týždenne) aj vlastné
  v `synonyms.json` – „kombinezón“ nájde overaly, „slúchadlá“ chrániče sluchu, „fejhallgató“ hallásvédő.
- **Týždenný report** na `/report?token=…` (voliteľne e-mailom každý pondelok): úspešnosť, top 20
  produktov a hľadaných výrazov podľa krajiny, výrazy, ktoré zákazníci hľadali a nenašli. Pozri NASADENIE.md.
- **Enter alebo tlačidlo „✨ Opýtať sa AI“** spustí AI vyhľadávanie: Claude premení voľný text na kľúčové slová
  v jazyku katalógu, vyberie kategórie, cenový rozsah a potom zoradí najlepších kandidátov.
- Ak AI nie je dostupná (chýba kľúč, výpadok), vyhľadávanie funguje ďalej bez nej.
- AI výsledky sa ukladajú do cache (rovnaký dopyt = žiadne ďalšie volanie), počet AI dopytov je obmedzený na IP adresu.

## Súbory

| Súbor | Popis |
|---|---|
| `sync.py` | stiahne produkty z Upgates a pripraví katalóg (`data/catalog.json`) |
| `search_engine.py` | rýchly fulltextový index (BM25), filtre ceny, skladu, kategórie a výrobcu |
| `ai.py` | Claude: pochopenie dopytu + zoradenie výsledkov (structured outputs) |
| `server.py` | HTTP API, hosťuje `widget.js` a testovaciu stránku `/demo` |
| `static/widget.js` | skript, ktorý sa vloží do e-shopu a napojí sa na existujúce vyhľadávacie pole |

## Spustenie lokálne

```bash
pip install -r requirements.txt
```

```bash
export UPGATES_LOGIN=... UPGATES_API_KEY=... ANTHROPIC_API_KEY=...
```

```bash
python3 -m ai_search.sync
```

```bash
python3 -m ai_search.server
```

Potom otvorte `http://localhost:8080/demo`.

Testy (bez siete, Claude je nahradený simuláciou):

```bash
python3 -m unittest discover -s tests
```

## Nasadenie na server

Upgates je hostovaná platforma – vlastný backend na nej spustiť nejde. Server preto beží zvlášť
(akýkoľvek VPS, Render, Railway, Fly.io, Hetzner…) a do e-shopu sa vloží iba skript.

```bash
docker build -t prime-ai-search .
```

```bash
docker run -d --name prime-ai-search -p 8080:8080 --env-file .env -v prime-ai-data:/data prime-ai-search
```

Server musí byť dostupný cez **HTTPS** (napr. `https://search.primework.sk`), inak ho prehliadač
na stránke e-shopu zablokuje. Najjednoduchšie je dať pred neho Caddy alebo použiť hosting, ktorý HTTPS rieši sám.

Premenné prostredia sú v `.env.example`.

| Premenná | Význam |
|---|---|
| `ANTHROPIC_API_KEY` | kľúč pre Claude API; bez neho beží iba fulltext |
| `AI_MODEL` | predvolene `claude-haiku-5-5` (najlacnejší a najrýchlejší); pre vyššiu kvalitu `claude-sonnet-5-5` |
| `AI_EFFORT` | `low` (rýchle), `medium`, `high` |
| `AI_RERANK` | `1` = Claude zoradí výsledky a napíše dôvod, `0` = iba pochopenie dopytu (rýchlejšie, lacnejšie) |
| `AI_RATE_PER_MIN` | max. AI dopytov za minútu z jednej IP |
| `SYNC_INTERVAL_MIN` | ako často sa načítajú produkty z Upgates (0 = vypnuté) |
| `ALLOWED_ORIGINS` | domény e-shopov, ktoré môžu volať API |
| `ADMIN_TOKEN` | heslo pre `POST /admin/sync` (okamžitá aktualizácia katalógu) |

## Vloženie do Upgates

V administrácii Upgates vložte do vlastných skriptov / HTML kódov (vkladanie kódu do hlavičky alebo pätičky
všetkých stránok) tento riadok:

```html
<script src="https://search.primework.sk/widget.js" defer></script>
```

Widget sám nájde vyhľadávacie pole šablóny (`input[name="q"]`, `input[type="search"]`…). Ak ho nenájde,
zadajte selektor ručne. Ďalšie voliteľné nastavenia:

```html
<script src="https://search.primework.sk/widget.js" defer
        data-input="#search input"
        data-lang="sk"
        data-enter="ai"></script>
```

- `data-lang` – `sk` alebo `hu`; predvolene podľa `<html lang>`, takže na maďarskej doméne sa automaticky použije HU katalóg a meny.
- `data-enter="native"` – Enter ponechá pôvodné vyhľadávanie Upgates; AI sa spúšťa iba tlačidlom.

Odkaz „Zobraziť všetky výsledky“ odošle pôvodný formulár, takže stránka výsledkov Upgates ostáva funkčná.

## Náklady

Okamžité vyhľadávanie počas písania AI nevolá. Claude sa volá len pri Enter / tlačidle AI (2 volania
na dopyt, opakované dopyty idú z cache). Predvolený model je najlacnejší Claude Haiku 5.5
(0,10 $ / 0,50 $ za milión vstupných / výstupných tokenov). Pre ešte nižšie náklady nastavte `AI_RERANK=0`.
