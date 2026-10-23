# Zmeny v rutinách „Kontrola objednávok 6:40“ a „Kontrola objednávok 10:10“

Rovnaké zmeny urob v oboch rutinách.

## 1) V časti 0a nahraď vetu
NIKDY neposuň do stavu „3.Objednávka sa pripravuje v sklade“, 16.1 ani 16.2 objednávku s platbou vopred, ktorá nie je zaplatená (bod 2a).

## týmto:
NIKDY neposuň do stavu „3.Objednávka sa pripravuje v sklade“ ani 16.1 B2C objednávku s platbou vopred, ktorá nie je zaplatená (bod 2a). B2B objednávky idú vždy do 16.2 bez ohľadu na platbu (bod 1b).

## 2) Pred riadok „2a) PLATBA …“ vlož nový odsek:
1b) B2B – KONTROLUJ AKO PRVÉ (pred platbou aj pred všetkým ostatným): B2B = vo Firemných údajoch je vyplnené ČOKOĽVEK z toho: spoločnosť (company), IČO (ico) alebo DIČ (dic), ALEBO je zákazník v skupine zákazníkov, ktorej názov obsahuje „B2B“. Skupinu zákazníka vždy over. Každú B2B objednávku HNEĎ nastav do stavu 16.2 – bez ohľadu na typ platby a na to, či je zaplatená (platí aj pre platbu so splatnosťou, napr. „35. Fizetési határidő (PAY)“ s payment.type = command, pre neznámy typ platby aj pre nezaplatenú online platbu). Pri B2B údaje nekontroluj ani neopravuj a bod 2a nepoužívaj. Do internej poznámky zapíš len: predfaktúra → „PROFORM“, zákazník v skupine „Black List 61“ → „6/BL“, hlásenie o žiadosti o odstúpenie → skrátený problém (stav ostáva 16.2). Ak je B2B s online platbou vopred nezaplatená, napíš do reportu „Na riešenie: B2B v 16.2, čaká na platbu (<payment.name>)“.

## 3) Nahraď
2a) PLATBA (kontroluj PRED všetkým ostatným, aj pri B2B):

## týmto:
2a) PLATBA (iba pre B2C – B2B už je v 16.2 podľa bodu 1b):

## 4) Pod riadok o dobierke/hotovosti vlož:
Platba so splatnosťou na faktúru (payment.type = command, napr. „35. Fizetési határidő (PAY)“) → platba vopred sa nevyžaduje, pokračuj bodom 2.

## 5) Nahraď
STAV OBJEDNÁVKY (iba pre objednávky, ktoré prešli bodom 2a):
B2B = vo Firemných údajoch je vyplnená spoločnosť (company), IČO (ico) alebo DIČ (dic), ALEBO je zákazník v skupine zákazníkov, ktorej názov obsahuje „B2B“ → údaje nekontroluj a nastav stav 16.2. Skupinu zákazníka vždy over.
Všetky ostatné objednávky (B2C) skontroluj podľa bodov 3 a 4 …

## týmto:
STAV B2C OBJEDNÁVKY (iba pre B2C objednávky, ktoré prešli bodom 2a):
B2C objednávky skontroluj podľa bodov 3 a 4 …
