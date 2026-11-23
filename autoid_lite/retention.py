"""v10.9.4: keep only the last AUTOID_KEEP_DAYS broadcast days (default 7, today included; 0 = keep everything) in autoid.db.
Once a day (AUTOID_PURGE_AT, default 03:30) and on request (an admin's "Clean up now") everything older goes: files, clip IDs, clip history names, stories with their script text, empty bulletins, day counters and the event log.
Small batches, each its own short transaction, so the dashboard and the poller never wait long. A copy of the database is made first (the newest 3 are kept in data/backups); afterwards the file is compacted when enough of it is free."""
from __future__ import annotations
import datetime as dt, json, os, sys, threading, time, traceback
from pathlib import Path
from .db import now_iso
from .common import HttpError

BATCH = 500
EVENTS_BATCH = 5000
EVENTS_NO_DELETE = "CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events is append-only'); END"      # the same as db.SCHEMA: put back after every batch
BACKUPS_KEPT = 3

def mb(n): return round((n or 0) / 1048576, 2)

class RetentionMixin:
    _purge_lock = threading.Lock()

    def keep_days(self): return int(self.cfg.get("keep_days", 7))
    def cutoff_day(self):
        """The oldest broadcast day that is kept: today and the (N-1) days before it."""
        return self.today() - dt.timedelta(days=self.keep_days() - 1)
    def db_files(self):
        p = Path(self.db.path); sz = lambda x: x.stat().st_size if x.exists() else 0
        with self.db.lock: ps = self.db.conn.execute("PRAGMA page_size").fetchone()["page_size"]; free = self.db.conn.execute("PRAGMA freelist_count").fetchone()["freelist_count"] * ps
        return {"db_bytes": sz(p), "wal_bytes": sz(Path(str(p) + "-wal")), "free_bytes": free}
    def retention_state(self):
        with self.db.tx() as cur: hb = cur.one("SELECT ts, detail FROM heartbeats WHERE component='retention'")
        try: last = json.loads(hb["detail"]) if hb else None
        except (TypeError, ValueError): last = None
        return last
    def a_retention(self, r):
        n = self.keep_days(); f = self.db_files(); last = self.retention_state()
        return {"keep_days": n, "keeps_from": self.cutoff_day().isoformat() if n > 0 else None, "purge_at": self.cfg.get("purge_at", "03:30"), "db_mb": mb(f["db_bytes"] + f["wal_bytes"]), "free_mb": mb(f["free_bytes"]), "last": last}
    def a_retention_run(self, r):
        if self.keep_days() <= 0: raise HttpError(409, "AUTOID_KEEP_DAYS is 0: nothing is deleted. Set it to the number of days to keep (7) in autoid.env and restart")
        if not self._purge_lock.acquire(blocking=False): raise HttpError(409, "a cleanup is already running")
        self._purge_lock.release()
        out = self.purge_old("manual: " + r.user["username"]); return out

    def purge_old(self, why="scheduled"):
        n = self.keep_days()
        if n <= 0: return {"skipped": "AUTOID_KEEP_DAYS is 0"}
        if not self._purge_lock.acquire(blocking=False): return {"skipped": "already running"}
        try:
            cutd = self.cutoff_day().isoformat(); t0 = time.time(); before = self.db_files()
            with self.db.tx() as cur:
                todo = cur.one("SELECT (SELECT COUNT(*) FROM clip_ids WHERE day<?) AS clips, (SELECT COUNT(*) FROM events WHERE time<?) AS events", (cutd, cutd))
            out = {"why": why, "keeps_from": cutd, "clips": 0, "files": 0, "stories": 0, "rundowns": 0, "events": 0, "backup": None}
            if todo["clips"] or todo["events"]: out["backup"] = self.backup_before_purge()
            while True:                                                                     # clips (and what hangs on them), oldest first
                with self.db.tx() as cur:
                    ids = [x["id"] for x in cur.q("SELECT id FROM clip_ids WHERE day<? ORDER BY id LIMIT ?", (cutd, BATCH))]
                    if not ids: break
                    m = ",".join("?" * len(ids))
                    out["files"] += cur.x("DELETE FROM files WHERE clip_id IN (%s)" % m, ids)
                    cur.x("DELETE FROM clip_old_names WHERE clip_id IN (%s)" % m, ids)
                    out["clips"] += cur.x("DELETE FROM clip_ids WHERE id IN (%s)" % m, ids)
            while True:                                                                     # stories with no clip left that have not been seen since the cut
                with self.db.tx() as cur:
                    k = cur.x("DELETE FROM stories WHERE id IN (SELECT s.id FROM stories s WHERE NOT EXISTS (SELECT 1 FROM clip_ids c WHERE c.story_id=s.id) AND substr(COALESCE(s.last_seen_at,''),1,10)<? LIMIT ?)", (cutd, BATCH))
                out["stories"] += k
                if not k: break
            with self.db.tx() as cur:
                out["rundowns"] = cur.x("DELETE FROM rundowns WHERE NOT EXISTS (SELECT 1 FROM stories s WHERE s.rundown_id=rundowns.id) AND COALESCE(air_date,'')<?", (cutd,))
                cur.x("DELETE FROM counters WHERE day<?", (cutd,))
                cur.x("DELETE FROM support_jobs WHERE state NOT IN ('QUEUED','WORKING') AND substr(COALESCE(created_at,''),1,10)<?", (cutd,))      # v10.10.0: Quick Support requests that are over
            while True:                                                                     # the event log: the append-only lock is lifted only inside this one transaction and is back before it ends
                with self.db.tx() as cur:
                    cur.x("DROP TRIGGER IF EXISTS events_no_delete")
                    try: k = cur.x("DELETE FROM events WHERE id IN (SELECT id FROM events WHERE time<? ORDER BY id LIMIT ?)", (cutd, EVENTS_BATCH))
                    finally: cur.x(EVENTS_NO_DELETE)
                out["events"] += k
                if not k: break
            out["compacted"] = self.compact_if_worth_it(bool(out["clips"] or out["events"]))
            after = self.db_files(); out.update(secs=round(time.time() - t0, 1), db_mb_before=mb(before["db_bytes"] + before["wal_bytes"]), db_mb_after=mb(after["db_bytes"] + after["wal_bytes"]))
            rec = dict(out, date=self.now().date().isoformat(), at=now_iso())
            with self.db.tx() as cur:
                cur.x("INSERT INTO heartbeats(component, ts, detail) VALUES('retention', ?, ?) ON CONFLICT(component) DO UPDATE SET ts=excluded.ts, detail=excluded.detail", (time.time(), json.dumps(rec)))
                if out["clips"] or out["events"] or out["stories"]: self.log(cur, "retention", "purged", dict(out))
            return rec
        finally: self._purge_lock.release()

    def backup_before_purge(self):
        d = Path(self.db.path).parent / "backups"; d.mkdir(parents=True, exist_ok=True)
        dest = d / ("autoid-before-cleanup-%s.db" % time.strftime("%Y%m%d-%H%M%S")); self.db.backup(dest)
        for old in sorted(d.glob("autoid-before-cleanup-*.db"))[:-BACKUPS_KEPT]:
            try: old.unlink()
            except OSError: pass
        return dest.name

    def compact_if_worth_it(self, deleted):
        """Give the freed space back to the disk (VACUUM) when it is 5 MB or a quarter of the file. The WAL file is emptied first."""
        f = self.db_files()
        with self.db.lock:
            try: self.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception: pass
            if f["free_bytes"] >= 5 * 1048576 or (f["db_bytes"] and f["free_bytes"] * 4 >= f["db_bytes"] and f["free_bytes"] >= 262144):
                self.db.conn.execute("VACUUM"); self.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)"); return True
        return False

    def retention_due(self, now=None):
        """True once a day, from AUTOID_PURGE_AT on (also when the server was off at that time): the last cleanup is not from today's date."""
        if self.keep_days() <= 0: return False
        now = now or self.now(); last = self.retention_state() or {}
        return now.strftime("%H:%M") >= self.cfg.get("purge_at", "03:30") and last.get("date") != now.date().isoformat()

    def retention_loop(self):
        time.sleep(90)
        while True:
            try:
                if self.retention_due(): self.purge_old("scheduled")
            except Exception: print("retention: cleanup failed, will try again:\n" + traceback.format_exc(), file=sys.stderr, flush=True)
            time.sleep(600)
