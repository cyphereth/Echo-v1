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
