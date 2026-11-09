# Nasadenie AI vyhľadávania na primework.sk – krok za krokom

Postup trvá asi 30–45 minút. Potrebujete prístup do administrácie Upgates, k GitHub účtu
s repozitárom `prime-kontrola` a k nastaveniam DNS domény primework.sk.

Odhad mesačných nákladov: hosting Render ~7–8 $, Claude Haiku podľa návštevnosti (zvyčajne
jednotky dolárov). Ceny sa môžu meniť, overte ich na render.com/pricing a claude.com/pricing.

---

## Krok 1 – API kľúč pre Claude (5 min)

1. Otvorte **https://console.anthropic.com** a zaregistrujte sa (firemný e-mail).
2. **Settings → Billing**: zadajte platobnú kartu a kúpte kredit, napr. 10 $.
3. **Settings → Limits**: nastavte mesačný limit míňania (napr. 20 $), aby náklady nikdy neprekročili rozpočet.
4. **Settings → API Keys → Create Key**, pomenujte ho `primework-search`. Pri **Expires** zvoľte
   **Never** (alebo najdlhšiu dobu), inak kľúč po 30 dňoch prestane fungovať.
5. Skopírujte kľúč (začína `sk-ant-…`) a uložte si ho bezpečne. Zobrazí sa len raz.
   Kľúč nikomu neposielajte e-mailom ani do chatu.

## Krok 2 – API prístup do Upgates (5 min)

1. Otvorte v administrácii **Nastavenia → Export / Import → API**:
   `https://prime-work.admin.s35.upgates.com/setup/export-import/api/`
2. Existujúce prístupy nemeňte ani nemažte, môžu ich používať iné napojenia.
3. Kliknite na pridanie nového prístupu (**+ Nový** / **Pridať**).
4. **Názov:** `AI vyhladavanie`. **Oprávnenia:** iba **čítanie** pre **Produkty** a **Jazyky**
   (žiadny zápis, objednávky ani zákazníci).
5. Kliknite **Uložiť**.
6. Z riadku nového prístupu v tabuľke skopírujte **Login** (`UPGATES_LOGIN`) a **API kľúč**
   (`UPGATES_API_KEY`, najprv ho zobrazte). Skontrolujte, či **URL** je
   `https://prime-work.admin.s35.upgates.com/api/v2`.

## Krok 3 – Server na Render.com (10 min)

1. Otvorte **https://render.com** → **Get Started** → prihláste sa cez **GitHub**.
2. Povoľte Renderu prístup k repozitáru **primeeuropesro-sk/prime-kontrola**.
3. V Renderi kliknite **New → Blueprint** a vyberte repozitár `prime-kontrola`.
   Vetva: `claude/eloquent-euler-9ivru6` (alebo `main`, ak zmeny zlúčite).
4. Render načíta súbor `render.yaml` a vypýta si tajné hodnoty:
   - `ANTHROPIC_API_KEY` – kľúč z kroku 1
   - `UPGATES_LOGIN` – login z kroku 2
   - `UPGATES_API_KEY` – kľúč z kroku 2
5. Kliknite **Apply**. Render zostaví a spustí server (3–5 minút).
6. Po spustení dostanete adresu typu `https://prime-ai-search.onrender.com`. Otvorte
   `https://prime-ai-search.onrender.com/healthz`. Prvé načítanie produktov z Upgates trvá niekoľko minút.
   Keď je všetko v poriadku, uvidíte:
   ```
   {"ok": true, "ai": true, "products": {"sk": 864, "hu": 864}, ...}
   ```
   - `"ok": false` → produkty sa ešte načítavajú (počkajte), alebo sú zlé údaje Upgates (pozrite **Logs** v Renderi).
   - `"ai": false` → chýba alebo je zlý `ANTHROPIC_API_KEY`.
7. Otvorte `https://prime-ai-search.onrender.com/demo` a vyskúšajte napr. `pr0cera zymna bunda`,
   potom Enter (AI vyhľadávanie).

## Krok 4 – Vlastná doména search.primework.sk (10 min, odporúčané)

Tento krok môžete preskočiť a používať adresu `…onrender.com`. Vlastná doména však vyzerá dôveryhodnejšie.

1. V Renderi: služba **prime-ai-search → Settings → Custom Domains → Add** → `search.primework.sk`.
2. Render ukáže, aký **CNAME** záznam treba pridať.
3. U správcu DNS domény primework.sk (tam, kde máte doménu registrovanú) pridajte záznam:

   | Typ | Názov | Hodnota |
   |---|---|---|
   | CNAME | `search` | `prime-ai-search.onrender.com` |

4. Po overení (zvyčajne do hodiny) Render sám vydá HTTPS certifikát.
   Overte, že funguje `https://search.primework.sk/healthz`.

## Krok 5 – Vloženie do Upgates (5 min)

1. V administrácii Upgates: **Doplnky → Vlastné konverzné kódy**.
2. V sekcii **Kódy umiestnené na všetkých stránkách** vložte do poľa pre hlavičku (medzi `<head>` tagmi):
   ```html
   <script src="https://search.primework.sk/widget.js" defer></script>
   ```
   (Ak ste preskočili krok 4, použite `https://prime-ai-search.onrender.com/widget.js`.)
3. Kliknite **Uložiť**.
4. To isté urobte aj pre maďarský e-shop munkaruhazatolcson.hu, ak má vlastné nastavenie kódov.
   Widget podľa jazyka stránky sám použije maďarský katalóg a forinty.

## Krok 6 – Kontrola na e-shope

1. Otvorte www.primework.sk v anonymnom okne a začnite písať do vyhľadávania, napr. `rukavyce`.
2. Pod poľom sa má okamžite zobraziť panel s produktmi a tlačidlom **✨ Opýtať sa AI**.
3. Napíšte vetu, napr. `topánky s oceľovou špičkou do 40 €`, a stlačte Enter.

**Ak sa panel nezobrazí:** widget nenašiel vyhľadávacie pole šablóny. Kliknite na vyhľadávacie pole
pravým tlačidlom → **Preskúmať**, skopírujte riadok `<input …>` a doplňte jeho selektor do skriptu, napr.:
```html
<script src="https://search.primework.sk/widget.js" defer data-input="#search-input"></script>
```

## Prevádzka

- Produkty sa z Upgates aktualizujú automaticky každú hodinu.
- Okamžitá aktualizácia (napr. po pridaní nových produktov): v Renderi zistite hodnotu `ADMIN_TOKEN`
  (Environment) a spustite:
  ```bash
  curl -X POST -H "X-Admin-Token: VAS_TOKEN" https://search.primework.sk/admin/sync
  ```
- Náklady na AI sledujete v console.anthropic.com → **Usage**.
- Vypnutie AI (ostane len rýchle vyhľadávanie s opravou preklepov): v Renderi zmažte `ANTHROPIC_API_KEY`.
- Zrušenie celej funkcie: v Upgates odstráňte vložený riadok `<script …>`. E-shop sa vráti do pôvodného stavu.

## Týždenný report vyhľadávania

Report je na adrese (token nájdete v Renderi: **prime-ai-search → Environment → ADMIN_TOKEN**; odporúčame token iba z písmen a číslic):

```
https://prime-ai-search.onrender.com/report?token=VAS_ADMIN_TOKEN
```

Predvolene ukazuje minulý týždeň (pondelok – nedeľa), odkazmi sa dá prejsť na iné týždne.
Pre každú krajinu (Slovensko, Maďarsko) obsahuje:

- počet vyhľadávaní, **úspešnosť** (podiel vyhľadávaní s klikom na produkt) a porovnanie s predchádzajúcim týždňom,
- **Čo zákazníci hľadajú a nemáte** – AI (Claude Haiku) zoskupí nenájdené výrazy do konkrétnych produktov
  (napr. „zvaracska kukla“, „kukla na zváranie“, „zváračská maska“ → *Zváračská kukla, 9 hľadaní*),
  zoradí ich podľa počtu hľadaní a pripíše poznámku, čo by malo byť v sortimente. Na stiahnutie ako
  **chýbajúce produkty (CSV)** pre Excel. Pri maďarskom e-shope sú názvy produktov po slovensky.
- **Máte, ale zákazníci to volajú inak** – výrazy, pre ktoré produkt máte, s hotovým textom na skopírovanie
  do `ai_search/synonyms.json`,
- **top 20 produktov**, na ktoré zákazníci klikli z vyhľadávania,
- **hľadali a nenašli** – výrazy, pre ktoré e-shop nemá produkt so všetkými hľadanými slovami, s dátumom a časom
  posledného hľadania; CSV pre Excel obsahuje každé takéto hľadanie zvlášť s dátumom a časom (slovenský čas),
- výrazy, pri ktorých výsledky boli, ale zákazník neklikol, a top 20 hľadaných výrazov,
- počet AI vyhľadávaní a ich úspešnosť.

Zaznamenáva sa iba hľadaný text, jazyk e-shopu, počet výsledkov a kliknutý produkt – žiadne IP adresy
ani iné osobné údaje. Záznamy sa mažú po 400 dňoch.

### Posielanie reportu e-mailom každý pondelok (voliteľné)

V Renderi: **prime-ai-search → Environment → Add Environment Variable** pridajte:

| Kľúč | Hodnota (príklad pre Gmail) |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `primeeuropesro@gmail.com` |
| `SMTP_PASSWORD` | heslo aplikácie z Google účtu (myaccount.google.com → Zabezpečenie → Heslá aplikácií), nie bežné heslo |
| `REPORT_EMAIL_TO` | adresa (alebo viac adries oddelených čiarkou), kam report posielať |

Report príde každý pondelok o 7:00 (slovenského času) za predchádzajúci týždeň.

## Synonymá

- **Automatické:** server raz za týždeň (a pri zmene katalógu) nechá Claude Haiku vytvoriť zoznam slov,
  ktoré zákazníci používajú a katalóg nie (napr. kombinezón → overal). Stojí to rádovo centy mesačne.
- **Vlastné:** súbor [`ai_search/synonyms.json`](ai_search/synonyms.json) upravíte priamo na GitHube
  (ikona ceruzky → **Commit changes**). Render zmenu nasadí sám. Formát:
  `"čo píše zákazník": ["výraz z katalógu"]`. Vlastné majú prednosť pred automatickými.
- Tip: výrazy z reportu „hľadali a nenašli“ sú najlepší zdroj nových synoným.
