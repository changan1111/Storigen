"""SQLite storage. One connection guarded by a lock; every write runs inside BEGIN IMMEDIATE ... COMMIT (all or nothing)."""
from __future__ import annotations
import contextlib, sqlite3, threading, time

SCHEMA = """
CREATE TABLE IF NOT EXISTS rundowns(id INTEGER PRIMARY KEY, blaze_rundown_id TEXT UNIQUE NOT NULL, name TEXT, air_date TEXT);
CREATE TABLE IF NOT EXISTS stories(id INTEGER PRIMARY KEY, blaze_story_id TEXT NOT NULL, rundown_id INTEGER NOT NULL REFERENCES rundowns(id),
  slug TEXT, last_seen_at TEXT, deleted INTEGER NOT NULL DEFAULT 0, deleted_at TEXT, deleted_reason TEXT, UNIQUE(rundown_id, blaze_story_id));
CREATE TABLE IF NOT EXISTS counters(day TEXT PRIMARY KEY, last INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS clip_old_names(clip_id INTEGER NOT NULL, name TEXT NOT NULL, changed_at TEXT, PRIMARY KEY(clip_id, name));      -- v10.9.1: the clip names a story had before it was renamed in Blaze (only to tell the editor who still uses one)
CREATE TABLE IF NOT EXISTS clip_ids(id INTEGER PRIMARY KEY, display_id TEXT UNIQUE NOT NULL, day TEXT NOT NULL, seq INTEGER NOT NULL,
  story_id INTEGER NOT NULL REFERENCES stories(id), version INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL DEFAULT 'WAITING_FOR_CLIP',
  created_at TEXT, verified_at TEXT, on_nitro_at TEXT, attached_at TEXT, attach_method TEXT, attach_error TEXT, name_id TEXT, UNIQUE(day, seq, version));
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, clip_id INTEGER NOT NULL REFERENCES clip_ids(id), nas_path TEXT, nitro_path TEXT,
  size INTEGER, sha256 TEXT, state TEXT, error TEXT, duration_s REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, time TEXT NOT NULL, actor TEXT, action TEXT, details TEXT);
CREATE TABLE IF NOT EXISTS heartbeats(component TEXT PRIMARY KEY, ts REAL NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, full_name TEXT, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  valid_upto TEXT, pw_salt TEXT NOT NULL, pw_hash TEXT NOT NULL, created_at TEXT);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
"""

# ---- schema versions ---------------------------------------------------------------------------------------
# New columns, in the order they were introduced. APPEND ONLY: never edit, reorder or delete an entry.
# (schema version, table, column, SQL type, what it is for)
COLUMNS = [
    (1, "stories",  "slug_id",        "TEXT",    "Blaze slug ID: kept for later, not used by the attach"),
    (1, "stories",  "position",       "INTEGER", "rundown position: kept for later, not used by the attach"),
    (2, "stories",  "story_title",    "TEXT",    "v9.5: the story's own name in Blaze (the slug title is the row's label)"),
    (2, "rundowns", "start_at",       "TEXT",    "v9.5: bulletin (show) start time"),
    (3, "clip_ids", "name_id",        "TEXT",    "v9.7.1: the shared clip name DDMMYY_STORY_NAME[_Vn]; display_id stays the unique internal ID"),
    (4, "clip_ids", "media_id",       "TEXT",    "v9.7.5: Blaze's media object (mosObjectId) found for this clip = the NITRO stage"),
    (4, "clip_ids", "media_found_at", "TEXT",    "v9.7.5: when it was found"),
    (5, "clip_ids", "item_id",        "TEXT",    "v9.8: the story item the attached clip sits on"),
    (5, "clip_ids", "attach_dur",     "INTEGER", "v9.8: the clip length in the story, whole seconds"),
    (5, "clip_ids", "blaze_clip_id",  "TEXT",    "v9.8: Blaze's own clip id"),
    (6, "clip_ids", "qa_state",       "TEXT",    "v9.13 Quick test attach: REQUESTED -> SENT / BLOCKED / FAILED"),
    (6, "clip_ids", "qa_by",          "TEXT",    "v9.13: who asked"),
    (6, "clip_ids", "qa_at",          "TEXT",    "v9.13: when"),
    (6, "clip_ids", "qa_msg",         "TEXT",    "v9.13: the poller's answer"),
    (7, "stories",  "online_script",  "TEXT",    "v9.13.2: the story's first script field from Blaze (storyComplete versions[0].items[].text1): reporter / place / on-screen lines"),
    (7, "stories",  "anchor_script",  "TEXT",    "v9.13.2: the story's second script field from Blaze (text2): the anchor's read / intro"),
    (7, "stories",  "script_at",      "TEXT",    "v9.13.2: when this script text was last stored (first read, or the time it last changed in Blaze)"),
    (8, "clip_ids", "media_name",     "TEXT",    "v10.2.0: the file's title in Blaze's media list (shown in the Ready feed)"),
    (9, "clip_ids", "replaced_at",    "TEXT",    "v10.7.0: when an update (_Un) took this clip's place in the story (the Blaze clip was removed after a verified read-back)"),
    (9, "clip_ids", "replaced_by",    "TEXT",    "v10.7.0: the display_id of the update that replaced this clip"),
    (10, "stories", "created_by",     "TEXT",    "v10.9.0: Blaze username of the story's creator (storyComplete, by user id)"),
    (10, "stories", "created_by_id",  "TEXT",    "v10.9.0: Blaze user number of the creator"),
    (10, "stories", "assigned_to",    "TEXT",    "v10.9.0: Blaze username the story is assigned to"),
    (10, "stories", "assigned_to_id", "TEXT",    "v10.9.0: Blaze user number it is assigned to"),
    (11, "stories", "editor",         "TEXT",    "v10.9.5: the video editor's name: the text of the slug's comment in Blaze (the editors write their name there)"),
    (12, "stories", "script_items",  "TEXT",    "v10.9.7: the story's script item by item (JSON list of {n, online, anchor}): the middle pane shows every Online / Anchor text in its own box"),
]
SCHEMA_VERSION = max(v for v, *_ in COLUMNS)

def now_iso(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

class Cur:
    """Tiny helper over the connection: rows come back as dicts."""
    def __init__(self, conn): self.c = conn
    def q(self, sql, a=()): return self.c.execute(sql, tuple(a)).fetchall()
    def one(self, sql, a=()): return self.c.execute(sql, tuple(a)).fetchone()
    def x(self, sql, a=()): return self.c.execute(sql, tuple(a)).rowcount
    def insert(self, sql, a=()): return self.c.execute(sql, tuple(a)).lastrowid

class DB:
    def __init__(self, path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.row_factory = lambda cur, row: {d[0]: row[i] for i, d in enumerate(cur.description)}
        self.conn.execute("PRAGMA journal_mode=WAL"); self.conn.execute("PRAGMA foreign_keys=ON")
        self.lock = threading.RLock(); self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_name ON clip_ids(UPPER(COALESCE(name_id, display_id)))")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_old_name ON clip_old_names(name)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON events(time)")      # v10.9.5: the Recent activity tab asks for the last 1 / 2 / 4 hours

    def _migrate(self):
        """Bring an older database up to SCHEMA_VERSION (stored in PRAGMA user_version). A column that is already there is skipped, so a database made before versions existed (user_version 0) upgrades the same way, and its data is kept."""
        cur = self.conn.execute("PRAGMA user_version").fetchone()["user_version"]
        if cur > SCHEMA_VERSION:
            raise RuntimeError("this database is schema %d but this program only knows up to %d: it was made by a newer version. Update the program, or restore a backup from data/backups." % (cur, SCHEMA_VERSION))
        have = {}      # v9.13.3: always check every column, whatever user_version says (a database stamped with the right version but missing columns gave 500 on /api/clips)
        for v, table, col, typ, _why in COLUMNS:
            if table not in have: have[table] = {r["name"] for r in self.conn.execute("PRAGMA table_info(%s)" % table).fetchall()}
            if col not in have[table]: self.conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
        if cur != SCHEMA_VERSION: self.conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)

    @contextlib.contextmanager
    def tx(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try: yield Cur(self.conn)
            except BaseException:
                self.conn.execute("ROLLBACK"); raise
            else: self.conn.execute("COMMIT")

    def backup(self, dest):
        """Consistent copy of the live database (safe while the server is running)."""
        with self.lock:
            out = sqlite3.connect(str(dest))
            try: self.conn.backup(out)
            finally: out.close()
