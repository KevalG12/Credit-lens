"""HTTP-level tests (FastAPI TestClient). Needs: pip install -r requirements-dev.txt"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ["CREDITLENS_DB"] = tempfile.mktemp(suffix=".db")
os.environ["CREDITLENS_JWT_SECRET"] = "t" * 40
os.environ["CREDITLENS_AUTH_RATE"] = "0"          # limiter has its own test below

from fastapi.testclient import TestClient  # noqa: E402

from app import deps  # noqa: E402
from app.main import app  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


def upload(c, headers, name="steady_intern", consent="true"):
    return c.post("/score", headers=headers, data={"consent": consent},
                  files={"file": (f"{name}.csv", (DATA / f"{name}.csv").read_bytes(), "text/csv")})


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.c = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def auth(self, email):
        r = self.c.post("/auth/register", json={"email": email, "password": "Passw0rd!x"})
        self.assertEqual(r.status_code, 201)
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def test_meta_endpoints_public(self):
        self.assertEqual(self.c.get("/health").json()["status"], "ok")
        self.assertEqual(len(self.c.get("/features").json()), 7)
        self.assertIn("disclaimer", self.c.get("/model-info").json())

    def test_auth_flow(self):
        self.auth("flow@x.io")
        self.assertEqual(self.c.post("/auth/register", json={"email": "FLOW@x.io", "password": "Passw0rd!x"}).status_code, 409)
        self.assertEqual(self.c.post("/auth/login", json={"email": "flow@x.io", "password": "wrong-pass"}).status_code, 401)
        tok = self.c.post("/auth/login", json={"email": "flow@x.io", "password": "Passw0rd!x"}).json()["access_token"]
        me = self.c.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
        self.assertEqual(me.json()["email"], "flow@x.io")
        self.assertEqual(self.c.post("/auth/register", json={"email": "bad", "password": "Passw0rd!x"}).status_code, 422)

    def test_password_rules_on_register(self):
        for bad in ["Sh0rt!a", "alllowercase1!", "ALLUPPERCASE1!", "NoNumbers!!", "NoSpecial123"]:
            r = self.c.post("/auth/register", json={"email": "pw@x.io", "password": bad})
            self.assertEqual(r.status_code, 422, bad)
        self.assertEqual(self.c.post("/auth/register", json={"email": "pw@x.io", "password": "Good#Pass1"}).status_code, 201)

    def test_protected_routes_need_token(self):
        for method, path in [("get", "/scores"), ("get", "/scores/1"), ("delete", "/data"), ("get", "/auth/me")]:
            self.assertEqual(getattr(self.c, method)(path).status_code, 401, path)

    def test_score_requires_consent_and_valid_csv(self):
        h = self.auth("consent@x.io")
        self.assertEqual(upload(self.c, h, consent="false").status_code, 400)
        r = self.c.post("/score", headers=h, data={"consent": "true"},
                        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
        self.assertEqual(r.status_code, 422)

    def test_score_history_simulate_and_isolation(self):
        h = self.auth("owner@x.io")
        r = upload(self.c, h, "steady_intern")
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertTrue(300 <= body["score"] <= 900)
        total = body["baseline_score"] + sum(f["points"] for f in body["factors"])
        self.assertAlmostEqual(total, body["score"], delta=2)
        self.assertEqual(self.c.get(f"/scores/{body['id']}", headers=h).json()["score"], body["score"])
        self.assertEqual(len(self.c.get("/scores", headers=h).json()), 1)

        sim = self.c.post("/simulate", headers=h, json={"score_id": body["id"], "overrides": {"savings_ratio": 0.0}})
        self.assertEqual(sim.status_code, 200)
        self.assertLess(sim.json()["delta"], 0)
        self.assertEqual(self.c.post("/simulate", headers=h, json={"score_id": body["id"], "overrides": {"nope": 1}}).status_code, 422)

        other = self.auth("other@x.io")                       # another user cannot see it
        self.assertEqual(self.c.get(f"/scores/{body['id']}", headers=other).status_code, 404)
        self.assertEqual(self.c.post("/simulate", headers=other, json={"score_id": body["id"], "overrides": {"savings_ratio": 0.1}}).status_code, 404)

    def test_delete_data_and_account(self):
        h = self.auth("gone@x.io")
        upload(self.c, h)
        r = self.c.delete("/data", headers=h)
        self.assertEqual(r.json(), {"deleted_scores": 1, "account_deleted": False})
        self.assertEqual(self.c.get("/scores", headers=h).json(), [])
        self.c.delete("/data?delete_account=true", headers=h)
        self.assertEqual(self.c.get("/scores", headers=h).status_code, 401)

    def test_auth_rate_limit(self):
        os.environ["CREDITLENS_AUTH_RATE"] = "3"
        deps._attempts.clear()
        try:
            codes = [self.c.post("/auth/login", json={"email": "z@x.io", "password": "Passw0rd!x"}).status_code
                     for _ in range(5)]
            self.assertEqual(codes, [401, 401, 401, 429, 429])
        finally:
            os.environ["CREDITLENS_AUTH_RATE"] = "0"
            deps._attempts.clear()


if __name__ == "__main__":
    unittest.main()
