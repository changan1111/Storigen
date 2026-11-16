"""Schema versions: an old database upgrades in place and keeps its data; a newer database is refused with a clear message."""
import pathlib, sqlite3, sys
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root))
import pytest
from autoid_lite import db as dbm

def cols(path, table):
    c = sqlite3.connect(str(path)); r = {x[1] for x in c.execute("PRAGMA table_info(%s)" % table)}; c.close(); return r

def old_db(path, have_extra=()):
    """A database as an old version (before schema versions) left it: base tables only, user_version 0, one clip with data."""
    c = sqlite3.connect(str(path)); c.executescript(dbm.SCHEMA)
    for t, col, typ in have_extra: c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (t, col, typ))
    c.execute("INSERT INTO rundowns(id, blaze_rundown_id, name, air_date) VALUES(1,'R1','News','2026-11-13')")
    c.execute("INSERT INTO stories(id, blaze_story_id, rundown_id, slug) VALUES(1,'724921',1,'SLUG')")
    c.execute("INSERT INTO clip_ids(id, display_id, day, seq, story_id, state) VALUES(1,'D1','20261113',1,1,'ATTACHED')")
    c.commit(); c.close()

def test_every_declared_column_exists_after_open(tmp_path):
    d = dbm.DB(tmp_path / "a.db")
    for _v, table, col, _t, _why in dbm.COLUMNS: assert col in cols(tmp_path / "a.db", table), (table, col)
    assert d.conn.execute("PRAGMA user_version").fetchone()["user_version"] == dbm.SCHEMA_VERSION

def test_old_database_is_upgraded_and_data_kept(tmp_path):
    p = tmp_path / "old.db"; old_db(p)
    d = dbm.DB(p)
    row = d.conn.execute("SELECT display_id, state, qa_state, media_id, name_id FROM clip_ids").fetchone()
    assert row == {"display_id": "D1", "state": "ATTACHED", "qa_state": None, "media_id": None, "name_id": None}
    assert d.conn.execute("SELECT slug, story_title FROM stories").fetchone() == {"slug": "SLUG", "story_title": None}

def test_partly_upgraded_database_does_not_fail_on_existing_columns(tmp_path):
    p = tmp_path / "mid.db"; old_db(p, have_extra=[("clip_ids", "media_id", "TEXT"), ("clip_ids", "media_found_at", "TEXT"), ("stories", "slug_id", "TEXT")])   # e.g. an install from 9.7
    d = dbm.DB(p); assert "qa_msg" in cols(p, "clip_ids") and "item_id" in cols(p, "clip_ids")

def test_reopen_is_a_noop_and_keeps_version(tmp_path):
    p = tmp_path / "r.db"; dbm.DB(p).conn.close(); d = dbm.DB(p)
    assert d.conn.execute("PRAGMA user_version").fetchone()["user_version"] == dbm.SCHEMA_VERSION

def test_database_from_a_newer_program_is_refused(tmp_path):
    p = tmp_path / "new.db"; dbm.DB(p).conn.close()
    c = sqlite3.connect(str(p)); c.execute("PRAGMA user_version = %d" % (dbm.SCHEMA_VERSION + 1)); c.commit(); c.close()
    with pytest.raises(RuntimeError, match="newer version"): dbm.DB(p)

def test_column_list_is_append_only_by_version():
    vs = [v for v, *_ in dbm.COLUMNS]; assert vs == sorted(vs) and len(set((t, c) for _v, t, c, *_ in dbm.COLUMNS)) == len(dbm.COLUMNS)


def test_9134_a_database_stamped_current_but_missing_columns_is_repaired(tmp_path):
    p = tmp_path / "s.db"; old_db(p)
    c = sqlite3.connect(str(p)); c.execute("PRAGMA user_version = %d" % dbm.SCHEMA_VERSION); c.commit(); c.close()
    d = dbm.DB(p)
    for v, t, col, typ, _ in dbm.COLUMNS: assert col in cols(p, t)
    assert d.conn.execute("SELECT display_id FROM clip_ids").fetchone()["display_id"] == "D1"
