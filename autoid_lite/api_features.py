"""v10.15.0: two read-only views over the registry, each with an on/off switch that lives in the database (not in autoid.env).

  Missing-clip board   /api/missing  stories that have no clip attached yet, grouped by bulletin, with a countdown to the bulletin's start.
                                     A bulletin that starts in less than `missing_minutes` (default 20) goes red. "Add media" is one click away (the page reuses Quick Support's Add media).
  Bulletin smoke test  /api/smoke    pick a bulletin, run a quick test: how many of its stories have a clip attached, as a bar graph, and which ones do not.

Both read only Storigen's own record (clip_ids), which the Blaze poller keeps up to date: they send nothing to Blaze and never touch the poller's safety wall.
The switches: GET /api/features (any signed-in user) and POST /api/features (admin: the `users` permission). They are stored in the `settings` table, so an admin changes them on the page (Users > Features)
and every signed-in user sees the change within a few seconds. Both are ON until an admin switches them off. Every change is written to the activity log with the admin's name."""
from __future__ import annotations
import datetime as dt, re
from .common import HttpError
from .db import now_iso

DEFAULT_MINUTES, MIN_MINUTES, MAX_MINUTES = 20, 1, 240
KEYS = {"missing_board": "feature.missing_board", "smoke_test": "feature.smoke_test", "standards_ai": "feature.standards_ai"}      # v10.16.0: standards_ai is OFF until an admin switches it on (footage stills go to an outside AI)
MINUTES_KEY = "feature.missing_board.minutes"
STATUS_TEXT = {"NO_FILE": "No file yet", "EXPORTING": "File seen, still converting", "FILE_READY": "File is in Blaze, not attached yet", "ATTACH_SENT": "Attach sent, being checked", "NEEDS_DESK": "Needs the desk"}
GRACE_MIN = 60              # same as ServiceMixin.AIRED_GRACE_MIN: a bulletin that started longer ago than this has aired

def start_ms(start_at):
    """A bulletin start (ISO text from Blaze) -> epoch milliseconds, or None. A time without a zone is UTC, as everywhere else in Storigen."""
    try: t = dt.datetime.fromisoformat(re.sub(r"Z$", "+00:00", str(start_at or "").strip()))
    except ValueError: return None
    if t.tzinfo is None: t = t.replace(tzinfo=dt.timezone.utc)
    return int(t.timestamp() * 1000)

def minutes_value(v):
    """The red-limit from a JSON body: a whole number of minutes, MIN_MINUTES..MAX_MINUTES. Anything else is refused (never silently changed)."""
    if isinstance(v, bool) or not isinstance(v, (int, str)): raise HttpError(422, "minutes must be a whole number")
    try: n = int(str(v).strip())
    except ValueError: raise HttpError(422, "minutes must be a whole number")
    if not MIN_MINUTES <= n <= MAX_MINUTES: raise HttpError(422, "minutes must be between %d and %d" % (MIN_MINUTES, MAX_MINUTES))
    return n

class FeaturesMixin:
    # ---------- the switches ----------
    def feat_read(self, cur):
        got = {x["key"]: x["value"] for x in cur.q("SELECT key, value FROM settings WHERE key LIKE 'feature.%'")}
        try: mins = minutes_value(got.get(MINUTES_KEY, DEFAULT_MINUTES))
        except HttpError: mins = DEFAULT_MINUTES                      # a damaged value never switches the board off or breaks the page
        return {"missing_board": got.get(KEYS["missing_board"], "1") != "0", "missing_minutes": mins, "smoke_test": got.get(KEYS["smoke_test"], "1") != "0", "standards_ai": got.get(KEYS["standards_ai"], "0") == "1"}
    def feat_view(self, cur=None):
        if cur is None:
            with self.db.tx() as c: return self.feat_view(c)
        f = self.feat_read(cur); out = {"missing_board": {"on": f["missing_board"], "minutes": f["missing_minutes"]}, "smoke_test": {"on": f["smoke_test"]}, "standards_ai": {"on": f["standards_ai"]}}
        if f["missing_board"]:                                          # the badge on the menu: how many stories still have no clip (bulletins not yet aired), and how many of them are in the red
            b = self.missing_data(cur, self.today().isoformat(), f["missing_minutes"], False); out["missing_board"].update(missing=b["missing"], red=b["red"])
        return out
    def feat_need(self, key):
        with self.db.tx() as cur: f = self.feat_read(cur)
        if not f[key]: raise HttpError(403, "%s is switched off. An admin can switch it on under Users > Features." % {"missing_board": "The Missing-clip board", "smoke_test": "The Bulletin smoke test", "standards_ai": "The AI standards check"}[key])
        return f
    def a_features(self, r): return self.feat_view()
    def a_features_set(self, r):
        b = r.body or {}; todo = {}
        for k in ("missing_board", "smoke_test", "standards_ai"):
            if k in b:
                if not isinstance(b[k], bool): raise HttpError(422, "%s must be true or false" % k)
                todo[KEYS[k]] = "1" if b[k] else "0"
        if "missing_minutes" in b: todo[MINUTES_KEY] = str(minutes_value(b["missing_minutes"]))
        if not todo: raise HttpError(400, "send missing_board, smoke_test, standards_ai and/or missing_minutes")
        with self.db.tx() as cur:
            before = self.feat_read(cur)
            for k, v in todo.items(): cur.x("INSERT INTO settings(key,value,updated_at,updated_by) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, updated_by=excluded.updated_by", (k, v, now_iso(), r.user["username"]))
            after = self.feat_read(cur)
            changed = {k: {"from": before[k], "to": after[k]} for k in after if after[k] != before[k]}
            if changed: self.log(cur, r.user["username"], "feature_changed", changed)
            return self.feat_view(cur)

    # ---------- what both views are built from ----------
    def coverage(self, cur, day, rundown=None):
        """Every real (not typed by hand, not removed) story of the broadcast day, grouped by bulletin, in bulletin-start order. A story HAS A CLIP when one of its clip IDs is ATTACHED and was not replaced by an update.
        A story without one gets the furthest point its file reached: NO_FILE, EXPORTING, FILE_READY (the file is in Blaze's media list), ATTACH_SENT or NEEDS_DESK. -> list of bulletins [{id, name, start_at, start_ms, aired, stories: [...]}]."""
        where, args = ["c.day=?", "COALESCE(s.deleted,0)=0", "ru.blaze_rundown_id NOT LIKE 'name:%'", "s.blaze_story_id NOT LIKE 'manual-%'"], [day]
        if rundown: where.append("ru.blaze_rundown_id=?"); args.append(rundown)
        rows = cur.q("SELECT ru.id AS ruid, ru.blaze_rundown_id AS rid, ru.name AS rname, ru.start_at, s.id AS sid, s.blaze_story_id AS bsid, s.slug, s.story_title, s.position, c.display_id, c.state, c.replaced_at, c.media_found_at "
                     "FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id WHERE " + " AND ".join(where) + " ORDER BY c.id", args)
        queued = {(x["blaze_rundown_id"], x["blaze_story_id"]) for x in cur.q("SELECT blaze_rundown_id, blaze_story_id FROM support_jobs WHERE kind='ADD' AND state IN ('QUEUED','WORKING')")}
        buls, stories = {}, {}
        for x in rows:
            b = buls.setdefault(x["ruid"], {"id": x["rid"], "name": x["rname"], "start_at": x["start_at"], "start_ms": start_ms(x["start_at"]), "aired": self.aired(x["start_at"]), "stories": []})
            s = stories.get(x["sid"])
            if s is None:
                s = stories[x["sid"]] = {"id": x["bsid"], "rundown": x["rid"], "title": (x["slug"] or x["story_title"] or "").strip() or "story " + x["bsid"], "position": x["position"], "has_clip": False, "stage": 0, "display_id": x["display_id"], "add_queued": (x["rid"], x["bsid"]) in queued}
                b["stories"].append(s)
            if x["state"] == "ATTACHED" and not x["replaced_at"]: s["has_clip"] = True
            st = x["state"]; rank = 5 if st in ("NEEDS_DESK", "QUARANTINED") else 4 if st == "ATTACH_SUBMITTED" else 3 if (st == "ON_NITRO" or x["media_found_at"]) else 2 if st in ("EXPORTING", "VERIFIED") else 1
            if rank > s["stage"]: s["stage"] = rank; s["display_id"] = x["display_id"]
        names = {1: "NO_FILE", 2: "EXPORTING", 3: "FILE_READY", 4: "ATTACH_SENT", 5: "NEEDS_DESK"}
        for b in buls.values():
            for s in b["stories"]:
                s["status"] = "ATTACHED" if s["has_clip"] else names[s.pop("stage")]; s.pop("stage", None); s["status_text"] = "Clip attached" if s["has_clip"] else STATUS_TEXT[s["status"]]
            b["stories"].sort(key=lambda s: (s["position"] is None, s["position"] if s["position"] is not None else 0, s["id"]))
        return sorted(buls.values(), key=lambda b: (b["start_ms"] is None, b["start_ms"] or 0, str(b["name"] or ""), b["id"]))
    def missing_data(self, cur, day, minutes, include_aired):
        now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000); out, red_n, miss_n = [], 0, 0
        for b in self.coverage(cur, day):
            miss = [s for s in b["stories"] if not s["has_clip"]]
            if not miss or (b["aired"] and not include_aired): continue
            left = None if b["start_ms"] is None else (b["start_ms"] - now) / 60000.0
            red = (not b["aired"]) and left is not None and left < minutes
            if not b["aired"]: miss_n += len(miss); red_n += len(miss) if red else 0
            out.append({"id": b["id"], "name": b["name"], "start_at": b["start_at"], "start_ms": b["start_ms"], "aired": b["aired"], "red": red, "minutes_left": None if left is None else round(left, 2), "total": len(b["stories"]), "missing": len(miss),
                        "stories": [{k: s[k] for k in ("id", "rundown", "title", "position", "status", "status_text", "add_queued", "display_id")} for s in miss]})
        return {"bulletins": out, "missing": miss_n, "red": red_n, "now_ms": now}
    def day_from(self, r):
        d = (r.q.get("day") or "").strip()
        if not d: return self.today().isoformat()
        try: return dt.datetime.strptime(d, "%Y%m%d").date().isoformat()
        except ValueError: raise HttpError(400, "day must be a real date written YYYYMMDD")

    # ---------- Missing-clip board ----------
    def a_missing(self, r):
        """Stories with no clip, by bulletin (soonest first). Parameters: day (YYYYMMDD, default today), aired=1 (also the bulletins that have already aired; they are never red)."""
        f = self.feat_need("missing_board"); day = self.day_from(r)
        with self.db.tx() as cur: out = self.missing_data(cur, day, f["missing_minutes"], (r.q.get("aired") or "").lower() in ("1", "true", "yes"))
        return dict(out, day=day, minutes=f["missing_minutes"])

    # ---------- Bulletin smoke test ----------
    def a_smoke(self, r):
        """Without `rundown`: the bulletins of the day for the picker. With `rundown` (the Blaze show id): the quick test of that bulletin: total stories, how many have a clip attached, the ones that do not."""
        self.feat_need("smoke_test"); day = self.day_from(r); rid = (r.q.get("rundown") or "").strip()[:80]
        with self.db.tx() as cur:
            buls = self.coverage(cur, day, rid or None)
            hb = cur.one("SELECT ts FROM heartbeats WHERE component='blaze_poll'")
        if not rid: return {"day": day, "bulletins": [{"id": b["id"], "name": b["name"], "start_at": b["start_at"], "start_ms": b["start_ms"], "aired": b["aired"], "total": len(b["stories"])} for b in buls]}
        if not buls: raise HttpError(404, "that bulletin has no stories today")
        b = buls[0]; miss = [s for s in b["stories"] if not s["has_clip"]]; total = len(b["stories"]); now = dt.datetime.now(dt.timezone.utc).timestamp()
        return {"day": day, "bulletin": {"id": b["id"], "name": b["name"], "start_at": b["start_at"], "start_ms": b["start_ms"], "aired": b["aired"]}, "total": total, "attached": total - len(miss), "missing": len(miss), "ok": not miss,
                "stories": [{k: s[k] for k in ("id", "rundown", "title", "position", "status", "status_text", "add_queued", "display_id")} for s in miss],
                "checked_ms": int(now * 1000), "poller_age_s": None if not hb else max(0, int(now - hb["ts"])), "stale_s": self.cfg.get("stale", 90)}
