"""The Poller: reading shows, syncing stories, identity, events. Method groups live in media.py, attach.py, reports.py and loop.py."""
from __future__ import annotations
from pathlib import Path
import datetime as dt
import threading
import time
from . import ledger as bl
from . import snapshot as snap
from .attach import AttachMixin
from .client import AutoId, Blaze
from .errors import SessionExpired
from .keys import ignored, rkey, show_ignored, transient
from .loop import RunMixin
from .media import MediaMixin
from .reports import ReportMixin
from .scripts import ScriptMixin
from .util import say


class Poller(MediaMixin, AttachMixin, ReportMixin, ScriptMixin, RunMixin):
    def __init__(self, c, blaze=None, autoid=None):
        self.c, self.b, self.a = c, blaze or Blaze(c), autoid or AutoId(c); self.led = bl.Ledger(c.ledger)
        self.names, self.pos, self.last, self.pinged, self.stories, self.rows, self.last_rec, self.skipped = {}, {}, {}, 0.0, {}, [], 0.0, {}
        self.five, self.five_at, self.page_err = None, 0.0, ""
        self.show_meta, self.list_at = {}, 0.0
        self.posin = {}                                    # v10.4.0: (show, story) -> row in THAT show (a shared story sits at a different row in every bulletin)
        self.store = snap.Store(self.led.c); self.stats = snap.Stats(); self.pool = snap.Fan(c.concurrency); self.fans = {}; self.dl = time.monotonic() + c.deadline; self.lock = threading.Lock(); self.started = time.time(); self.show_day, self.said, self.late_n, self.closed = {}, set(), 0, False
        self.snapv, self.synced, self.synced_at, self.fails, self.next_try, self.last_ok, self.raw = {}, {}, {}, {}, {}, {}, {}      # per show: snapshot, registry sync state, failures, retry time, last good read, raw slug/story counts
        self.info_cache = {}; self.round_fails = []; self.login_at, self.login_fails = 0.0, 0
        self.ident, self.dirty, self.story_shows, self.slow_streak, self.slow_said, self.log_at, self.reg_err = {}, set(), {}, 0, 0.0, 0.0, ""   # story -> (media rows, read time, signal); stories whose attachments changed
        for sh, r in self.store.polls().items():
            if r.get("last_ok"): self.last_ok[sh] = r["last_ok"]
        self.fmt, self.mcache = {}, {}; self.mlist, self.list_err, self.list_partial = None, False, False; self.clipcount, self.cc_read = {}, {}            # story ID -> Blaze story format; clip display ID -> (time, state, media) of the last media-list search
    def lookahead(self, day):
        """Shows Blaze lists under the NEXT calendar date but that start before the broadcast day ends (BROADCAST_DAY_START) and within BLAZE_SHOW_LOOKAHEAD_HOURS from now: the 00:00 to 05:00 shows seen from 21:00 on.
        One extra request per show-list refresh. A show that starts at or after the day end is NOT taken: it belongs to the next broadcast day and is picked up by the normal list when the day rolls over."""
        ends = dt.datetime.fromisoformat(self.a.call("/svc/status")["day_ends"]); ends = ends if ends.tzinfo else ends.astimezone(); now = dt.datetime.now(dt.timezone.utc)
        horizon = min(now + dt.timedelta(hours=self.c.lookahead_h), ends); out = []
        for x in self.b.day_shows(day + dt.timedelta(days=1)):
            try: st = dt.datetime.fromisoformat(x["start"])
            except (TypeError, ValueError): continue
            if st.tzinfo is None: st = st.astimezone()
            if now - dt.timedelta(minutes=30) <= st <= horizon and st < ends: out.append(x)
        return out
    def discover(self):
        """Auto mode: ask Blaze for the broadcast day's shows (and BLAZE_SHOW_DAYS_AHEAD more days) and follow all of them. A reply with no shows never empties the list."""
        if not self.c.auto or time.time() - self.list_at < self.c.list_secs: return
        day = self.server_day()
        try: lst = self.b.day_shows(day, day + dt.timedelta(days=self.c.days_ahead)); self.list_at = time.time()
        except SessionExpired: raise
        except Exception as e:                                       # the show list is not critical: keep following the shows already known and ask again soon
            self.list_at = time.time() - self.c.list_secs + min(15, self.c.list_secs)
            if self.c.shows: say("could not refresh the show list (%s: %s): following the %d known shows" % (type(e).__name__, e, len(self.c.shows))); return
            raise
        if self.c.lookahead_h > 0 and not self.c.days_ahead:
            try:
                have = {x["id"] for x in lst}; lst += [x for x in self.lookahead(day) if x["id"] not in have]
            except SessionExpired: raise
            except Exception as e:                                       # the look-ahead is a bonus: never let it break the normal list
                if "lookahead" not in self.said: self.said.add("lookahead"); say("look-ahead for shows after midnight failed (%s: %s): the normal show list is unaffected" % (type(e).__name__, e))
        keep = [x for x in lst if not show_ignored(x["title"], self.c.ignore_shows)]
        if not keep:
            if not self.c.shows: say("Blaze listed no shows for %s: nothing to follow yet" % day.isoformat())
            return
        if self.c.keep_completed:                                    # v9.5: a finished show Blaze no longer lists stays in the follow list until the broadcast day closes
            have = {x["id"] for x in keep}
            keep += [self.show_meta[sh] for sh in self.c.shows if sh not in have and sh in self.show_meta and self.show_day.get(sh) == day.isoformat() and self.completed(sh)]
        new = [x for x in keep if x["id"] not in self.show_meta]
        self.show_meta = {x["id"]: x for x in keep}; self.c.shows[:] = [x["id"] for x in keep]
        for x in keep: self.names[x["id"]] = (x["title"] or "SHOW " + x["id"], time.time()); self.show_day[x["id"]] = day.isoformat()
        for sh in [k for k in list(self.show_day) if k not in self.show_meta]:      # no longer followed: memory is released, the snapshot stays in the ledger as history
            for d in (self.show_day, self.fails, self.next_try, self.snapv, self.synced, self.synced_at, self.raw): d.pop(sh, None)
        if new:
            if len(new) <= 3: [self.event("NEW SHOW", "%s %s (%s stories)" % (x["id"], x["title"], x["slugs"])) for x in new]
            else: self.event("NEW SHOWS", "%d shows for %s: %s ... %s (ids %s to %s)" % (len(new), day.isoformat(), new[0]["title"], new[-1]["title"], new[0]["id"], new[-1]["id"]))
    # ---- layer A: every show, every pass
    def completed(self, show):
        """A show that started more than BLAZE_HOT_BEFORE_MIN minutes ago (a 30-minute bulletin is long over)."""
        try: mins = (dt.datetime.fromisoformat(self.show_meta[show]["start"]) - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60
        except (KeyError, TypeError, ValueError): return False
        return mins < -self.c.hot_before
    def rt(self, fn):
        """Run one Blaze read; a network or 5xx failure is retried quickly (BLAZE_REQUEST_RETRIES) while the round still has time. An expired session is never retried."""
        tries = 0
        while True:
            try: return fn()
            except SessionExpired: raise
            except Exception as e:
                if tries >= self.c.retries or not transient(e) or time.monotonic() + 0.3 >= self.dl: raise
                tries += 1; time.sleep(0.25)
    def pool_map(self, fn, items, tag="x", key=None):
        """Run fn over items in at most BLAZE_CONCURRENCY threads and wait no longer than the round's deadline (v9.5). The workers only talk to Blaze; every database or registry write stays in the main thread.
        A read still running at the deadline is NOT started a second time: its answer is returned by a later call with the same tag. A read that had not started is cancelled and runs again next time."""
        items = list(items); key = key or (lambda it: it)
        if self.pool.workers != self.c.concurrency: self.pool.close(); self.pool = snap.Fan(self.c.concurrency); self.fans = {}
        fan = self.fans.get(tag) or self.fans.setdefault(tag, snap.Fan(self.c.concurrency, self.pool.pool))
        self.dl = deadline = time.monotonic() + self.c.deadline
        jobs = {(tag, key(it)): (lambda it=it: fn(it)) for it in items}
        res, harv, late, busy = fan.run(jobs, deadline)
        self.late_n += len(late) + len(busy); self.stats.late = getattr(self.stats, "late", 0) + len(late) + len(busy)
        return [o.value for o in list(harv.values()) + [res[k] for k in jobs if k in res] if o.ok]      # in the order asked for (as Pool.map did), earlier late answers first
    def read_shows(self, shows):
        def one(show):
            t = time.monotonic()
            try:
                name = self.b.show_name(show) if (not self.c.auto and (show not in self.names or time.time() - self.names[show][1] > 600)) else None
                return show, "ok", self.rt(lambda: self.b.slugs(show)), name, (time.monotonic() - t) * 1000
            except SessionExpired as e: return show, "expired", e, None, (time.monotonic() - t) * 1000
            except Exception as e: return show, "err", e, None, (time.monotonic() - t) * 1000
        return self.pool_map(one, shows, "slugs")
    def note_fail(self, show, err, now, quiet=False):
        """A show could not be read: its last good snapshot stays, and it is retried with a growing delay (next pass, then poll x1, x2, x4 ... up to BLAZE_RETRY_MAX_SECS). A timeout is never an empty rundown."""
        n = self.fails.get(show, 0) + 1; self.fails[show] = n
        self.next_try[show] = now + (0 if n == 1 else min(self.c.retry_max, self.c.poll * 2 ** (n - 2)))
        self.store.poll_fail(show, now, "%s: %s" % (type(err).__name__, err), n)
        if not quiet: self.round_fails.append((show, err))
    def note_ok(self, show, now, ms, count):
        if self.fails.get(show): say("show %s: read again after %d failed attempt(s)" % (show, self.fails[show]))
        self.fails[show] = 0; self.next_try.pop(show, None); self.last_ok[show] = now; self.store.poll_ok(show, (self.names.get(show) or ("", 0))[0], now, ms, count)
    def day_key(self, day=None): return "closed:" + (day or self.server_day()).strftime("%Y%m%d")
    def sync(self):
        """Layer A (cheap, every pass): the slug lists of ALL the day's shows, read in parallel and within the round's deadline; each is compared with its stored snapshot (new, removed, swapped, retitled, moved, reformatted,
        attachment signals) and applied to the registry. A show that fails keeps its last good snapshot and is retried; it never blocks the others. A day closed with `close-day` is not polled."""
        self.round_fails = []; self.discover(); now = time.time(); day = self.server_day().isoformat(); shows = list(self.c.shows); self.stats.shows_total = len(shows)
        self.closed = self.led.get(self.day_key()) is not None
        if self.closed:
            if "closed" not in self.said: self.said.add("closed"); self.event("DAY CLOSED", "broadcast day %s is closed: polling of the shows is paused (snapshots are kept). `blaze_poll.py open-day` resumes it; the next broadcast day starts by itself." % day)
            self.story_shows = {}
            for sh in shows:
                for x in self.stories.get(sh, []): self.story_shows.setdefault(x["story_id"], []).append(sh)
            return sum(len(self.stories.get(sh, [])) for sh in shows)
        self.said.discard("closed")
        due = [x for x in shows if self.next_try.get(x, 0) <= now]; late0 = getattr(self.stats, "late", 0); results = [r for r in self.read_shows(due) if r[0] in self.c.shows]; late = getattr(self.stats, "late", 0) - late0
        expired = None; reg_try = reg_fail = 0; changes_all = []; first = []; reg_jobs = []
        with self.store.batch():
            for show, kind, val, name, ms in results:
                self.stats.api(ms, kind == "ok")
                if kind != "ok":
                    if kind == "expired": expired = expired or val
                    self.note_fail(show, val, now); continue
                sl = val
                if not sl and not self.c.allow_empty:
                    say("show %s: Blaze returned NO stories: not synced (an empty list would remove every story). Set BLAZE_ALLOW_EMPTY=1 if it is really empty." % show); self.note_fail(show, RuntimeError("empty answer"), now, quiet=True); continue
                if name: self.names[show] = (name, now)
                self.note_ok(show, now, ms, len(sl)); self.raw[show] = (len(sl), {x["story_id"] for x in sl})
                keep = [x for x in sl if not ignored(x["title"], self.c.ignore) and (not self.c.only_formats or x["format"] in self.c.only_formats)]
                if len(sl) - len(keep) != self.skipped.get(show) and not self.c.auto: self.skipped[show] = len(sl) - len(keep); say("show %s: %d row(s) left out (BLAZE_IGNORE_TITLES / BLAZE_ONLY_FORMAT_IDS)" % (show, self.skipped[show]))
                self.stories[show] = keep; sname = (self.names.get(show) or ("", 0))[0] or "SHOW " + show
                for x in keep: self.pos[x["story_id"]] = x["pos"]; self.posin[(show, x["story_id"])] = x["pos"]; self.fmt[x["story_id"]] = x["format"]; self.clipcount[x["story_id"]] = x.get("clips")
                newv = {x["slug_id"]: snap.view(x) for x in keep}
                if show not in self.snapv: self.snapv[show] = self.store.load_show(show)            # after a restart: what was seen before it
                prev = self.snapv[show]; ch = snap.diff_show(prev, newv) if prev is not None else []
                for c in ch: c["show"] = show
                if prev is None: first.append(show)
                if ch or prev is None: self.store.save_show(show, newv, day, now)
                self.snapv[show] = newv; changes_all += ch
                if ch or prev is None or not self.synced.get(show) or now - self.synced_at.get(show, 0) >= self.c.sync_secs: reg_jobs.append((show, sname, keep))
            self.store.log(changes_all, day, now)
        for show, sname, keep in reg_jobs:                       # v9.5: the registry is called after the ledger transaction is closed, never while it is open
            reg_try += 1; start = (self.show_meta.get(show) or {}).get("start") or None
            try:
                r = self.a.call("/svc/rundowns/sync", {"blaze_rundown_id": show, "rundown_name": sname, "rundown_start": start, "stories": [
                    {"blaze_story_id": x["story_id"], "slug": x["title"], "slug_id": x["slug_id"], "position": x["pos"], "story_title": x.get("story_title") or self.store.story_title(x["story_id"]) or None} for x in keep]})
                self.synced[show] = True; self.synced_at[show] = now
                if r.get("created") or r.get("removed"): say("show %s (%s): %d stories, %d new, %d removed, %d clips held" % (show, sname, r["stories"], r["created"], r["removed"], len(r["held"])))
            except Exception as e: self.synced[show] = False; reg_fail += 1; self.reg_err = "%s: %s" % (type(e).__name__, e)
        shout = [(sh, e) for sh, e in self.round_fails if self.fails.get(sh, 0) in (1, 3) or self.fails.get(sh, 0) % 10 == 0]      # said on the first and third failure and every tenth, not every round
        if shout: say("%d show(s) could not be read from Blaze this round, e.g. show %s (%s: %s), attempt %d: their last good snapshots are kept and they are retried with a growing delay" % (len(self.round_fails), shout[0][0], type(shout[0][1]).__name__, shout[0][1], self.fails[shout[0][0]]))
        if late and ("late" not in self.said or self.stats.cycles % 20 == 0):
            self.said.add("late"); say("%d show read(s) did not finish within the %d s round deadline: they finish in the background and are used by the next round (never requested twice)" % (late, self.c.deadline))
        if expired: raise expired
        if due and self.stats.ok == 0 and not late: raise RuntimeError("Blaze answered for none of the %d shows read (last error: %s)" % (len(due), self.store.polls().get(due[0], {}).get("last_error")))
        if reg_try and reg_fail == reg_try: raise RuntimeError("the Auto-ID registry did not accept any of the %d show updates (%s)" % (reg_try, self.reg_err))
        self.story_shows = {}
        for sh in shows:
            for x in self.stories.get(sh, []): self.story_shows.setdefault(x["story_id"], []).append(sh)
        self.stats.slugs_total = sum(n for n, _ in self.raw.values()); self.stats.stories_unique = len(set().union(*[st for _, st in self.raw.values()])) if self.raw else 0
        for c in changes_all: self.stats.changed_stories.add(c["story_id"])
        self.report_changes(changes_all, first)
        return sum(len(self.stories.get(sh, [])) for sh in shows)
    def report_changes(self, changes, first):
        if first: self.event("SNAPSHOT", "first snapshot of %d show(s): %d slugs, %d unique stories (%s)" % (len(first), sum(len(self.snapv.get(x) or {}) for x in first), len({v["story_id"] for x in first for v in (self.snapv.get(x) or {}).values()}), ", ".join(first[:4]) + (" ..." if len(first) > 4 else "")))
        moved = [c for c in changes if c["kind"] == "POSITION"]; rest = [c for c in changes if c["kind"] != "POSITION"]
        for c in rest[:20]:
            what = {"SLUG_NEW": "new slug", "SLUG_REMOVED": "slug removed", "SLUG_ID_CHANGED": "story moved to another slug", "STORY_REPLACED": "story replaced in the slug"}.get(c["kind"], c["kind"].lower().replace("_", " "))
            say("CHANGE show %s story %s slug %s: %s%s" % (c["show"], c["story_id"], c["slug_id"], what, "" if c["old"] is None and c["new"] is None else " (%s -> %s)" % (c["old"], c["new"])))
        if len(rest) > 20: say("CHANGE ... and %d more change(s) in this round" % (len(rest) - 20))
        if moved: say("CHANGE %d position change(s) in %d show(s)" % (len(moved), len({c["show"] for c in moved})))
    # ---- layer B: who is attached (identity), only where the cheap signals say so, plus a periodic sweep
    def where_story(self, sid):
        shs = self.story_shows.get(sid) or []
        return "story %s%s" % (sid, (" in " + ", ".join("%s (%s)" % ((self.names.get(x) or ("", 0))[0] or "show", x) for x in shs)) if shs else "")
    def identity(self):
        """Layer B. A story's clip list (GET /stories/<id>/clips?clipType=media, a few ms) is read when the slug list's attachment signals changed (count, total duration, status), when the story is seen for the first time, and every
        BLAZE_IDENT_SECS as a sweep: that sweep is what catches a clip swapped for another of the same length, and it bounds how late such a swap can be noticed. Added, removed, replaced and changed clips are reported."""
        now = time.time(); sig = {}; urgent, periodic = [], []
        for sh in self.c.shows:
            for x in self.stories.get(sh, []): sig[x["story_id"]] = (x.get("clips") or 0, x.get("clip_dur"), x.get("clip_status"))
        for sid, g in sig.items():
            have = self.ident.get(sid)
            if have is None:
                if g[0] == 0 and self.store.load_clips(sid) is None: self.ident[sid] = ([], now, g)
                else: urgent.append(sid)
            elif have[2] != g: urgent.append(sid)
            elif g[0] and now - have[1] >= self.c.ident_secs: periodic.append((have[1], sid))
        todo = urgent + [sid for _, sid in sorted(periodic)[: self.c.ident_batch]]
        if not todo: return
        def one(sid):
            t = time.time()
            try: return sid, "ok", ([] if sig[sid][0] == 0 else self.rt(lambda: self.b.story_media(sid))), (time.time() - t) * 1000
            except SessionExpired as e: return sid, "expired", e, 0
            except Exception as e: return sid, "err", e, 0
        res = [r for r in self.pool_map(one, todo, "ident") if r[0] in sig]; bad = 0; expired = None
        with self.store.batch():
            for sid, kind, val, ms in res:
                if kind == "expired": expired = expired or val; continue
                if kind == "err": bad += 1; continue
                self.stats.ident_reads += 1; prev = self.ident[sid][0] if sid in self.ident else self.store.load_clips(sid)
                ch = snap.diff_clips(prev, val) if prev is not None else []                    # no earlier knowledge: a silent baseline
                self.ident[sid] = (val, now, sig[sid]); self.store.save_clips(sid, val, now)
                if ch:
                    self.info_cache.pop(sid, None); self.dirty.add(sid); self.stats.attach_changes += len(ch); self.stats.changed_stories.add(sid)
                    for c in ch: self.attach_event(sid, c, now)
        if expired: raise expired
        if bad: say("%d attachment read(s) failed this round: they are repeated next round" % bad)
    def attach_event(self, sid, c, now):
        clip = lambda r: 'clip "%s" (media %s, clip id %s%s%s)' % (r["title"], r["mos"], r["id"], ", %ds" % int(r["dur"] // 1000) if r.get("dur") else "", ", status %s" % r["status"] if r.get("status") else "")
        kind = {"ATTACH_ADDED": "ATTACHMENT ADDED", "ATTACH_REMOVED": "ATTACHMENT REMOVED", "ATTACH_REPLACED": "ATTACHMENT REPLACED", "ATTACH_CHANGED": "ATTACHMENT CHANGED"}[c["kind"]]
        txt = {"ATTACH_ADDED": clip(c["new"] or {}) if c["new"] else "", "ATTACH_REMOVED": clip(c["old"]) if c["old"] else "", "ATTACH_REPLACED": "%s replaced by %s" % (clip(c["old"]), clip(c["new"])) if c["old"] and c["new"] else "",
               "ATTACH_CHANGED": "%s is now %s" % (clip(c["old"]), clip(c["new"])) if c["old"] and c["new"] else ""}[c["kind"]]
        self.event(kind, "%s: %s" % (self.where_story(sid), txt))
        self.store.log([{"kind": c["kind"], "show": (self.story_shows.get(sid) or [""])[0], "story_id": sid, "slug_id": None, "old": c["old"], "new": c["new"]}], self.server_day().isoformat(), now)
    def server_day(self):
        """The Auto-ID broadcast day (it starts at DAY_START, not at midnight: after midnight the night clips still belong to the day before)."""
        return dt.date.fromisoformat(self.a.call("/svc/status")["day"])
    def fetch_rows(self):
        today, rows = self.server_day(), []
        for d in range(self.c.days): rows += self.a.call("/svc/clips?day=%s" % (today - dt.timedelta(days=d)).strftime("%Y%m%d"))
        return rows
    # ---- the lines the desk and you read: one place, printed and also appended (with the date) to attach_watch.log
    def event(self, kind, headline, detail=None):
        say("%-16s %s" % (kind, headline)); detail and say("%-16s %s" % ("", detail))
        try:
            f = Path(self.c.watchlog); f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "a", encoding="utf-8") as fh:
                fh.write("%s %-16s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), kind, headline)); detail and fh.write("%s %-16s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), "", detail))
        except OSError: pass
    def announce(self, key, value):
        """True once per (key, value), and again only when value changes. Remembered in the ledger, so a restart does not repeat old lines."""
        if self.led.get(key) == value: return False
        self.led.put(key, value); return True
    def where(self, r):
        show = r["blaze_rundown_id"]; name = (self.names.get(show) or ("", 0))[0]
        return 'story %s "%s" (show %s %s, row %s)' % (r["blaze_story_id"], r.get("slug") or "", show, name, self.posin.get((show, r["blaze_story_id"]), self.pos.get(r["blaze_story_id"], "?")))
    def ready(self):
        """A clip reached Nitro (the watcher saw the original leave INBOX and a stable MXF with the same ID arrive): say which story it is for. Once per clip."""
        for r in self.rows:
            if r.get("deleted") or r["state"] != "ON_NITRO" or r.get("blaze_rundown_id") not in self.c.shows: continue
            if self.announce("ready:" + r["display_id"], "1"): self.event("READY ON NITRO", "clip %s is on Nitro: ready for %s" % (r["display_id"], self.where(r)))
    def lookup(self, r):
        """The result of the latest media-list search for this clip (see prefetch_media): (state, media|list), or "missing" when none was made yet."""
        c = self.mcache.get(r["display_id"]); return (c[1], c[2]) if c and rkey(r) else ("missing", None)
