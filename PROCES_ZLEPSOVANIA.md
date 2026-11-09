# Proces zlepšovania AI vyhľadávania

Ako raz týždenne skontrolovať, či AI odpovedala dobre, a opraviť to, čo nesedí. Bez programovania,
všetko v prehliadači. Trvá 15–30 minút týždenne.

Odkazy (nahraďte `VAS_TOKEN` tokenom z Render → prime-ai-search → Environment → `ADMIN_TOKEN`):

| Stránka | Adresa |
|---|---|
| Týždenný report | `prime-ai-search.onrender.com/report?token=VAS_TOKEN` |
| AI odpovede (hodnotenie a opravy) | `prime-ai-search.onrender.com/report/ai?token=VAS_TOKEN&filter=unrated` |
| Pravidlá a pokyny pre AI | `prime-ai-search.onrender.com/report/rules?token=VAS_TOKEN` |

Tip: všetky tri si uložte do záložiek (Ctrl+D).

---

## Odkiaľ sa dozviete, že niečo nie je v poriadku

1. **Zákazník sám** – pod každou AI odpoveďou je „Pomohlo vám to? 👍 👎“.
2. **Správanie zákazníka** – či po AI odpovedi klikol na produkt (✅ klikol / „zákazník neklikol“).
3. **Vy** – na stránke AI odpovede si každú odpoveď prečítate a označíte 👍 Dobrá / 👎 Zlá.
4. **Report** – úspešnosť AI vyhľadávaní (% s klikom) a jej zmena oproti minulému týždňu.

## Týždenný postup (každý pondelok)

### 1. Otvorte AI odpovede → záložka **Zlé (👎)**
Tu sú odpovede, ktoré ohodnotil zákazník 👎 alebo vy. Začnite nimi – sú najdôležitejšie.
Potom prejdite záložku **Bez kliku** (zákazník nič nevybral) a nakoniec **Nehodnotené**.

### 2. Pri každej odpovedi si všimnite 3 veci

| Čo vidíte | Otázka |
|---|---|
| **AI pochopila:** veta a kľúčové slová | Pochopila AI, čo zákazník chcel? |
| **Zoznam produktov** s dôvodmi ✔ | Sú to správne produkty? Je ten najlepší navrchu? |
| **Zákazník** (👍/👎, klikol na…) | Našiel zákazník, čo hľadal? |

Označte **👍 Dobrá odpoveď** alebo **👎 Zlá odpoveď** a do poznámky napíšte, čo bolo zle
(napr. „ukázalo aj sandále, chcem iba uzavretú obuv“). Poznámky slúžia vám a pri ďalšom ladení.

### 3. Vyberte nápravu podľa toho, čo bolo zle

| Problém | Náprava | Kde |
|---|---|---|
| Správny produkt chýba alebo je nízko | **📌 Pripnúť iný produkt** – zadajte kód produktu | pri odpovedi |
| Dobrý produkt je až na 4. mieste | **📌 Pripnúť pre tento výraz** pri tom produkte | pri produkte |
| Medzi výsledkami je nevhodný produkt | **🚫 Skryť pre tento výraz** | pri produkte |
| AI niečo pochopila zle všeobecne (napr. „do zimy“ = zateplené) | **➕ Pridať pokyn pre AI** – jedna jasná veta | pri odpovedi alebo v Pravidlách |
| Zákazník použil slovo, ktoré katalóg nepozná | **➕ Pridať synonymum** – v reporte („Máte, ale zákazníci to volajú inak“) alebo v Pravidlách → Synonymá | report / Pravidlá |
| Produkt v sortimente nie je | Zoznam **„Čo zákazníci hľadajú a nemáte“** v reporte → zvážte doplnenie | report |
| Produkt má zlý alebo chudobný názov / popis | Opravte názov či popis v Upgates – vyhľadávanie ho načíta do hodiny | Upgates |

**Ako platia pripnuté a skryté produkty:** pre každé vyhľadávanie, ktoré obsahuje **všetky slová**
výrazu (bez ohľadu na diakritiku a veľké písmená). Pravidlo „zimné rukavice“ platí aj pre
„zimne rukavice do 10 €“, ale nie pre samotné „rukavice“. Platia v okamžitom vyhľadávaní aj v AI.

**Ako písať pokyny pre AI** (platia pre všetky AI vyhľadávania v danej krajine):
- jedna veta, jedna vec: *„Keď zákazník hľadá ‚do zimy‘ alebo ‚zimné‘, ponúkni iba zateplené produkty.“*
- konkrétne slová, ktoré zákazníci používajú: *„‚Montérky‘ znamená montérkové nohavice, nie bundy.“*
- čo uprednostniť: *„Pri rukaviciach na stavbu uprednostni rukavice s normou EN388.“*
- nepíšte všeobecnosti ako „buď presnejšia“ – AI nevie, čo presne chcete.
- maďarský e-shop má vlastné pokyny (pri pridávaní vyberte krajinu); pokyn môžete napísať po slovensky.

### 4. Overte opravu
Na testovacej stránke `prime-ai-search.onrender.com/demo` (alebo priamo na e-shope) zadajte ten istý
výraz a stlačte Enter. Pripnutie, skrytie aj nový pokyn platia **okamžite**.

### 5. Sledujte výsledok o týždeň
V reporte porovnajte **úspešnosť AI vyhľadávaní** s minulým týždňom a v AI odpovediach skontrolujte,
či sa zlé odpovede na rovnaké výrazy už neopakujú.

## Synonymá

- **V reporte** v časti „Máte, ale zákazníci to volajú inak“ je pri každom riadku formulár:
  vľavo slová zákazníka (viac oddeľte čiarkou), vpravo výraz z katalógu. Upravte podľa potreby
  a kliknite **➕ Pridať synonymum**. Riadok sa zmení na „✔ pridané“.
- **V Pravidlách → Synonymá** sú všetky synonymá so zdrojom (vy / súbor synonyms.json / AI automaticky):
  - **upraviť**: zmeňte výraz v katalógu v riadku a kliknite **Uložiť**,
  - **Zmazať** vaše synonymum, **Vypnúť** automatické alebo zo súboru (a **Zapnúť** späť),
  - nové synonymum pridáte formulárom nad tabuľkou.
- Všetko platí **okamžite** v okamžitom vyhľadávaní aj v našepkávači.

## Údržba pravidiel (raz za mesiac)
Na stránke **Pravidlá** prejdite pripnuté a skryté produkty. Zmažte pravidlá pre produkty, ktoré
už nepredávate, a pokyny, ktoré si protirečia. Menej presných pravidiel funguje lepšie ako veľa
všeobecných.

## Kedy kontaktovať vývojára
- AI odpovede sú zlé hromadne a pokyny nepomáhajú (možno treba silnejší model, napr. `claude-sonnet-5-5`
  v Render → Environment → `AI_MODEL`),
- na stránke AI odpovede je často „AI neodpovedala“ (kľúč, kredit alebo výpadok – pozrite `/healthz`),
- chcete pravidlá iného typu (napr. podľa kategórie alebo ceny).
