import sys, os, sqlite3, importlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _legacy_db(path):
    """A pre-news-mode schema: brand_id NOT NULL, no topic_id yet."""
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE mentions ("
        "id INTEGER PRIMARY KEY, brand_id INTEGER NOT NULL, "
        "platform TEXT, post_id TEXT, "
        "FOREIGN KEY(brand_id) REFERENCES brands (id))"
    )
    con.execute(
        "CREATE TABLE stories ("
        "id INTEGER PRIMARY KEY, brand_id INTEGER NOT NULL, title TEXT)"
    )
    con.commit(); con.close()


def test_relax_brand_id_not_null_allows_topic_only_rows(monkeypatch, tmp_path):
    dbfile = tmp_path / "legacy.db"
    _legacy_db(str(dbfile))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dbfile}")
    import radar.core.db as db; importlib.reload(db)

    db._relax_brand_id_not_null()

    con = sqlite3.connect(str(dbfile))
    con.execute("INSERT INTO mentions (brand_id, platform, post_id) VALUES (NULL, 'web', 'x')")
    con.execute("INSERT INTO stories (brand_id, title) VALUES (NULL, 'тема')")
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM mentions WHERE brand_id IS NULL").fetchone()[0] == 1
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()


def test_relax_brand_id_not_null_is_idempotent(monkeypatch, tmp_path):
    dbfile = tmp_path / "legacy2.db"
    _legacy_db(str(dbfile))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dbfile}")
    import radar.core.db as db; importlib.reload(db)

    db._relax_brand_id_not_null()
    db._relax_brand_id_not_null()  # second run must be a no-op, not a failure

    con = sqlite3.connect(str(dbfile))
    con.execute("INSERT INTO mentions (brand_id, platform, post_id) VALUES (NULL, 'web', 'y')")
    con.commit()
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()
