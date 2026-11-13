# Faktúry PDF → TXT príjemka

Z PDF faktúry dodávateľa vytvorí TXT súbor na import príjemky do skladového
hospodárstva (*Sklad 2 → Pridanie pohybu → Načítanie pomocného dokladu → Externý textový (TXT)*).
Do súboru idú tri dôležité údaje: **EAN, počet kusov a cena MJ** (+ mena).

## Formát TXT (pevná dĺžka položiek)

| Pole     | Pozícia | Dĺžka |
|----------|--------:|------:|
| EAN kód  | 1       | 14    |
| Počet MJ | 15      | 15    |
| Cena MJ  | 30      | 15    |
| Mena     | 45      | 3     |

```
5908274527801        3.000000      19.260000EUR
```
Riadky končia CRLF (Windows). Toto nastavenie musí byť v okne *Štruktúra súboru TXT* (Ctrl+P).

## Ako to funguje pri rôznych dodávateľoch

Netreba šablónu pre každého dodávateľa. Aplikácia:

1. nájde na faktúre všetky **EAN-13** a overí kontrolnú číslicu (IČO, DIČ, čísla účtov a colné kódy tak vypadnú),
2. pri každom EAN hľadá v tom istom riadku (alebo v susednom riadku tej istej položky)
   dvojicu **množstvo × cena = hodnota položky**, takže nezáleží na poradí stĺpcov
   a pri zľave sa zoberie cena **po zľave**,
3. spočíta všetky položky a porovná súčet so sumou *Total / Spolu / Razem / Invoice total* na faktúre
   (✔ súčet sedí, ⚠ nesedí, treba skontrolovať).

Overené na faktúrach PROCERA (Comarch ERP Optima) a RAW-POL (pro forma).

## Použitie

**Program v okne (Windows):** stiahni `FakturyTXT.exe` z GitHub Actions
(záložka *Actions → Faktury TXT – Windows .exe → Artifacts*) a spusti ho.
Prípadne s nainštalovaným Pythonom dvojklik na `spustit.bat`.

1. *Pridať PDF faktúry…* (naraz aj viac faktúr),
2. skontroluj zoznam (vľavo ✔ = súčet sedí s faktúrou),
3. riadky, ktoré nechceš (napr. doprava / logistické náklady), vypni medzerníkom
   alebo *Vždy vynechať tento EAN* (zapamätá sa),
4. dvojklikom sa dá opraviť EAN, počet alebo cena,
5. *Uložiť TXT* a súbor načítaj do skladu.

**Príkazový riadok:**
```
python invoice_parser.py faktura1.pdf faktura2.pdf -o C:\Users\dell\Desktop\Snimka --skip-ean 5907522900007
```

## Obmedzenia

- PDF musí obsahovať text (faktúry z účtovných programov ho obsahujú). Naskenovaný papier treba najprv dať cez OCR.
- Položky bez EAN sa nenačítajú, program na ne upozorní len ak má EAN, ale chýba množstvo alebo cena.
