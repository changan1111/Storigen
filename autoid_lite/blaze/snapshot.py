"""Complete-day snapshot, change detection and statistics for the Blaze poller.

Pure functions (diff_show, diff_clips) plus a small store kept in the poller's OWN ledger database (BLAZE_LEDGER): nothing here touches the Auto-ID database or schema.
Only fields that Blaze really returns are used (checked against captured traffic):
  slug list   GET /DataService/shows/<id>/slugs        slug id, finalPosition, slugTitle, storyId{id, clipCount, clipDur, clipStatus, cgCount, storyFormatId{id}}, slug clipState
  clip list   GET /DataService/stories/<id>/clips?clipType=media   id (Blaze clip ID), mosObjectId{id}, objId, title, duration, position, status, createdTime
  story       GET /DataService/stories/<id>/complete/  title (the STORY title, not always equal to the slug title)
Blaze exposes no story-level modified time in the slug list, and no file hash or version number for media: a replacement is recognised by clip ID, media object ID, objId, title and duration
(whatever changes). A new file saved under the same media object, name and length cannot be told apart, and nothing here claims to."""
from __future__ import annotations
import concurrent.futures as cf
import contextlib, json, statistics, time

# slug-list fields compared from one read to the next
TRACK = ("story_id", "title", "pos", "format", "clips", "clip_dur", "clip_status", "clip_state", "cg")
KIND_OF = {"title": "SLUG_TITLE", "pos": "POSITION", "format": "FORMAT", "clips": "CLIP_COUNT", "clip_dur": "CLIP_DURATION", "clip_status": "CLIP_STATUS", "clip_state": "CLIP_STATUS", "cg": "CG_COUNT"}
ATTACH_KINDS = ("ATTACH_ADDED", "ATTACH_REMOVED", "ATTACH_REPLACED", "ATTACH_CHANGED")


def view(s):
    """The part of a parsed slug (Blaze.slugs) that is kept in the snapshot."""
    return {k: s.get(k) for k in TRACK} | {"slug_id": s.get("slug_id")}


def _chg(kind, slug_id, story_id, old=None, new=None): return {"kind": kind, "slug_id": slug_id, "story_id": story_id, "old": old, "new": new}


def diff_show(prev, new):
    """Compare two snapshots of one show ({slug_id: view}) -> list of changes. Not only counts: a story swapped into an existing slug, a story that moved to another slug, titles, positions, format and the attachment signals."""
    out = []; prev_by_story = {}
    for sl, v in prev.items(): prev_by_story.setdefault(v["story_id"], []).append(sl)
    explained = set()
    for sl, v in new.items():
        p = prev.get(sl)
        if p is None:
            gone = [x for x in prev_by_story.get(v["story_id"], []) if x not in new]
            if gone: out.append(_chg("SLUG_ID_CHANGED", sl, v["story_id"], gone[0], sl)); explained.add(gone[0])
            else: out.append(_chg("SLUG_NEW", sl, v["story_id"], None, v["title"]))
            continue
        if p["story_id"] != v["story_id"]:
            out.append(_chg("STORY_REPLACED", sl, v["story_id"], p["story_id"], v["story_id"]))      # same slug, other story, whatever the slug count is
        for k in TRACK[1:]:
            if k in ("clips", "clip_dur", "clip_status", "clip_state", "cg") and p["story_id"] != v["story_id"]: continue      # the attachment numbers of a different story are not a change of this one
            if p.get(k) != v.get(k): out.append(_chg(KIND_OF[k], sl, v["story_id"], p.get(k), v.get(k)))
    for sl, p in prev.items():
        if sl not in new and sl not in explained: out.append(_chg("SLUG_REMOVED", sl, p["story_id"], p["title"], None))
    return out


def clip_row(c):
    """A clip as returned by GET /stories/<id>/clips (or the clips of /complete/), reduced to what identifies it."""
    return {"id": str(c.get("id")), "mos": str((c.get("mosObjectId") or {}).get("id")), "obj": c.get("objId"), "title": c.get("title") or "",
            "dur": c.get("duration") if isinstance(c.get("duration"), (int, float)) else None, "pos": c.get("position"), "status": c.get("status") or "", "created": c.get("createdTime")}


def _ident(c): return (c["mos"], c.get("obj"), c.get("title"), c.get("dur"), c.get("status"))


def diff_clips(prev, new):
    """Compare the attached media clips of one story -> changes. A clip that disappears while another appears is a REPLACEMENT even though the count is unchanged; a clip ID whose media changed in place is one too."""
    p = {c["id"]: c for c in prev}; n = {c["id"]: c for c in new}; out = []
    for i, c in n.items():
        if i in p and _ident(p[i]) != _ident(c):
            kind = "ATTACH_REPLACED" if (p[i]["mos"], p[i].get("obj")) != (c["mos"], c.get("obj")) else "ATTACH_CHANGED"
            out.append({"kind": kind, "old": p[i], "new": c})
    added = sorted((c for i, c in n.items() if i not in p), key=lambda c: (c.get("pos") or 0, c["id"])); removed = sorted((c for i, c in p.items() if i not in n), key=lambda c: (c.get("pos") or 0, c["id"]))
    for a, r in zip(added, removed): out.append({"kind": "ATTACH_REPLACED", "old": r, "new": a})
    for a in added[len(removed):]: out.append({"kind": "ATTACH_ADDED", "old": None, "new": a})
    for r in removed[len(added):]: out.append({"kind": "ATTACH_REMOVED", "old": r, "new": None})
    return out


SCHEMA = """
CREATE TABLE IF NOT EXISTS snap_slug(show_id TEXT, slug_id TEXT, story_id TEXT, title TEXT, pos INTEGER, format TEXT, clips INTEGER, clip_dur INTEGER, clip_status TEXT, clip_state TEXT, cg INTEGER,
  day TEXT, first_seen REAL, last_seen REAL, present INTEGER DEFAULT 1, PRIMARY KEY(show_id, slug_id));
CREATE TABLE IF NOT EXISTS snap_clip(story_id TEXT, clip_id TEXT, mos TEXT, obj TEXT, title TEXT, dur REAL, pos INTEGER, status TEXT, created TEXT, first_seen REAL, last_seen REAL, present INTEGER DEFAULT 1, PRIMARY KEY(story_id, clip_id));
CREATE TABLE IF NOT EXISTS snap_story(story_id TEXT PRIMARY KEY, title TEXT, seen_at REAL);
CREATE TABLE IF NOT EXISTS snap_poll(show_id TEXT PRIMARY KEY, title TEXT, last_ok REAL, last_try REAL, fails INTEGER DEFAULT 0, last_ms REAL, slugs INTEGER, last_error TEXT);
CREATE TABLE IF NOT EXISTS snap_change(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, day TEXT, show_id TEXT, story_id TEXT, slug_id TEXT, kind TEXT, old TEXT, new TEXT);
"""
KEEP_DAYS = 14                  # history older than this is dropped, so the ledger stays small over months


class Store:
    """The snapshot as kept on disk, so a restart compares with what was seen before the restart. Used from the poller's main thread only."""
    def __init__(self, conn): self.c = conn; self.c.executescript(SCHEMA)

    @contextlib.contextmanager
    def batch(self):
        """One transaction for a whole polling cycle: one disk sync instead of one per statement."""
        self.c.execute("BEGIN")
        try: yield
        except BaseException: self.c.execute("ROLLBACK"); raise
        else: self.c.execute("COMMIT")

    def load_show(self, show):
        rows = self.c.execute("SELECT * FROM snap_slug WHERE show_id=? AND present=1", (str(show),)).fetchall()
        return {r["slug_id"]: {k: r[k] for k in TRACK} | {"slug_id": r["slug_id"]} for r in rows} if rows else None

    def save_show(self, show, views, day, now):
        """Upsert every slug that is present; slugs that are gone are KEPT but marked present=0 (history is never deleted because a slug left the rundown or a request failed)."""
        for v in views.values():
            self.c.execute("INSERT INTO snap_slug(show_id,slug_id,story_id,title,pos,format,clips,clip_dur,clip_status,clip_state,cg,day,first_seen,last_seen,present) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1) "
                           "ON CONFLICT(show_id,slug_id) DO UPDATE SET story_id=excluded.story_id,title=excluded.title,pos=excluded.pos,format=excluded.format,clips=excluded.clips,clip_dur=excluded.clip_dur,"
                           "clip_status=excluded.clip_status,clip_state=excluded.clip_state,cg=excluded.cg,last_seen=excluded.last_seen,present=1",
                           (str(show), v["slug_id"], v["story_id"], v["title"], v["pos"], v["format"], v["clips"], v["clip_dur"], v["clip_status"], v["clip_state"], v["cg"], day, now, now))
        have = set(views)
        for r in self.c.execute("SELECT slug_id FROM snap_slug WHERE show_id=? AND present=1", (str(show),)).fetchall():
            if r["slug_id"] not in have: self.c.execute("UPDATE snap_slug SET present=0, last_seen=? WHERE show_id=? AND slug_id=?", (now, str(show), r["slug_id"]))

    def history(self, show):
        """Every slug ever seen for a show on the stored days, present or not."""
        return [dict(r) for r in self.c.execute("SELECT * FROM snap_slug WHERE show_id=? ORDER BY slug_id", (str(show),)).fetchall()]

    def day_counts(self, day):
        r = self.c.execute("SELECT COUNT(DISTINCT show_id) AS shows, COUNT(*) AS slugs, COUNT(DISTINCT story_id) AS stories FROM snap_slug WHERE day=? AND present=1", (day,)).fetchone()
        return dict(r)

    def load_clips(self, story):
        rows = self.c.execute("SELECT * FROM snap_clip WHERE story_id=? AND present=1 ORDER BY pos, clip_id", (str(story),)).fetchall()
        return [{"id": r["clip_id"], "mos": r["mos"], "obj": r["obj"], "title": r["title"], "dur": r["dur"], "pos": r["pos"], "status": r["status"], "created": r["created"]} for r in rows] if rows else None

    def save_clips(self, story, rows, now):
        for c in rows:
            self.c.execute("INSERT INTO snap_clip(story_id,clip_id,mos,obj,title,dur,pos,status,created,first_seen,last_seen,present) VALUES(?,?,?,?,?,?,?,?,?,?,?,1) "
                           "ON CONFLICT(story_id,clip_id) DO UPDATE SET mos=excluded.mos,obj=excluded.obj,title=excluded.title,dur=excluded.dur,pos=excluded.pos,status=excluded.status,last_seen=excluded.last_seen,present=1",
                           (str(story), c["id"], c["mos"], c.get("obj"), c["title"], c.get("dur"), c.get("pos"), c.get("status"), c.get("created"), now, now))
        have = {c["id"] for c in rows}
        for r in self.c.execute("SELECT clip_id FROM snap_clip WHERE story_id=? AND present=1", (str(story),)).fetchall():
            if r["clip_id"] not in have: self.c.execute("UPDATE snap_clip SET present=0, last_seen=? WHERE story_id=? AND clip_id=?", (now, str(story), r["clip_id"]))

    def story_title(self, story):
        r = self.c.execute("SELECT title FROM snap_story WHERE story_id=?", (str(story),)).fetchone(); return None if r is None else r["title"]

    def set_story_title(self, story, title, now): self.c.execute("INSERT INTO snap_story VALUES(?,?,?) ON CONFLICT(story_id) DO UPDATE SET title=excluded.title, seen_at=excluded.seen_at", (str(story), title, now))

    def poll_ok(self, show, title, now, ms, slugs):
        self.c.execute("INSERT INTO snap_poll VALUES(?,?,?,?,0,?,?,NULL) ON CONFLICT(show_id) DO UPDATE SET title=excluded.title,last_ok=excluded.last_ok,last_try=excluded.last_try,fails=0,last_ms=excluded.last_ms,slugs=excluded.slugs,last_error=NULL",
                       (str(show), title, now, now, ms, slugs))

    def poll_fail(self, show, now, error, fails):
        self.c.execute("INSERT INTO snap_poll(show_id,last_try,fails,last_error) VALUES(?,?,?,?) ON CONFLICT(show_id) DO UPDATE SET last_try=excluded.last_try,fails=excluded.fails,last_error=excluded.last_error",
                       (str(show), now, fails, str(error)[:300]))

    def polls(self): return {r["show_id"]: dict(r) for r in self.c.execute("SELECT * FROM snap_poll").fetchall()}

    def log(self, changes, day, now):
        for c in changes:
            self.c.execute("INSERT INTO snap_change(ts,day,show_id,story_id,slug_id,kind,old,new) VALUES(?,?,?,?,?,?,?,?)",
                           (now, day, str(c.get("show")), str(c.get("story_id")), c.get("slug_id"), c["kind"], json.dumps(c.get("old"), default=str), json.dumps(c.get("new"), default=str)))

    def changes(self, limit=200): return [dict(r) for r in self.c.execute("SELECT * FROM snap_change ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def prune(self, now, days=None):
        cut = now - (days or KEEP_DAYS) * 86400
        for t, col in (("snap_slug", "last_seen"), ("snap_clip", "last_seen"), ("snap_change", "ts"), ("snap_story", "seen_at")): self.c.execute("DELETE FROM %s WHERE %s<?" % (t, col), (cut,))


# ---------------------------------------------------------------- bounded parallel reads
class Out:
    """The outcome of one read: ok, value or exc, milliseconds, wall-clock start."""
    __slots__ = ("ok", "value", "exc", "ms", "started")
    def __init__(self, ok, value, exc, ms, started): self.ok, self.value, self.exc, self.ms, self.started = ok, value, exc, ms, started

class Fan:
    """Run many independent reads at once, at most `workers` at a time, and wait no longer than a deadline.
    * A read that fails comes back as Out(ok=False, exc=...): it never raises into the caller and never affects the others.
    * A read still running at the deadline is `late`: it stays in flight and is NOT started a second time (so one hung request can never pile up); its result is returned as `harvested` by a later run().
    * A read that had not even started at the deadline is cancelled and reported `late` too (it simply runs again next time).
    Only HTTP happens in the workers; everything that touches a database or shared state is done by the caller, on its own thread, with the results."""
    def __init__(self, workers, pool=None):
        """pool: share another Fan's thread pool (one pool for the whole poller, so `workers` really is the most requests in flight), each Fan keeping its own in-flight reads."""
        self.workers = max(1, int(workers)); self.own = pool is None
        self.pool = pool or cf.ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="blaze-poll"); self.inflight = {}
    @staticmethod
    def _call(fn):
        t, st = time.monotonic(), time.time()
        try: return Out(True, fn(), None, (time.monotonic() - t) * 1000, st)
        except Exception as e: return Out(False, None, e, (time.monotonic() - t) * 1000, st)
    def run(self, jobs, deadline):
        """jobs {key: callable}, deadline = a time.monotonic() value. -> (results {key: Out}, harvested {key: Out}, late {keys}, busy {keys})."""
        harvested, busy, late, results = {}, set(), set(), {}
        for k, fut in list(self.inflight.items()):
            if fut.done(): harvested[k] = fut.result(); del self.inflight[k]
        futs = {}
        for k, fn in jobs.items():
            if k in self.inflight: busy.add(k)
            else: futs[k] = self.pool.submit(self._call, fn)
        done, pending = cf.wait(list(futs.values()), timeout=max(0.0, deadline - time.monotonic())); rev = {f: k for k, f in futs.items()}
        for f in done: results[rev[f]] = f.result()
        for f in pending:
            late.add(rev[f])
            if not f.cancel(): self.inflight[rev[f]] = f
        return results, harvested, late, busy
    def close(self):
        if self.own: self.pool.shutdown(wait=False, cancel_futures=True)


class Stats:
    """Counters and timings for the monitoring interface. Per-cycle values are reset by begin(); the totals run since the poller started."""
    def __init__(self):
        self.cycles = self.missed = self.overlaps = self.changes_total = self.attach_total = self.req_ok_total = self.req_fail_total = 0; self.begin()
    def begin(self):
        self.api_ms, self.ok, self.failed, self.changed_stories, self.attach_changes, self.shows_total, self.slugs_total, self.stories_unique = [], 0, 0, set(), 0, 0, 0, 0
        self.ident_reads = 0; self.cycle_s = 0.0; self.phase = {}; self.late = 0
    def api(self, ms, ok):
        self.api_ms.append(ms)
        if ok: self.ok += 1; self.req_ok_total += 1
        else: self.failed += 1; self.req_fail_total += 1
    def end(self, seconds, target):
        self.cycles += 1; self.cycle_s = seconds
        if seconds > target: self.missed += 1
        self.changes_total += len(self.changed_stories); self.attach_total += self.attach_changes
    def as_dict(self, target, ages=None, fresh=None, stale=None):
        ms = sorted(self.api_ms); pct = lambda p: round(ms[min(len(ms) - 1, int(len(ms) * p))], 1) if ms else None
        d = {"shows": self.shows_total, "slugs": self.slugs_total, "stories": self.stories_unique, "show_requests_ok": self.ok, "show_requests_failed": self.failed,
             "api_ms_median": round(statistics.median(ms), 1) if ms else None, "api_ms_p95": pct(0.95), "api_ms_max": round(ms[-1], 1) if ms else None,
             "cycle_s": round(self.cycle_s, 2), "cycle_target_s": target, "cycles": self.cycles, "cycles_over_target": self.missed, "overlaps_skipped": self.overlaps,
             "changed_stories": len(self.changed_stories), "attachment_changes": self.attach_changes, "changes_total": self.changes_total, "attachment_changes_total": self.attach_total,
             "phase_s": {k: round(v, 2) for k, v in self.phase.items()}, "identity_reads": self.ident_reads, "late_reads": self.late, "requests_ok_total": self.req_ok_total, "requests_failed_total": self.req_fail_total}
        if ages is not None: d["last_ok_age_s_max"] = round(max(ages.values()), 1) if ages else None; d["shows_over_target"] = sum(1 for a in ages.values() if a > fresh); d["shows_stale"] = sum(1 for a in ages.values() if a > stale)
        return d
