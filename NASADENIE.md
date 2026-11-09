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
4. **Settings → API Keys → Create Key**, pomenujte ho `primework-search`.
5. Skopírujte kľúč (začína `sk-ant-…`) a uložte si ho bezpečne. Zobrazí sa len raz.
   Kľúč nikomu neposielajte e-mailom ani do chatu.

## Krok 2 – API prístup do Upgates (5 min)

1. V administrácii Upgates: **Nastavenia → Import / Export → záložka Ostatné** (API).
2. Ak API nie je zapnuté, zapnite ho. Stačí oprávnenie na **čítanie produktov a jazykov**.
3. Skopírujte **API login** a **API kľúč (heslo)**.
4. Adresa API pre váš obchod je `https://prime-work.admin.s35.upgates.com/api/v2` (už je prednastavená).

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
