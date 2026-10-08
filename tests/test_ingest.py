"""Real-world statement formats (services/ingest.py) + preview/demo endpoints."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CREDITLENS_DB", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("CREDITLENS_JWT_SECRET", "t" * 40)
os.environ["CREDITLENS_AUTH_RATE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.features import StatementError, extract_features_from_bytes  # noqa: E402
from app.services.ingest import classify, load_statement  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


def csv_bytes(text: str) -> bytes:
    return text.strip().encode()


def months_csv(header: str, line, months: int = 4) -> bytes:
    rows = [header]
    for m in range(1, months + 1):
        rows += line(m)
    return "\n".join(rows).encode()


class IngestTests(unittest.TestCase):
    def test_bank_export_with_preamble_and_debit_credit_columns(self):
        fr = extract_features_from_bytes((DATA / "bank_export_hdfc_style.csv").read_bytes())
        self.assertEqual(fr.report["mapping"]["debit"], "Withdrawal Amt.")
        self.assertEqual(fr.features["history_months"], 7.0)
        counts = fr.report["category_counts"]
        for cat in ("income", "rent", "food", "emi", "savings", "utilities", "mobile", "subscription"):
            self.assertIn(cat, counts)
        self.assertAlmostEqual(fr.features["rent_to_income"], 9000 / 28000, delta=0.03)

    def test_upi_style_dr_cr_column_with_positive_amounts(self):
        fr = extract_features_from_bytes((DATA / "upi_gig_style.csv").read_bytes())
        self.assertEqual(fr.report["mapping"]["drcr"], "Dr/Cr")
        self.assertGreater(fr.features["rent_to_income"], 0.1)
        self.assertGreater(fr.report["category_counts"]["income"], 20)

    def test_formats_amounts_semicolons_and_latin1(self):
        raw = months_csv("Date;Particulars;Amount",
                         lambda m: [f"05/{m:02d}/2026;SALARY CREDIT;\"₹ 30,000.00\"".replace("₹", "Rs"),
                                    f"10/{m:02d}/2026;Rent to landlord;(9,000.00)",
                                    f"12/{m:02d}/2026;Caf\xe9 lunch;-500"]).decode().encode("cp1252")
        fr = extract_features_from_bytes(raw)
        self.assertAlmostEqual(fr.features["rent_to_income"], 0.3, places=3)
        self.assertAlmostEqual(fr.features["savings_ratio"], (30000 - 9500) / 30000, places=3)

    def test_existing_category_column_still_respected_and_synonyms_mapped(self):
        raw = months_csv("date,amount,category,description",
                         lambda m: [f"2026-{m:02d}-01,30000,Salary,x", f"2026-{m:02d}-04,-9000,rent,x",
                                    f"2026-{m:02d}-09,-3000,Groceries,x", f"2026-{m:02d}-11,-800,mystery,swiggy"])
        df, rep = load_statement(raw)
        self.assertEqual(set(df["category"]), {"income", "rent", "food"})
        self.assertEqual(rep["auto_categorised"], 4)  # the 4 'mystery' rows were classified from description

    def test_classifier_rules(self):
        self.assertEqual(classify("SWIGGY ORDER 123", -300), "food")
        self.assertEqual(classify("Amazon refund", 500), "transfer")
        self.assertEqual(classify("SIP Groww", -2000), "savings")
        self.assertEqual(classify("Uber trip", -150), "transport")
        self.assertEqual(classify("UPI from friend", 800), "income")
        self.assertEqual(classify("mystery", -10), "other")
        self.assertEqual(classify("Swiggy payout", 4000), "income")   # money IN is not food

    def test_friendly_errors(self):
        with self.assertRaisesRegex(StatementError, "Found columns: foo, bar"):
            extract_features_from_bytes(b"foo,bar\n1,2\n")
        with self.assertRaisesRegex(StatementError, "empty"):
            extract_features_from_bytes(b"   \n")
        with self.assertRaisesRegex(StatementError, "at least 3 months"):
            extract_features_from_bytes(csv_bytes("date,amount\n2026-01-01,100\n2026-01-02,-5"))


class PreviewAndDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.c = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def guest(self):
        r = self.c.post("/auth/demo")
        self.assertEqual(r.status_code, 201)
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def test_demo_login_creates_guest(self):
        h = self.guest()
        me = self.c.get("/auth/me", headers=h).json()
        self.assertTrue(me["is_guest"])
        self.assertTrue(me["email"].endswith("@guest.creditlens.local"))

    def test_preview_ready_and_not_ready_and_requires_auth(self):
        h = self.guest()
        body = (DATA / "bank_export_hdfc_style.csv").read_bytes()
        r = self.c.post("/preview", headers=h, files={"file": ("a.csv", body, "text/csv")})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["ready"])
        self.assertEqual(j["months"], 7)
        self.assertEqual(len(j["sample"]), 8)
        self.assertEqual(self.c.get("/scores", headers=h).json(), [])   # preview stores nothing

        short = b"date,amount,category\n2026-01-01,100,income\n2026-01-02,-5,food\n"
        j = self.c.post("/preview", headers=h, files={"file": ("a.csv", short, "text/csv")}).json()
        self.assertFalse(j["ready"])
        self.assertIn("3 months", j["problem"])
        self.assertEqual(self.c.post("/preview", files={"file": ("a.csv", body, "text/csv")}).status_code, 401)

    def test_score_bank_export_returns_ingest_report(self):
        h = self.guest()
        body = (DATA / "upi_gig_style.csv").read_bytes()
        r = self.c.post("/score", headers=h, data={"consent": "true"}, files={"file": ("a.csv", body, "text/csv")})
        self.assertEqual(r.status_code, 201)
        self.assertIn("category_counts", r.json()["ingest"])
        again = self.c.get(f"/scores/{r.json()['id']}", headers=h).json()
        self.assertEqual(again["ingest"]["rows"], r.json()["ingest"]["rows"])


if __name__ == "__main__":
    unittest.main()
