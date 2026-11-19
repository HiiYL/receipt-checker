import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import invoice as iv  # noqa: E402
import sources  # noqa: E402
import server  # noqa: E402

# Synthetic numbers only, NOT real draw results.
WN = iv.WinningNumbers(term="11410", special="12345678", grand="87654321",
                       first=["11122233", "44455566", "77788899"],
                       additional_sixth=["135"])


def left_qr(number="AB11122233", date="1140914", rand="1234", sales=95, total=100,
            buyer="00000000", seller="12345675", tail=":**********:2:2:1:咖啡:1:60:麵包:1:40"):
    return (number + date + rand + f"{sales:08x}" + f"{total:08x}" + buyer + seller
            + "A" * 24 + tail)


class Parse(unittest.TestCase):
    def test_left_qr(self):
        inv = iv.parse_left_qr(left_qr())
        self.assertEqual(inv.number, "AB11122233")
        self.assertEqual(inv.date, dt.date(2025, 9, 14))
        self.assertEqual((inv.sales_amount, inv.total_amount), (95, 100))
        self.assertEqual(inv.seller_id, "12345675")
        self.assertEqual([i.name for i in inv.items], ["咖啡", "麵包"])
        self.assertEqual(inv.term, "11410")

    def test_base64_items(self):
        inv = iv.parse_left_qr(left_qr(tail=":**********:1:1:2:5ZKW5ZWh:1:60"))
        self.assertEqual(inv.items[0].name, "咖啡")

    def test_barcode(self):
        inv = iv.parse_barcode("11410AB111222331234")
        self.assertEqual((inv.number, inv.term, inv.random_code), ("AB11122233", "11410", "1234"))

    def test_rejects_right_qr(self):
        with self.assertRaises(ValueError):
            iv.parse_any("**:咖啡:1:60")

    def test_manual(self):
        self.assertEqual(iv.manual_invoice("ab-11122233", "2025-10-02").number, "AB11122233")
        self.assertEqual(iv.manual_invoice("11122233", "2025-10-02").digits, "11122233")


class Periods(unittest.TestCase):
    def test_term(self):
        self.assertEqual(iv.term_for(dt.date(2025, 1, 31)), "11402")
        self.assertEqual(iv.term_for(dt.date(2025, 12, 1)), "11412")

    def test_schedule_crosses_year(self):
        s = iv.term_schedule("11412")
        self.assertEqual(s, {"draw_date": "2026-01-25", "claim_start": "2026-02-06",
                             "claim_end": "2026-05-05"})

    def test_latest_drawn(self):
        self.assertEqual(iv.latest_drawn_terms(dt.date(2026, 11, 19)), ["11508", "11506"])
        self.assertEqual(iv.latest_drawn_terms(dt.date(2026, 11, 26)), ["11510", "11508"])


class Prizes(unittest.TestCase):
    def chk(self, digits):
        return iv.check(iv.Invoice("AB" + digits, dt.date(2025, 9, 1)), WN)

    def test_tiers(self):
        cases = {"12345678": 10_000_000, "87654321": 2_000_000, "11122233": 200_000,
                 "01122233": 40_000, "00122233": 10_000, "00022233": 4_000,
                 "00002233": 1_000, "00000233": 200, "00000135": 200, "00000000": 0}
        for digits, amount in cases.items():
            self.assertEqual(self.chk(digits)["amount"], amount, digits)

    def test_special_needs_all_8(self):
        self.assertEqual(self.chk("02345678")["amount"], 0)

    def test_wrong_term(self):
        with self.assertRaises(ValueError):
            iv.check(iv.Invoice("AB11122233", dt.date(2025, 5, 1)), WN)


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
<item><title><![CDATA[114年09月、10月]]></title><description><![CDATA[
<p>特別獎：12345678</p><p>特獎：87654321</p><p>頭獎：11122233、44455566、77788899</p>
<p>增開六獎：135</p>]]></description></item>
<item><title>114年07~08月</title><description>&lt;p&gt;特別獎：11111111&lt;/p&gt;&lt;p&gt;特獎：22222222&lt;/p&gt;&lt;p&gt;頭獎：33333333、44444444、55555555&lt;/p&gt;</description></item>
</channel></rss>"""


class Sources(unittest.TestCase):
    def test_rss(self):
        a, b = sources.parse_rss(RSS)
        self.assertEqual((a.term, a.special, a.grand, a.first, a.additional_sixth),
                         ("11410", "12345678", "87654321", WN.first, ["135"]))
        self.assertEqual((b.term, b.first[2], b.additional_sixth), ("11408", "55555555", []))

    def test_mof_api_shape(self):
        d = {"code": 200, "superPrizeNo": "12345678", "spcPrizeNo": "87654321",
             "firstPrizeNo1": "11122233", "firstPrizeNo2": "44455566",
             "firstPrizeNo3": "77788899", "firstPrizeNo4": "", "sixthPrizeNo1": "135"}
        wn = sources.parse_mof_winning("11410", d)
        self.assertEqual((wn.first, wn.additional_sixth), (WN.first, ["135"]))


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_winning  # noqa: E402


class Updater(unittest.TestCase):
    def test_merge_keeps_old_terms_and_prefers_fresh(self):
        old = [{"term": "11406", "special": "1"}, {"term": "11408", "special": "old"}]
        fresh = [{"term": "11410", "special": "3"}, {"term": "11408", "special": "new"}]
        out = update_winning.merge(old, fresh)
        self.assertEqual([d["term"] for d in out], ["11410", "11408", "11406"])
        self.assertEqual(out[1]["special"], "new")

    def test_merge_caps_length(self):
        fresh = [{"term": f"114{m:02d}"} for m in (2, 4, 6, 8, 10, 12)]
        out = update_winning.merge([{"term": "11312"}], fresh, keep=6)
        self.assertEqual(out[-1]["term"], "11402")


class EndToEnd(unittest.TestCase):
    def setUp(self):
        sources._cache["11410"] = (1e18, WN)

    def test_scan_winner(self):
        out = server.check_payload({"code": left_qr()}, today=dt.date(2025, 12, 1))
        self.assertEqual((out["status"], out["result"]["amount"]), ("won", 200_000))
        self.assertEqual(out["schedule"]["claim_end"], "2026-03-05")

    def test_expired(self):
        out = server.check_payload({"code": left_qr()}, today=dt.date(2026, 4, 1))
        self.assertEqual(out["status"], "expired")

    def test_not_drawn(self):
        out = server.check_payload({"number": "AB11122233", "date": "2025-10-02"},
                                   today=dt.date(2025, 11, 1))
        self.assertEqual(out["status"], "not_drawn")


if __name__ == "__main__":
    unittest.main()
