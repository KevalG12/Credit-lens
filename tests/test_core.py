"""Tests for the pure-Python core (no web server needed).

Run:  python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from app import db, security
from app.services.explain import FEATURE_META, build_result, contributions_raw, tips
from app.services.features import (BOUNDS, EXPECTED_SIGN, FEATURES, StatementError, extract_features,
                                   extract_features_from_bytes)
from app.services.scoring import Model, band_for, get_model
from app.services.simulate import SimulationError, simulate

DATA = Path(__file__).resolve().parent.parent / "data"


def load(name: str) -> dict:
    return extract_features_from_bytes((DATA / f"{name}.csv").read_bytes()).features


def tiny_statement(months: int = 4, with_due: bool = True) -> pd.DataFrame:
    rows = []
    for m in range(1, months + 1):
        rows.append((f"2026-{m:02d}-01", "SALARY", 30000, "income", ""))
        rows.append((f"2026-{m:02d}-04", "RENT", -9000, "rent", f"2026-{m:02d}-05" if with_due else ""))
        rows.append((f"2026-{m:02d}-12", "FOOD", -5000, "food", ""))
    return pd.DataFrame(rows, columns=["date", "description", "amount", "category", "due_date"])


class FeatureTests(unittest.TestCase):
    def test_hand_computed_values(self):
        r = extract_features(tiny_statement(4))
        f = r.features
        self.assertEqual(f["income_consistency"], 1.0)        # identical income every month
        self.assertAlmostEqual(f["savings_ratio"], (30000 - 14000) / 30000, places=3)
        self.assertEqual(f["bill_punctuality"], 1.0)          # rent paid before due date
        self.assertAlmostEqual(f["rent_to_income"], 0.3, places=3)
        self.assertEqual(f["emi_burden"], 0.0)
        self.assertEqual(f["spending_volatility"], 0.0)
        self.assertEqual(f["history_months"], 4.0)

    def test_late_payments_lower_punctuality(self):
        df = tiny_statement(4)
        df.loc[df.category == "rent", "date"] = ["2026-01-20", "2026-02-20", "2026-03-04", "2026-04-04"]
        self.assertEqual(extract_features(df).features["bill_punctuality"], 0.5)

    def test_grace_period_counts_as_on_time(self):
        df = tiny_statement(4)
        df.loc[df.category == "rent", "date"] = [f"2026-{m:02d}-07" for m in range(1, 5)]  # 2 days late
        self.assertEqual(extract_features(df).features["bill_punctuality"], 1.0)

    def test_scale_invariance(self):
        """Absolute income must not matter, only ratios (a fairness property)."""
        a = tiny_statement(5)
        b = a.copy()
        b["amount"] = b["amount"] * 3.7
        fa, fb = extract_features(a).features, extract_features(b).features
        for k in FEATURES:
            self.assertAlmostEqual(fa[k], fb[k], places=3, msg=k)

    def test_every_feature_within_bounds(self):
        for name in ["steady_intern", "gig_driver", "stretched_student"]:
            for k, v in load(name).items():
                lo, hi = BOUNDS[k]
                self.assertTrue(lo <= v <= hi, f"{name}.{k}={v}")

    def test_missing_due_date_gives_warning_not_error(self):
        r = extract_features(tiny_statement(4, with_due=False).drop(columns=["due_date"]))
        self.assertTrue(any("neutral" in w for w in r.warnings))

    def test_validation_errors(self):
        with self.assertRaisesRegex(StatementError, "Missing required column"):
            extract_features(pd.DataFrame({"date": ["2026-01-01"], "amount": [1]}))
        with self.assertRaisesRegex(StatementError, "at least 3 months"):
            extract_features(tiny_statement(2))
        no_income = tiny_statement(4)
        no_income["category"] = "food"
        with self.assertRaisesRegex(StatementError, "No income"):
            extract_features(no_income)
        with self.assertRaisesRegex(StatementError, "empty|Could not read"):
            extract_features_from_bytes(b"")
        junk = tiny_statement(4)
        junk["amount"] = "abc"
        with self.assertRaisesRegex(StatementError, "invalid"):
            extract_features(junk)

    def test_day_first_dates_as_exported_by_indian_banks(self):
        df = tiny_statement(4)
        df["date"] = [f"13/{m:02d}/2026" for m in [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]]
        df["due_date"] = ""
        r = extract_features(df)
        self.assertEqual(r.n_months, 4)  # 13/01 .. 13/04 read as Jan..Apr, not rejected as invalid

    def test_a_few_bad_rows_are_ignored_with_warning(self):
        df = tiny_statement(6)
        df.loc[0, "date"] = "not-a-date"
        r = extract_features(df)
        self.assertTrue(any("ignored" in w for w in r.warnings))


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = get_model()

    def test_model_matches_feature_extractor(self):
        self.assertEqual(self.model.features, FEATURES)
        self.assertEqual(set(FEATURE_META), set(FEATURES))

    def test_all_coefficients_have_expected_sign(self):
        for f, c in zip(self.model.features, self.model.coef):
            self.assertTrue(c == 0 or np.sign(c) == EXPECTED_SIGN[f], f"{f} has wrong sign: {c}")

    def test_deterministic(self):
        f = load("gig_driver")
        self.assertEqual(self.model.score(f), self.model.score(dict(f)))

    def test_personas_rank_sensibly(self):
        a, b, c = (self.model.score(load(n)) for n in ["steady_intern", "gig_driver", "stretched_student"])
        self.assertGreater(a, b)
        self.assertGreater(b, c)
        self.assertEqual(band_for(a), "Excellent")
        self.assertEqual(band_for(c), "Poor")

    def test_score_always_in_range(self):
        rng = np.random.default_rng(0)
        for _ in range(300):
            f = {k: rng.uniform(*BOUNDS[k]) for k in FEATURES}
            self.assertTrue(300 <= self.model.score(f) <= 900)

    def test_band_edges(self):
        self.assertEqual([band_for(s) for s in (300, 499, 500, 649, 650, 749, 750, 900)],
                         ["Poor", "Poor", "Fair", "Fair", "Good", "Good", "Excellent", "Excellent"])

    def test_missing_feature_rejected(self):
        with self.assertRaises(ValueError):
            self.model.score({"savings_ratio": 0.1})

    def test_stale_model_rejected(self):
        bad = dict(self.model.bundle, features=FEATURES[:-1])
        with self.assertRaises(ValueError):
            Model(bad)


class ExplanationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = get_model()

    def test_contributions_add_up_exactly(self):
        for name in ["steady_intern", "gig_driver", "stretched_student"]:
            f = load(name)
            total = self.model.baseline_score() + sum(contributions_raw(self.model, f).values())
            self.assertAlmostEqual(total, self.model.score_unclipped(f), places=6)

    def test_factor_direction_matches_points(self):
        r = build_result(self.model, load("stretched_student"))
        for fac in r["factors"]:
            if fac["direction"] == "raises":
                self.assertGreaterEqual(fac["points"], 1)
            if fac["direction"] == "lowers":
                self.assertLessEqual(fac["points"], -1)
        pts = [abs(x["points"]) for x in r["factors"]]
        self.assertEqual(pts, sorted(pts, reverse=True))

    def test_tip_gains_are_real(self):
        """Applying a tip's target and re-scoring must give (about) the promised gain."""
        f = load("stretched_student")
        base = self.model.score_unclipped(f)
        for t in tips(self.model, f):
            gained = self.model.score_unclipped({**f, t["feature"]: t["target_value"]}) - base
            self.assertAlmostEqual(gained, t["estimated_gain"], delta=0.51)
            self.assertGreater(t["estimated_gain"], 0)

    def test_no_tips_for_a_perfect_applicant(self):
        best = {"income_consistency": 1, "savings_ratio": 0.5, "bill_punctuality": 1,
                "rent_to_income": 0.1, "emi_burden": 0, "spending_volatility": 0, "history_months": 12}
        self.assertEqual(tips(self.model, best), [])

    def test_negative_savings_wording(self):
        f = dict(load("steady_intern"), savings_ratio=-0.2)
        reason = next(x["reason"] for x in build_result(self.model, f)["factors"] if x["feature"] == "savings_ratio")
        self.assertIn("spent more than you earned", reason)

    def test_result_has_disclaimer_and_all_fields(self):
        r = build_result(self.model, load("gig_driver"), ["w"])
        for key in ["score", "band", "factors", "tips", "features", "warnings", "disclaimer", "model_version"]:
            self.assertIn(key, r)
        self.assertIn("not a real credit score", r["disclaimer"])
        self.assertEqual(r["warnings"], ["w"])


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = get_model()

    def test_improving_a_good_behaviour_never_lowers_score(self):
        f = load("stretched_student")
        for name in FEATURES:
            lo, hi = BOUNDS[name]
            better = hi if self.model.higher_is_better(name) else lo
            if name == "history_months":
                better = 12
            r = simulate(self.model, f, {name: better})
            self.assertGreaterEqual(r["delta"], 0, name)

    def test_what_if_matches_direct_scoring_and_does_not_mutate(self):
        f = load("gig_driver")
        before = dict(f)
        r = simulate(self.model, f, {"bill_punctuality": 1.0})
        self.assertEqual(r["new_score"], self.model.score({**f, "bill_punctuality": 1.0}))
        self.assertEqual(r["delta"], r["new_score"] - r["original_score"])
        self.assertEqual(f, before)

    def test_values_are_clipped_to_bounds(self):
        r = simulate(self.model, load("gig_driver"), {"bill_punctuality": 7})
        self.assertEqual(r["features"]["bill_punctuality"], 1.0)

    def test_bad_input_rejected(self):
        f = load("gig_driver")
        for bad in [{}, {"nope": 1}, {"bill_punctuality": "abc"}, {"bill_punctuality": float("nan")},
                    {"bill_punctuality": float("inf")}, {"bill_punctuality": None}]:
            with self.assertRaises(SimulationError, msg=str(bad)):
                simulate(self.model, f, bad)


class SecurityTests(unittest.TestCase):
    def test_password_hash_roundtrip(self):
        h = security.hash_password("correct horse")
        self.assertTrue(security.verify_password("correct horse", h))
        self.assertFalse(security.verify_password("wrong", h))
        self.assertNotEqual(h, security.hash_password("correct horse"))  # salted
        self.assertNotIn("correct horse", h)

    def test_malformed_hash_is_rejected_not_crashed(self):
        for stored in ["", "garbage", "a$b$c$d", "pbkdf2_sha256$x$zz$zz"]:
            self.assertFalse(security.verify_password("pw", stored))

    def test_token_roundtrip_and_failures(self):
        tok = security.create_token(42, "secret", 5)
        self.assertEqual(security.decode_token(tok, "secret"), 42)
        with self.assertRaises(security.AuthError):
            security.decode_token(tok, "other-secret")
        with self.assertRaises(security.AuthError):
            security.decode_token(security.create_token(42, "secret", -1), "secret")  # expired
        with self.assertRaises(security.AuthError):
            security.decode_token(tok[:-3] + "abc", "secret")  # tampered
        with self.assertRaises(security.AuthError):
            security.decode_token("not.a.token", "secret")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db.init_db(self.path)
        self.result = build_result(get_model(), load("gig_driver"))

    def tearDown(self):
        os.remove(self.path)

    def test_user_lifecycle(self):
        uid = db.create_user(self.path, "a@x.com", "hash")
        self.assertEqual(db.get_user_by_email(self.path, "a@x.com")["id"], uid)
        self.assertEqual(db.get_user(self.path, uid)["email"], "a@x.com")
        self.assertIsNone(db.get_user_by_email(self.path, "nobody@x.com"))
        with self.assertRaises(db.DuplicateEmail):
            db.create_user(self.path, "a@x.com", "hash2")

    def test_scores_are_saved_listed_and_isolated_per_user(self):
        u1, u2 = db.create_user(self.path, "a@x.com", "h"), db.create_user(self.path, "b@x.com", "h")
        s1, _ = db.save_score(self.path, u1, self.result, True)
        s2, _ = db.save_score(self.path, u1, self.result, True)
        self.assertEqual([r["id"] for r in db.list_scores(self.path, u1)], [s2, s1])  # newest first
        self.assertEqual(db.list_scores(self.path, u2), [])
        self.assertIsNone(db.get_score(self.path, u2, s1))  # another user's score is invisible
        row = db.get_score(self.path, u1, s1)
        self.assertEqual(row["features"], self.result["features"])
        self.assertEqual(row["result"]["score"], self.result["score"])

    def test_raw_statement_columns_are_not_stored(self):
        import sqlite3
        conn = sqlite3.connect(self.path)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(scores)")]
        finally:
            conn.close()  # Windows cannot delete a database file that is still open
        self.assertNotIn("raw_csv", cols)
        self.assertNotIn("statement", cols)

    def test_delete_data_and_account(self):
        u = db.create_user(self.path, "a@x.com", "h")
        other = db.create_user(self.path, "b@x.com", "h")
        db.save_score(self.path, u, self.result, True)
        db.save_score(self.path, u, self.result, True)
        db.save_score(self.path, other, self.result, True)
        self.assertEqual(db.delete_user_data(self.path, u), 2)
        self.assertEqual(db.list_scores(self.path, u), [])
        self.assertIsNotNone(db.get_user(self.path, u))          # account kept
        self.assertEqual(len(db.list_scores(self.path, other)), 1)  # other user untouched
        db.delete_user_data(self.path, u, delete_account=True)
        self.assertIsNone(db.get_user(self.path, u))


class EndToEndCoreTest(unittest.TestCase):
    def test_csv_bytes_to_stored_result_to_simulation(self):
        """Mirrors what POST /score then POST /simulate do, minus HTTP."""
        model = get_model()
        fr = extract_features_from_bytes((DATA / "stretched_student.csv").read_bytes())
        result = build_result(model, fr.features, fr.warnings)
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            db.init_db(path)
            uid = db.create_user(path, "demo@x.com", "h")
            sid, _ = db.save_score(path, uid, result, True)
            stored = db.get_score(path, uid, sid)
            sim = simulate(model, stored["features"], {"bill_punctuality": 1.0, "savings_ratio": 0.2})
            self.assertGreater(sim["new_score"], result["score"])
            self.assertEqual(sim["original_score"], result["score"])
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
