"""Offers engine, card advice, manual form scoring and dashboard."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CREDITLENS_DB", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("CREDITLENS_JWT_SECRET", "t" * 40)
os.environ["CREDITLENS_AUTH_RATE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import offers  # noqa: E402
from app.services.dashboard import plan_to_reach  # noqa: E402
from app.services.features import extract_features  # noqa: E402
from app.services.manual import build_statement  # noqa: E402
from app.services.scoring import get_model  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
FEATS = {"history_months": 9, "emi_burden": 0.06, "savings_ratio": 0.10, "bill_punctuality": 0.9}
MONTH = {"income": 30000, "rent": 9000, "emi": 0, "bills": 1200, "food": 4000, "shopping": 2000,
         "transport": 1500, "subscription": 300, "other": 1500, "savings": 3000}


class MathTests(unittest.TestCase):
    def test_emi_known_values_and_inverse(self):
        self.assertAlmostEqual(offers.emi(100000, 12, 12), 8884.88, places=2)
        self.assertAlmostEqual(offers.emi(120000, 0, 12), 10000.0)
        for rate in (0, 9.5, 24):
            e = offers.emi(250000, rate, 36)
            self.assertAlmostEqual(offers.affordable_principal(e, rate, 36), 250000, delta=0.01)

    def test_rate_improves_with_score_and_is_bounded(self):
        p = {"min_score": 600, "rate_best": 10.0, "rate_worst": 20.0}
        rates = [offers.indicative_rate(p, s, 800) for s in (600, 650, 700, 800, 900)]
        self.assertEqual(rates[0], 20.0)
        self.assertEqual(rates[-1], 10.0)
        self.assertEqual(rates, sorted(rates, reverse=True))


class LoanMatchingTests(unittest.TestCase):
    def test_more_loans_unlock_as_score_rises(self):
        n = lambda s: sum(x["status"] == "eligible" for x in offers.match_loans(s, FEATS))
        self.assertLess(n(400), n(620))
        self.assertLess(n(620), n(800))

    def test_secured_loans_open_to_everyone(self):
        ids = {x["id"] for x in offers.match_loans(320, {**FEATS, "history_months": 1}) if x["status"] == "eligible"}
        self.assertTrue({"gold-loan", "loan-against-fd", "credit-builder"} <= ids)

    def test_close_status_and_points_needed(self):
        by = {x["id"]: x for x in offers.match_loans(660, FEATS)}
        self.assertEqual(by["personal-prime"]["status"], "close")       # min 700, 40 points short
        self.assertEqual(by["personal-prime"]["points_needed"], 40)
        self.assertEqual(by["home-loan"]["status"], "close")
        self.assertEqual(offers.match_loans(400, FEATS)[-1]["status"], "not_yet")

    def test_history_and_emi_blockers(self):
        short = {x["id"]: x for x in offers.match_loans(800, {**FEATS, "history_months": 3})}
        self.assertEqual(short["home-loan"]["status"], "close")        # score is fine, history is the only gap
        self.assertTrue(any("months of history" in b for b in short["home-loan"]["blockers"]))
        heavy = {x["id"]: x for x in offers.match_loans(800, {**FEATS, "emi_burden": 0.6})}
        self.assertNotEqual(heavy["home-loan"]["status"], "eligible")

    def test_income_sizes_the_loan_and_never_exceeds_product_max(self):
        low = {x["id"]: x for x in offers.match_loans(720, FEATS, 20000)}
        high = {x["id"]: x for x in offers.match_loans(720, FEATS, 200000)}
        self.assertLess(low["personal-prime"]["max_amount_for_you"], high["personal-prime"]["max_amount_for_you"])
        for x in high.values():
            self.assertLessEqual(x["max_amount_for_you"], x["amount_range"][1])
        self.assertIsNone(offers.match_loans(720, FEATS)[0]["max_amount_for_you"])      # no income, no sizing
        # the sized loan really is affordable: EMI at the sizing tenure <= 50% of income minus existing EMIs
        p = low["personal-standard"]
        e = offers.emi(p["max_amount_for_you"], p["rate_apr"], p["tenure_months"][1])
        self.assertLessEqual(e, (0.5 - FEATS["emi_burden"]) * 20000 + 1)

    def test_catalog_sanity(self):
        for p in offers.get_provider().loan_catalog()["products"]:
            self.assertLessEqual(p["rate_best"], p["rate_worst"], p["id"])
            self.assertLessEqual(p["tenure"][0], p["tenure"][1], p["id"])
            self.assertLessEqual(p["amount"][0], p["amount"][1], p["id"])
        for c in offers.get_provider().card_catalog()["cards"]:
            self.assertEqual(set(c["reward"]), set(offers.get_provider().card_catalog()["groups"]), c["id"])

    def test_unknown_provider_is_rejected(self):
        os.environ["CREDITLENS_OFFER_PROVIDER"] = "nope"
        try:
            with self.assertRaises(RuntimeError):
                offers.get_provider()
        finally:
            del os.environ["CREDITLENS_OFFER_PROVIDER"]


class CardTests(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(offers.card_advice(430, FEATS)["verdict"], "build_first")
        self.assertEqual(offers.card_advice(700, {**FEATS, "history_months": 2})["verdict"], "build_first")
        self.assertEqual(offers.card_advice(700, {**FEATS, "emi_burden": 0.55})["verdict"], "build_first")
        self.assertEqual(offers.card_advice(700, {**FEATS, "savings_ratio": 0.0, "emi_burden": 0.3})["verdict"], "caution")
        self.assertEqual(offers.card_advice(720, {**FEATS, "bill_punctuality": 0.95})["verdict"], "good_fit")

    def test_build_first_recommends_secured_cards_only(self):
        r = offers.match_cards(430, FEATS)
        rec = [c for c in r["cards"] if c.get("recommended")]
        self.assertTrue(rec and all(c["tag"] == "build" for c in rec))
        self.assertEqual(rec[0]["id"], "secured-fd")

    def test_rewards_follow_spending_mix(self):
        foodie = offers.match_cards(700, {**FEATS, "bill_punctuality": 0.95}, {"food": 0.8, "transport": 0.1, "other": 0.1})
        driver = offers.match_cards(700, {**FEATS, "bill_punctuality": 0.95}, {"transport": 0.8, "food": 0.1, "other": 0.1})
        top = lambda r: next(c["id"] for c in r["cards"] if c["status"] == "eligible" and c["tag"] != "build")
        self.assertEqual(top(foodie), "dining-delivery")
        self.assertEqual(top(driver), "fuel-commute")
        self.assertFalse(foodie["spend_share_is_default"])
        self.assertTrue(offers.match_cards(700, FEATS)["spend_share_is_default"])

    def test_net_value_uses_fee_waiver(self):
        r = offers.match_cards(700, FEATS, {"food": 1.0}, monthly_spend=10000)
        c = next(x for x in r["cards"] if x["id"] == "dining-delivery")
        self.assertEqual(c["fee_waived"], True)                          # 1.2L yearly >= 60k waiver
        self.assertEqual(c["net_annual_value"], round(120000 * 0.05))


class ManualAndApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.c = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def guest(self):
        return {"Authorization": f"Bearer {self.c.post('/auth/demo').json()['access_token']}"}

    def manual(self, h, months=None, pct=100, consent=True):
        return self.c.post("/score/manual", headers=h,
                           json={"months": months or [MONTH] * 6, "bills_on_time_pct": pct, "consent": consent})

    def test_manual_features_match_hand_calculation(self):
        fr = extract_features(build_statement([MONTH] * 6, 100))
        self.assertEqual(fr.features["income_consistency"], 1.0)
        self.assertAlmostEqual(fr.features["rent_to_income"], 0.3, places=3)
        self.assertAlmostEqual(fr.features["savings_ratio"], (30000 - (9000 + 1200 + 4000 + 2000 + 1500 + 300 + 1500)) / 30000, places=3)
        self.assertEqual(fr.features["bill_punctuality"], 1.0)
        self.assertEqual(fr.features["history_months"], 6.0)

    def test_manual_on_time_percentage_is_respected_and_lowers_score(self):
        ps = [extract_features(build_statement([MONTH] * 6, p)).features["bill_punctuality"] for p in (100, 75, 50, 25, 0)]
        self.assertEqual(ps, sorted(ps, reverse=True))
        self.assertAlmostEqual(ps[2], 0.5, delta=0.05)
        self.assertEqual(ps[-1], 0.0)

    def test_manual_endpoint_end_to_end(self):
        h = self.guest()
        r = self.manual(h)
        self.assertEqual(r.status_code, 201)
        j = r.json()
        self.assertEqual(j["ingest"]["source"], "form")
        self.assertTrue(abs(j["baseline_score"] + sum(f["points"] for f in j["factors"]) - j["score"]) <= 2)
        self.assertIn("spend_share", j["profile"])
        self.assertEqual(self.c.get(f"/scores/{j['id']}", headers=h).json()["score"], j["score"])
        late = self.manual(h, pct=20).json()["score"]
        self.assertLess(late, j["score"])

    def test_manual_validation(self):
        h = self.guest()
        self.assertEqual(self.manual(h, consent=False).status_code, 400)
        self.assertEqual(self.manual(h, months=[MONTH] * 2).status_code, 422)             # <3 months
        self.assertEqual(self.manual(h, months=[{**MONTH, "income": -5}] * 4).status_code, 422)
        self.assertEqual(self.manual(h, months=[{**MONTH, "income": 0}] * 4).status_code, 422)
        self.assertEqual(self.manual(h, pct=140).status_code, 422)
        self.assertEqual(self.c.post("/score/manual", json={}).status_code, 401)

    def test_loans_and_cards_endpoints_and_isolation(self):
        h, other = self.guest(), self.guest()
        sid = self.manual(h).json()["id"]
        j = self.c.get(f"/scores/{sid}/loans?monthly_income=30000", headers=h).json()
        self.assertEqual(sum(j["summary"].values()), len(j["loans"]))
        self.assertTrue(any(x["max_amount_for_you"] for x in j["loans"]))
        k = self.c.get(f"/scores/{sid}/cards?monthly_spend=12000", headers=h).json()
        self.assertIn(k["advice"]["verdict"], {"build_first", "caution", "good_fit", "optional"})
        self.assertFalse(k["spend_share_is_default"])
        self.assertEqual(self.c.get(f"/scores/{sid}/loans", headers=other).status_code, 404)
        self.assertEqual(self.c.get(f"/scores/{sid}/cards", headers=other).status_code, 404)
        self.assertEqual(self.c.get(f"/scores/{sid}/loans").status_code, 401)
        self.assertEqual(self.c.get(f"/scores/{sid}/loans?monthly_income=-1", headers=h).status_code, 422)

    def test_dashboard_empty_then_populated(self):
        h = self.guest()
        self.assertEqual(self.c.get("/dashboard", headers=h).json(), {"has_scores": False})
        self.manual(h, pct=40)
        d = self.c.get("/dashboard", headers=h).json()
        self.assertTrue(d["has_scores"])
        self.assertEqual(len(d["trend"]), 1)
        self.assertIsNone(d["change"]["vs_previous"])
        self.assertTrue(d["goal"]["steps"])
        self.manual(h, pct=100)                                   # second check: better habits
        d = self.c.get("/dashboard", headers=h).json()
        self.assertEqual(len(d["trend"]), 2)
        self.assertGreater(d["change"]["vs_previous"], 0)
        self.assertTrue(any(a["level"] == "good" for a in d["alerts"]))
        self.assertEqual(d["stats"]["checks"], 2)
        self.assertEqual(self.c.get("/dashboard").status_code, 401)

    def test_goal_plan_is_computed_with_the_real_model(self):
        h = self.guest()
        j = self.manual(h, pct=30).json()
        d = self.c.get("/dashboard", headers=h).json()
        g = d["goal"]
        scores = [s["score_after"] for s in g["steps"]]
        self.assertEqual(scores, sorted(scores))                  # each applied tip never lowers the score
        plan = plan_to_reach(get_model(), j["features"], j["tips"], g["target"])
        self.assertEqual(plan["final_score"], g["final_score"])


if __name__ == "__main__":
    unittest.main()
