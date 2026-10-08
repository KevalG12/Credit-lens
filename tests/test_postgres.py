"""Runs the data-layer contract against PostgreSQL (e.g. a Neon branch).
Skipped unless CREDITLENS_TEST_PG_URL is set. WARNING: it drops the users/scores tables in that database,
so point it at a scratch database, never at real data."""
import os
import unittest

from app import db

URL = os.getenv("CREDITLENS_TEST_PG_URL")
RESULT = {"score": 700, "band": "Good", "features": {"savings_ratio": 0.2}}


@unittest.skipUnless(URL, "set CREDITLENS_TEST_PG_URL to run PostgreSQL tests")
class PostgresTests(unittest.TestCase):
    def setUp(self):
        with db.connect(URL) as c:
            c.execute("DROP TABLE IF EXISTS scores")
            c.execute("DROP TABLE IF EXISTS users")
        db.init_db(URL)
        db.init_db(URL)  # idempotent

    def test_users_and_duplicates(self):
        uid = db.create_user(URL, "a@x.com", "hash")
        self.assertIsInstance(uid, int)
        self.assertEqual(db.get_user_by_email(URL, "a@x.com")["id"], uid)
        self.assertEqual(db.get_user(URL, uid)["email"], "a@x.com")
        self.assertIsNone(db.get_user_by_email(URL, "nobody@x.com"))
        with self.assertRaises(db.DuplicateEmail):
            db.create_user(URL, "a@x.com", "hash2")
        self.assertIsNotNone(db.get_user_by_email(URL, "a@x.com"))   # connection still healthy afterwards

    def test_scores_isolated_per_user_and_newest_first(self):
        u1, u2 = db.create_user(URL, "a@x.com", "h"), db.create_user(URL, "b@x.com", "h")
        s1, _ = db.save_score(URL, u1, RESULT, True)
        s2, _ = db.save_score(URL, u1, RESULT, True)
        self.assertEqual([r["id"] for r in db.list_scores(URL, u1)], [s2, s1])
        self.assertEqual(db.list_scores(URL, u2), [])
        self.assertIsNone(db.get_score(URL, u2, s1))
        self.assertEqual(db.get_score(URL, u1, s1)["features"], {"savings_ratio": 0.2})

    def test_delete_and_cascade(self):
        u = db.create_user(URL, "a@x.com", "h")
        db.save_score(URL, u, RESULT, True)
        self.assertEqual(db.delete_user_data(URL, u), 1)
        self.assertIsNotNone(db.get_user(URL, u))
        db.save_score(URL, u, RESULT, True)
        db.delete_user_data(URL, u, delete_account=True)
        self.assertIsNone(db.get_user(URL, u))

    def test_purge_old_guests(self):
        g = db.create_user(URL, "guest-1" + db.GUEST_DOMAIN, "h")
        db.save_score(URL, g, RESULT, True)
        keep = db.create_user(URL, "real@x.com", "h")
        self.assertEqual(db.purge_old_guests(URL, max_age_hours=24), 0)     # too new
        self.assertEqual(db.purge_old_guests(URL, max_age_hours=-1), 1)     # everything counts as old
        self.assertIsNone(db.get_user(URL, g))
        self.assertIsNotNone(db.get_user(URL, keep))


if __name__ == "__main__":
    unittest.main()
