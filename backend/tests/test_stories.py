import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta
import numpy as np
import pytest


def _load_sqlite_vec(dbapi_conn):
    """Load the sqlite-vec extension into a raw DBAPI sqlite3 connection.

    Python 3.14 (and some other builds) omit enable_load_extension() from the
    sqlite3.Connection class for security reasons.  When the attribute is absent
    we fall back to calling the underlying C-level functions via ctypes so that
    the test suite still works without any third-party SQLite wrapper.
    """
    if hasattr(dbapi_conn, "enable_load_extension"):
        # Standard path (Python ≤ 3.13 or builds that expose the method).
        dbapi_conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)
        return

    # Fallback: Python 3.14+ path — use ctypes to call the C-level SQLite API.
    import ctypes, importlib.util, sqlite_vec as _sv

    _sqlite3_path = importlib.util.find_spec("_sqlite3").origin
    lib = ctypes.CDLL(_sqlite3_path)
    lib.sqlite3_enable_load_extension.restype = ctypes.c_int
    lib.sqlite3_enable_load_extension.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.sqlite3_load_extension.restype = ctypes.c_int
    lib.sqlite3_load_extension.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_char_p),
    ]

    # The first pointer-sized word after PyObject_HEAD in pysqlite_Connection
    # is the sqlite3* db handle.
    ptr = id(dbapi_conn)
    db_ptr = ctypes.cast(ptr + 16, ctypes.POINTER(ctypes.c_void_p)).contents.value

    lib.sqlite3_enable_load_extension(ctypes.c_void_p(db_ptr), 1)
    ext_path = _sv.loadable_path().encode()
    errmsg = ctypes.c_char_p(None)
    rc = lib.sqlite3_load_extension(
        ctypes.c_void_p(db_ptr), ext_path, None, ctypes.byref(errmsg)
    )
    lib.sqlite3_enable_load_extension(ctypes.c_void_p(db_ptr), 0)
    if rc != 0:
        raise RuntimeError(f"sqlite-vec load failed: {errmsg.value}")


def _engine_with_vec():
    """In-memory engine with sqlite-vec loaded and all tables created."""
    import sqlite_vec
    from sqlalchemy import create_engine, event
    from radar.models import Base
    from radar import vec

    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _load(dbapi_conn, _rec):
        _load_sqlite_vec(dbapi_conn)

    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        vec.create_vec_tables(conn)
    return eng


def _session():
    from sqlalchemy.orm import Session as _S
    return _S(_engine_with_vec())


def test_store_and_knn_roundtrip():
    from radar import vec
    s = _session()
    conn = s.connection().connection  # raw DBAPI conn
    a = np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32)
    b = np.array([0.0, 1.0] + [0.0] * 382, dtype=np.float32)
    vec.store(conn, "incident_vec", 1, a)
    vec.store(conn, "incident_vec", 2, b)
    hits = vec.knn(conn, "incident_vec", a, k=2)
    assert hits[0][0] == 1            # nearest id is the identical vector
    assert hits[0][1] == pytest.approx(0.0, abs=1e-4)  # cosine distance ~0
