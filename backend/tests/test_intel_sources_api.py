"""Tests for the /intel/sources management API."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_sources_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'src_noauth.db'}")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from radar.intel.api import router
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    assert c.get("/intel/sources").status_code in (401, 403)


def test_sources_list_add_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'src_full.db'}")
    from fastapi.testclient import TestClient
    from radar.app import app

    with TestClient(app) as c:
        # --- Auth setup ---
        c.post("/auth/register", json={"email": "src@test.local", "password": "secret123"})
        tok = c.post(
            "/auth/login", json={"email": "src@test.local", "password": "secret123"}
        ).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}

        # 1. GET /intel/sources → 200, is a list (seeded 94 handles)
        r = c.get("/intel/sources", headers=h)
        assert r.status_code == 200
        initial = r.json()
        assert isinstance(initial, list)
        assert len(initial) >= 1  # at least some seeds loaded

        # 2. POST new source → created=True
        new_src = {"link": "@newchan_test_xyz", "side": "ru", "kind": "channel"}
        r = c.post("/intel/sources", json=new_src, headers=h)
        assert r.status_code == 200
        created = r.json()
        assert created["created"] is True
        assert created["handle"] == "@newchan_test_xyz"
        assert created["side"] == "ru"
        assert created["kind"] == "channel"
        new_id = created["id"]

        # 3. GET again shows it
        r = c.get("/intel/sources", headers=h)
        assert r.status_code == 200
        handles = [s["handle"] for s in r.json()]
        assert "@newchan_test_xyz" in handles

        # 4. POST same link again → idempotent, created=False
        r = c.post("/intel/sources", json=new_src, headers=h)
        assert r.status_code == 200
        dup = r.json()
        assert dup["created"] is False
        assert dup["id"] == new_id

        # 5. POST with invalid side → 400
        r = c.post(
            "/intel/sources",
            json={"link": "@x", "side": "zz", "kind": "channel"},
            headers=h,
        )
        assert r.status_code == 400

        # 6. POST with invalid kind → 400
        r = c.post(
            "/intel/sources",
            json={"link": "@y", "side": "ru", "kind": "bogus"},
            headers=h,
        )
        assert r.status_code == 400

        # 7. DELETE by id → 200 deleted=True
        r = c.delete(f"/intel/sources/{new_id}", headers=h)
        assert r.status_code == 200
        assert r.json()["deleted"] is True

        # 8. GET no longer lists it
        r = c.get("/intel/sources", headers=h)
        assert r.status_code == 200
        handles_after = [s["handle"] for s in r.json()]
        assert "@newchan_test_xyz" not in handles_after

        # 9. DELETE non-existent → 404
        r = c.delete(f"/intel/sources/{new_id}", headers=h)
        assert r.status_code == 404
