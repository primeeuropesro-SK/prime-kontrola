import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "faktury_txt"))
import invoice_parser as ip  # noqa: E402

# Riadky v štýle reálnych faktúr (PROCERA / Comarch a RAW-POL)
PROCERA = """
No   DESCRIPTION                       CN CODE    EAN            CO   QTY   UoM TAX   PRICE    AMOUNT
  1 KURTKA OCIEPLANA PROCERA LUMA L    62033310   5908274527801  CN     3   szt  0%   19,26     57,78
  2 CZAPKA ZIMOWA AKRYLOWA DZIANA LED  65050090   5908274528969  CN    20   szt  0%    2,90     58,00
 Total:                                                                          115,78 EUR
NIP: 5732871168   Nr rachunku: 34 1050 1142 1000 0090 3108 6334
"""
RAWPOL = """
              BCNIL_B40-41
      3.      PKWiU: 15.20.13.0; EAN: 5902973668797          1 pair     11,9024    11,90 00   0,00   11,90
              TG-GANS_BM
      44.                                                    2 pc.      14,9862    29,97 00   0,00   29,97
              PKWiU: 14.12.12.0; EAN: 5902973659580
              Protective trousers
                                                    Invoice total:   41,87 x    0,00     41,87
"""
# Zľava: cena pred zľavou, % zľavy, cena po zľave, hodnota
DISCOUNT = "1 Bunda XL  5908274527801  2 ks  20,00  10%  18,00  36,00  EUR\n"


class ParserTest(unittest.TestCase):
    def test_ean_checksum(self):
        self.assertTrue(ip.ean_valid("5908274527801"))
        self.assertFalse(ip.ean_valid("5908274527802"))

    def test_procera(self):
        inv = ip.parse_pages([PROCERA])
        self.assertEqual([(i.ean, i.qty, i.price) for i in inv.items], [
            ("5908274527801", Decimal("3"), Decimal("19.26")),
            ("5908274528969", Decimal("20"), Decimal("2.90"))])
        self.assertEqual(inv.currency, "EUR")
        self.assertTrue(inv.total_ok)

    def test_rawpol_ean_on_next_line(self):
        inv = ip.parse_pages([RAWPOL])
        self.assertEqual([(i.ean, i.qty, i.price) for i in inv.items], [
            ("5902973668797", Decimal("1"), Decimal("11.9024")),
            ("5902973659580", Decimal("2"), Decimal("14.9862"))])
        self.assertTrue(inv.total_ok)

    def test_discount_price_used(self):
        inv = ip.parse_pages([DISCOUNT])
        self.assertEqual((inv.items[0].qty, inv.items[0].price), (Decimal("2"), Decimal("18.00")))

    def test_thousands(self):
        self.assertEqual(ip.to_decimal("2 031,43"), Decimal("2031.43"))
        self.assertEqual(ip.to_decimal("1.234,5"), Decimal("1234.5"))
        self.assertEqual(ip.to_decimal("1,234.5"), Decimal("1234.5"))

    def test_fixed_width_format(self):
        line = ip.format_line("5908274527801", Decimal("3"), Decimal("19.26"), "EUR")
        self.assertEqual(line, "5908274527801        3.000000      19.260000EUR")
        self.assertEqual(line.index("3.0"), 14 + 15 - len("3.000000"))
        self.assertEqual(line[44:47], "EUR")
        txt = ip.to_txt(ip.parse_pages([PROCERA]).items, "EUR")
        self.assertTrue(txt.endswith("EUR\r\n"))


if __name__ == "__main__":
    unittest.main()
