"""v10.10.0 Quick Support: add a media clip to a story, or delete one from it, by hand (a side menu on the dashboard, meant for exceptions only).
Nothing is sent to Blaze from here. A request is a ROW in support_jobs; the Blaze poller (which owns the Blaze session and every safety check) picks it up, does it, and reports back.
kinds : ADD (attach a file; waits up to SUPPORT_QUEUE_MINUTES for a file that is not in Blaze yet), REMOVE (delete one clip from a story), LIST (read a story's clips from Blaze, for the delete picker)
states: QUEUED -> WORKING -> DONE | FAILED | BLOCKED (a safety rule said no, nothing was sent) | EXPIRED (the file never came) | CANCELLED (an editor cancelled a queued one)"""
from __future__ import annotations
import json, os, re, time
from .blaze.keys import media_key
from .common import HttpError, opt
from .db import now_iso

OPEN = ("QUEUED", "WORKING")
FINAL = ("DONE", "FAILED", "BLOCKED", "EXPIRED", "CANCELLED")
COLS = "id, kind, state, by_user, created_at, updated_at, expires_at, blaze_rundown_id, rundown, blaze_story_id, story, media_id, media_name, blaze_clip_id, clip_title, msg, result"
LIST_SECS = 120            # a LIST the poller has not answered by then fails (the poller is not running, or Blaze did not answer)
REMOVE_SECS = 600          # a REMOVE nobody picked up (poller down) is dropped after this long: a delete must never fire hours later
PICK_SECS = 900            # v10.10.1: the same for an ADD of a file that is already in the list ("attach now"): it is not carried out an hour later (a typed name keeps SUPPORT_QUEUE_MINUTES: it waits for the file on purpose)
WORKING_STALE = 1800       # v10.10.1: an ADD / REMOVE that has been WORKING this long without an answer was cut off (the poller stopped): it is closed as unclear, never sent again
NAME_MAX = 200             # v10.10.1: longest typed clip name
TITLE_MAX = 500            # v10.10.1: longest clip title (the one the page read from Blaze)
ID_MAX = 2 ** 62           # v10.10.1: a request number above this cannot exist (SQLite integers stop at 2**63)
def iso_in(seconds): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))
def sup_id(v, code=404):
    """v10.10.1: a request number from a URL or a report -> int. Not a number, or too big to exist: a clean 4xx instead of an internal error."""
    try: n = int(v)
    except (TypeError, ValueError): raise HttpError(code, "unknown request")
    if not 0 < n < ID_MAX: raise HttpError(code, "unknown request")
    return n
def sup_text(v, what, limit):
    """v10.10.1: a text field of a JSON body. Nothing -> "". A number is taken as its digits; a list, an object or true/false is refused; control characters become spaces; too long is refused (never cut: a cut name would match the wrong file)."""
    if v is None: return ""
    if isinstance(v, bool) or not isinstance(v, (str, int)): raise HttpError(400, "%s must be text" % what)
    t = re.sub(r"[\x00-\x1f\x7f]+", " ", str(v)).strip()
    if len(t) > limit: raise HttpError(422, "%s is too long (at most %d characters)" % (what, limit))
    return t


class SupportMixin:
    # ---------- helpers ----------
    def sup_on(self):
        if not self.cfg.get("support", True): raise HttpError(403, "Quick Support is switched off (SUPPORT_MENU=0)")
    @staticmethod
    def sup_view(j):
        j = dict(j)
        try: j["result"] = json.loads(j["result"]) if j.get("result") else None
        except ValueError: j["result"] = None
        return j
    def sup_expire(self, cur, stale=False):
        """Queued requests whose time ran out. Said once (the state changes), alerted for an ADD whose file never came.
        stale=True (the page asks, never the poller): also an ADD / REMOVE that has been WORKING for WORKING_STALE seconds with no answer is closed as FAILED (unclear, never sent again). The poller itself does not do this: when it
        starts again it settles such a request by reading the story, which is more exact."""
        now = now_iso()
        if stale:
            old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - WORKING_STALE)); msg = "No answer came back after this request was started (the poller stopped?). It is unclear whether it went through: look at the story in Blaze. Nothing is sent again."
            for j in cur.q("SELECT %s FROM support_jobs WHERE state='WORKING' AND kind<>'LIST' AND COALESCE(updated_at,'')<?" % COLS, (old,)):
                if cur.x("UPDATE support_jobs SET state='FAILED', msg=?, updated_at=? WHERE id=? AND state='WORKING'", (msg, now, j["id"])):
                    self.log(cur, "blaze", "support_failed", {"id": j["id"], "kind": j["kind"], "story": j["story"], "media": j["media_name"] or j["clip_title"], "message": msg})
                    self.alert("Quick Support (%s) for story \"%s\" (%s) got no answer: %s" % (j["kind"], j["story"], j["rundown"], msg))
        for j in cur.q("SELECT %s FROM support_jobs WHERE expires_at<? AND (state='QUEUED' OR (state='WORKING' AND kind='LIST'))" % COLS, (now,)):
            if j["kind"] == "LIST": st, msg = "FAILED", "Blaze did not answer in time. Is the Blaze poller running?"
            elif j["kind"] == "REMOVE": st, msg = "EXPIRED", "Nobody picked this request up in time (is the Blaze poller running?): nothing was deleted. Ask again if it is still needed."
            elif j["media_id"]: st, msg = "EXPIRED", "This file was not attached in time (the poller did not get to it, or Blaze was still converting the file): nothing was attached. Pick the file again if it is still needed."
            else: st, msg = "EXPIRED", "The file did not appear in Blaze's media list in time: nothing was attached. Queue it again when the file has been exported."
            if cur.x("UPDATE support_jobs SET state=?, msg=?, updated_at=? WHERE id=? AND state IN ('QUEUED','WORKING')", (st, msg, now, j["id"])) and j["kind"] != "LIST":
                self.log(cur, "blaze", "support_" + st.lower(), {"id": j["id"], "kind": j["kind"], "story": j["story"], "media": j["media_name"] or j["clip_title"], "message": msg})
                self.alert("Quick Support (%s) for story \"%s\" (%s) expired: %s" % (j["kind"], j["story"], j["rundown"], msg))
    def sup_story(self, cur, rid, sid):
        """The story must be a real, still-present Blaze story of that bulletin. -> (story row, rundown row)"""
        if not rid or not sid: raise HttpError(400, "choose the bulletin and the story")
        if str(rid).startswith("name:") or str(sid).startswith("manual-"): raise HttpError(409, "this story was typed by hand: it has no real Blaze story")
        st = cur.one("""SELECT s.id, s.blaze_story_id, s.slug, s.story_title, ru.blaze_rundown_id, ru.name AS rundown, ru.start_at, s.deleted
                        FROM stories s JOIN rundowns ru ON ru.id=s.rundown_id WHERE ru.blaze_rundown_id=? AND s.blaze_story_id=?""", (str(rid), str(sid)))
        if not st: raise HttpError(404, "unknown story")
        if st["deleted"]: raise HttpError(409, "the story is no longer in the rundown in Blaze")
        return st
    @staticmethod
    def sup_title(st): return (st["slug"] or st["story_title"] or "").strip() or "story " + st["blaze_story_id"]
    def sup_job_row(self, cur, jid):
        j = cur.one("SELECT %s FROM support_jobs WHERE id=?" % COLS, (jid,))
        if not j: raise HttpError(404, "unknown request")
        return j

    # ---------- the page: what the pickers show ----------
    def a_sup_bulletins(self, r):
        self.sup_on(); d = (r.q.get("day") or "").strip()
        try: day = (__import__("datetime").datetime.strptime(d, "%Y%m%d").date() if re.fullmatch(r"\d{8}", d) else self.today()).isoformat()
        except ValueError: raise HttpError(400, "day must be a real date written YYYYMMDD")
        with self.db.tx() as cur:
            rows = cur.q("""SELECT ru.blaze_rundown_id AS id, ru.name, ru.start_at, COUNT(DISTINCT s.id) AS stories FROM rundowns ru JOIN stories s ON s.rundown_id=ru.id JOIN clip_ids c ON c.story_id=s.id
                            WHERE c.day=? AND s.deleted=0 AND ru.blaze_rundown_id NOT LIKE 'name:%' AND s.blaze_story_id NOT LIKE 'manual-%'
                            GROUP BY ru.id ORDER BY COALESCE(ru.start_at,''), ru.name""", (day,))
        for x in rows: x["aired"] = self.aired(x["start_at"])
        return {"day": day, "bulletins": rows, "wait_min": self.cfg.get("support_wait_min", 60)}
    def a_sup_stories(self, r):
        self.sup_on(); rid = (r.q.get("rundown") or "").strip()
        with self.db.tx() as cur:
            ru = cur.one("SELECT start_at FROM rundowns WHERE blaze_rundown_id=?", (rid,))
            if not ru: raise HttpError(404, "unknown bulletin")
            rows = cur.q("""SELECT s.blaze_story_id AS id, COALESCE(NULLIF(TRIM(s.slug),''), NULLIF(TRIM(s.story_title),''), 'story ' || s.blaze_story_id) AS title, s.position AS pos
                            FROM stories s JOIN rundowns ru ON ru.id=s.rundown_id WHERE ru.blaze_rundown_id=? AND s.deleted=0 AND s.blaze_story_id NOT LIKE 'manual-%'
                            ORDER BY s.position IS NULL, s.position, s.id""", (rid,))
        return {"stories": rows, "aired": self.aired(ru["start_at"])}
    def a_sup_media(self, r):
        """The files this registry has already found in Blaze's media list (what the log holds), newest first: the drop-down of 'Add media'."""
        self.sup_on()
        try: days = max(1, int(os.getenv("BLAZE_MEDIA_DAYS", "2") or "2"))
        except ValueError: days = 2
        since = (self.today() - __import__("datetime").timedelta(days=days)).isoformat()
        with self.db.tx() as cur:
            rows = cur.q("""SELECT media_id, COALESCE(MAX(media_name), MAX(name_id), MAX(display_id)) AS name, MAX(media_found_at) AS found_at FROM clip_ids
                            WHERE media_id IS NOT NULL AND media_id<>'' AND day>=? GROUP BY media_id ORDER BY MAX(media_found_at) DESC, media_id DESC LIMIT 600""", (since,))
        return {"media": rows, "days": days}
    def a_sup_jobs(self, r):
        """The queue and the last day's results, newest first. Every signed-in user sees all of it: that is how everyone is notified."""
        self.sup_on()
        with self.db.tx() as cur:
            self.sup_expire(cur, True); since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400))
            rows = cur.q("SELECT %s FROM support_jobs WHERE kind<>'LIST' AND (state IN ('QUEUED','WORKING') OR updated_at>=?) ORDER BY id DESC LIMIT 60" % COLS, (since,))
        return {"jobs": [self.sup_view(x) for x in rows], "open": sum(1 for x in rows if x["state"] in OPEN)}
    def a_sup_job(self, r):
        self.sup_on()
        jid = sup_id(r.m[0])
        with self.db.tx() as cur: self.sup_expire(cur, True); return self.sup_view(self.sup_job_row(cur, jid))

    # ---------- the page: requests (each one is recorded with the user's name) ----------
    def a_sup_list(self, r):
        """Ask the poller to read this story's clips from Blaze (the delete picker). A request for the same story that is still open is shared (a finished one is never reused: the list must be fresh)."""
        self.sup_on(); b = r.body
        with self.db.tx() as cur:
            st = self.sup_story(cur, opt(b.get("rundown")), opt(b.get("story"))); self.sup_expire(cur)
            old = cur.one("SELECT id FROM support_jobs WHERE kind='LIST' AND state IN ('QUEUED','WORKING') AND blaze_story_id=? AND blaze_rundown_id=? ORDER BY id DESC LIMIT 1",
                          (st["blaze_story_id"], st["blaze_rundown_id"]))
            if old: return {"id": old["id"]}
            jid = cur.insert("""INSERT INTO support_jobs(kind,state,by_user,created_at,updated_at,expires_at,blaze_rundown_id,rundown,blaze_story_id,story) VALUES('LIST','QUEUED',?,?,?,?,?,?,?,?)""",
                             (r.user["username"], now_iso(), now_iso(), iso_in(LIST_SECS), st["blaze_rundown_id"], st["rundown"], st["blaze_story_id"], self.sup_title(st)))
            return {"id": jid}
    def a_sup_add(self, r):
        self.sup_on(); b = r.body
        if b.get("confirm") is not True: raise HttpError(400, "confirmation missing: the editor must answer Yes")
        name = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", sup_text(b.get("name"), "the clip name", NAME_MAX)); mid = opt(b.get("media_id"))
        if bool(name) == bool(mid): raise HttpError(400, "pick one clip from the list, or type the correct name (not both)")
        with self.db.tx() as cur:
            st = self.sup_story(cur, opt(b.get("rundown")), opt(b.get("story"))); self.sup_expire(cur)
            if mid:
                m = cur.one("SELECT media_id, COALESCE(MAX(media_name), MAX(name_id), MAX(display_id)) AS name FROM clip_ids WHERE media_id=? GROUP BY media_id", (mid,))
                if not m: raise HttpError(404, "that file is not in the list (any more): type its name to queue it instead")
                mname = m["name"]
            else:
                if not media_key(name): raise HttpError(422, "That name is not valid. Use DDMMYY_STORY_NAME (capitals, digits and underscores), for example 221126_FIRE_AT_PORT")
                mname = name
            key = media_key(mname)
            for x in cur.q("SELECT id, media_id, media_name FROM support_jobs WHERE kind='ADD' AND state IN ('QUEUED','WORKING') AND blaze_story_id=?", (st["blaze_story_id"],)):
                if (mid and x["media_id"] == mid) or (key and media_key(x["media_name"]) == key): raise HttpError(409, "this clip is already queued for this story (request %d)" % x["id"])
            jid = cur.insert("""INSERT INTO support_jobs(kind,state,by_user,created_at,updated_at,expires_at,blaze_rundown_id,rundown,blaze_story_id,story,media_id,media_name,msg) VALUES('ADD','QUEUED',?,?,?,?,?,?,?,?,?,?,?)""",
                             (r.user["username"], now_iso(), now_iso(), iso_in(60 * int(self.cfg.get("support_wait_min", 60)) if not mid else min(PICK_SECS, 60 * int(self.cfg.get("support_wait_min", 60)))), st["blaze_rundown_id"], st["rundown"], st["blaze_story_id"], self.sup_title(st), mid, mname,
                              "Queued: waiting for the poller" if mid else "Queued: waiting for this file to appear in Blaze"))
            self.log(cur, r.user["username"], "support_add_queued", {"id": jid, "story": self.sup_title(st), "blaze_story_id": st["blaze_story_id"], "show": st["blaze_rundown_id"], "bulletin": st["rundown"], "media": mname, "media_id": mid, "typed": not mid, "bulletin_aired": self.aired(st["start_at"])})
            return {"ok": True, "id": jid, "aired": self.aired(st["start_at"])}
    def a_sup_remove(self, r):
        self.sup_on(); b = r.body
        if b.get("confirm") is not True: raise HttpError(400, "confirmation missing: the editor must answer Yes")
        cid, title = opt(b.get("clip_id")), sup_text(b.get("clip_title"), "the clip title", TITLE_MAX)
        if not cid: raise HttpError(400, "choose the clip to delete")
        with self.db.tx() as cur:
            st = self.sup_story(cur, opt(b.get("rundown")), opt(b.get("story"))); self.sup_expire(cur)
            if cur.one("SELECT id FROM support_jobs WHERE kind='REMOVE' AND state IN ('QUEUED','WORKING') AND blaze_story_id=? AND blaze_clip_id=?", (st["blaze_story_id"], cid)): raise HttpError(409, "this clip is already being deleted")
            jid = cur.insert("""INSERT INTO support_jobs(kind,state,by_user,created_at,updated_at,expires_at,blaze_rundown_id,rundown,blaze_story_id,story,blaze_clip_id,clip_title,msg) VALUES('REMOVE','QUEUED',?,?,?,?,?,?,?,?,?,?,?)""",
                             (r.user["username"], now_iso(), now_iso(), iso_in(REMOVE_SECS), st["blaze_rundown_id"], st["rundown"], st["blaze_story_id"], self.sup_title(st), cid, title, "Queued: waiting for the poller"))
            self.log(cur, r.user["username"], "support_remove_queued", {"id": jid, "story": self.sup_title(st), "blaze_story_id": st["blaze_story_id"], "show": st["blaze_rundown_id"], "bulletin": st["rundown"], "clip": title, "blaze_clip_id": cid, "bulletin_aired": self.aired(st["start_at"])})
            return {"ok": True, "id": jid, "aired": self.aired(st["start_at"])}
    def a_sup_cancel(self, r):
        """Only a request that has not started: a queued add that is still waiting for its file."""
        self.sup_on()
        with self.db.tx() as cur:
            j = self.sup_job_row(cur, sup_id(r.m[0]))
            if j["kind"] == "LIST" or j["state"] != "QUEUED": raise HttpError(409, "it is already %s: it cannot be cancelled now" % j["state"])
            cur.x("UPDATE support_jobs SET state='CANCELLED', msg=?, updated_at=? WHERE id=? AND state='QUEUED'", ("Cancelled by %s" % r.user["username"], now_iso(), j["id"]))
            self.log(cur, r.user["username"], "support_cancelled", {"id": j["id"], "kind": j["kind"], "story": j["story"]})
        return {"ok": True}

    # ---------- the poller ----------
    def s_sup_jobs(self, r):
        """Open requests for the poller. ?kind=LIST (only the read-only story lists), ACTION (add / delete) or nothing (all)."""
        k = (r.q.get("kind") or "").upper()
        with self.db.tx() as cur:
            self.sup_expire(cur)
            w = {"LIST": " AND kind='LIST'", "ACTION": " AND kind<>'LIST'"}.get(k, "")
            out = [self.sup_view(x) for x in cur.q("SELECT %s FROM support_jobs WHERE state='QUEUED'%s ORDER BY id LIMIT 50" % (COLS, w))]
            if k != "LIST":                                                      # WORKING when the poller restarted: the outcome is unclear, the poller settles it by reading the story (never sends it again)
                out += [dict(self.sup_view(x), recovered=True) for x in cur.q("SELECT %s FROM support_jobs WHERE state='WORKING' AND kind<>'LIST' ORDER BY id LIMIT 20" % COLS)]
            return out
    def s_sup_result(self, r):
        """The poller's report. `from` makes a state change conditional (QUEUED -> WORKING is how it claims a request: two readers never both do one)."""
        b = r.body; self.need(b, "id", "state")
        if b["state"] not in ("QUEUED", "WORKING") + FINAL: raise HttpError(422, "bad state")
        with self.db.tx() as cur:
            j = self.sup_job_row(cur, sup_id(b["id"], 422))
            if j["state"] in FINAL: return {"ok": False, "state": j["state"]}
            if b.get("from") and j["state"] != b["from"]: return {"ok": False, "state": j["state"]}
            msg = str(b.get("message") or "")[:600]; res = b.get("result")
            cur.x("UPDATE support_jobs SET state=?, msg=?, updated_at=?, result=COALESCE(?,result), media_id=COALESCE(?,media_id), media_name=COALESCE(?,media_name) WHERE id=?",
                  (b["state"], msg, now_iso(), json.dumps(res, ensure_ascii=False) if res is not None else None, opt(b.get("media_id")), opt(b.get("media_name")), j["id"]))
            if b["state"] != j["state"] and j["kind"] != "LIST" and b["state"] != "QUEUED":
                self.log(cur, "blaze", "support_" + b["state"].lower(), {"id": j["id"], "kind": j["kind"], "by": j["by_user"], "story": j["story"], "blaze_story_id": j["blaze_story_id"], "media": j["media_name"] or j["clip_title"], "message": msg})
            if b["state"] == "DONE" and j["kind"] == "REMOVE" and j["blaze_clip_id"]:
                mos = str((res or {}).get("mos") or ""); held = []
                for c in cur.q("""SELECT c.id, c.display_id FROM clip_ids c JOIN stories s ON s.id=c.story_id WHERE s.blaze_story_id=? AND c.state='ATTACHED' AND (c.blaze_clip_id=? OR (?<>'' AND c.media_id=?))""", (j["blaze_story_id"], j["blaze_clip_id"], mos, mos)):
                    cur.x("UPDATE clip_ids SET state='NEEDS_DESK', blaze_clip_id=NULL, attach_error=? WHERE id=?",
                          ("DELETED FROM THE STORY by %s in Quick Support. The tool will not attach it again by itself: use Quick Support > Add media to put it back." % j["by_user"], c["id"])); held.append(c["display_id"])
                if held: self.log(cur, "blaze", "support_clip_ids_held", {"id": j["id"], "clips": held})
            if b["state"] == "FAILED" and j["kind"] != "LIST": self.alert("Quick Support (%s) FAILED for story \"%s\" (%s): %s" % (j["kind"], j["story"], j["rundown"], msg))
        return {"ok": True, "state": b["state"]}
