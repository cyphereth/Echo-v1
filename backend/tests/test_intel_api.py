import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_intel_router_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path/'i.db'}")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from radar.intel.api import router
    app = FastAPI(); app.include_router(router)
    c = TestClient(app)
    assert c.get("/intel/overview").status_code in (401, 403)
    assert c.get("/intel/directions").status_code in (401, 403)


def test_intel_overview_authed_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path/'i2.db'}")
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as c:
        c.post("/auth/register", json={"email": "intel@test.local", "password": "secret123"})
        tok = c.post("/auth/login", json={"email": "intel@test.local", "password": "secret123"}).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        ov = c.get("/intel/overview", headers=h)
        assert ov.status_code == 200
        assert set(ov.json().keys()) == {"kpis", "hot", "alerts", "top_stories"}
        dirs = c.get("/intel/directions", headers=h)
        assert dirs.status_code == 200 and isinstance(dirs.json(), list) and len(dirs.json()) >= 1
