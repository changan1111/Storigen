"""v10.17.0: the FULL clip list of a story as Blaze holds it.

The registry only knows the clips Storigen made IDs for. A clip somebody added by hand in Blaze was invisible on the dashboard and to the chat (Support reads the story from Blaze, so it saw everything).
Now the poller reports the whole list of a story to /svc/story_clips every time it reads the story (and after every Support add, delete or list); it is kept in `story_blaze_clips`.
  * the dashboard shows a clip that is in that list but not in the registry as an 'Added by hand' card (Delete works; since v10.18.0 Play finds its file on Nitro by name; no quality checks);
  * the chat merges the list with the registry before it works out the next _U / _V names. Clips with another name are listed apart and never change the numbering.
Everything here only READS Blaze data that the poller already sent: nothing is sent to Blaze from this file."""
from __future__ import annotations
import json, re, time
from .common import HttpError, opt
from . import preview
from .db import now_iso
from .ids import enc_version, norm_name, strip_label

SUFFIX_RE = re.compile(r"((?:_[UV]\d+)+)$", re.I)                 # ..._V01, ..._U02, ..._V01_U02
CAP = 200                                                          # clips kept per story


def parse_clip_name(title):
    """'231126_FIRE_V01_U02' -> ('231126_FIRE', 2000+1 ...) i.e. (base, stored version). A name without a suffix is the plain clip (1). None for a name this rule book cannot place (_V01_U01_V02 ...)."""
    t = strip_label(re.sub(r"\.[A-Za-z0-9]{2,4}$", "", (title or "").strip())); m = SUFFIX_RE.search(t)
    if not m: return t, 1
    base, suf = t[: m.start()], m.group(1).upper(); parts = re.findall(r"_([UV])(\d+)", suf)
    if not base or len(parts) > 2 or any(int(n) < 1 or int(n) > 99 for _, n in parts): return None
    if len(parts) == 1: return base, enc_version(parts[0][0], parts[0][1])
    (k1, n1), (k2, n2) = parts
    if k1 == "V" and k2 == "U": return base, 10000 + int(n1) * 100 + int(n2)
    return None


def merge_blaze(base, rows, bclips):
    """Pure (tested on its own). rows: the registry rows of the story name (dicts with name_id, version, state, replaced_at); bclips: [{id, mos, title}] as Blaze lists them.
    -> (rows + one ATTACHED row for every Blaze clip that is named like this story but is not in the registry, [other clips: another name, or a name that is not DDMMYY_NAME_Vn / _Un]).
    A hand-added _V01 therefore makes the next append V02."""
    have = {norm_name(x.get("name_id") or "") for x in rows}; versions = {int(x["version"] or 1) for x in rows}; out, others = list(rows), []
    for c in bclips or []:
        t = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", (c.get("title") or "").strip()); key = norm_name(t)
        if not t or key in have: continue
        p = parse_clip_name(t)
        if not p or norm_name(p[0]) != norm_name(base) or p[1] in versions: others.append({"name": t, "id": c.get("id")}); continue
        versions.add(p[1]); have.add(key); out.append({"name_id": t, "display_id": t, "version": p[1], "state": "ATTACHED", "replaced_at": None, "blaze_story_id": None, "by_hand": True})
    return out, others


class BlazeClipsMixin:
    def s_story_clips(self, r):
        """The poller's report: {story: <Blaze story id>, clips: [{id, mos, title, dur_s}]}. Only a changed list is written."""
        b = r.body; self.need(b, "story", "clips")
        if not isinstance(b["clips"], list): raise HttpError(422, "clips must be a list")
        sid = str(b["story"]).strip()
        if not sid or sid.startswith("manual-"): raise HttpError(422, "bad story id")
        clips = [{"id": str(c.get("id")), "mos": str(c.get("mos") or ""), "title": str(c.get("title") or "")[:200], "dur_s": c.get("dur_s") if isinstance(c.get("dur_s"), (int, float)) else None}
                 for c in b["clips"][:CAP] if isinstance(c, dict) and c.get("id") is not None]
        raw = json.dumps(clips, ensure_ascii=False, sort_keys=True)
        with self.db.tx() as cur:
            old = cur.one("SELECT clips FROM story_blaze_clips WHERE blaze_story_id=?", (sid,))
            if old and old["clips"] == raw: cur.x("UPDATE story_blaze_clips SET seen_at=? WHERE blaze_story_id=?", (now_iso(), sid)); return {"ok": True, "changed": False}
            cur.x("INSERT INTO story_blaze_clips(blaze_story_id,clips,seen_at) VALUES(?,?,?) ON CONFLICT(blaze_story_id) DO UPDATE SET clips=excluded.clips, seen_at=excluded.seen_at", (sid, raw, now_iso()))
        return {"ok": True, "changed": True, "n": len(clips)}

    @staticmethod
    def note_added(cur, sid, clip_id, mos, title):
        """v10.18.0: a Support add that finished (DONE) puts its clip into the story's list at once, from the poller's own result, so the card does not wait for the next full report
        (the poller's report after the add still replaces this list with what Blaze really holds). Nothing is sent to Blaze. A clip that is already listed is left alone."""
        sid = str(sid or "").strip()
        if not sid or sid.startswith("manual-") or not clip_id: return False
        old = cur.one("SELECT clips FROM story_blaze_clips WHERE blaze_story_id=?", (sid,))
        try: v = json.loads(old["clips"]) if old else []
        except ValueError: v = []
        if not isinstance(v, list): v = []
        if any(str(x.get("id")) == str(clip_id) for x in v if isinstance(x, dict)): return False
        v.append({"id": str(clip_id), "mos": str(mos or ""), "title": str(title or "")[:200], "dur_s": None})
        raw = json.dumps(v[:CAP], ensure_ascii=False, sort_keys=True)
        cur.x("INSERT INTO story_blaze_clips(blaze_story_id,clips,seen_at) VALUES(?,?,?) ON CONFLICT(blaze_story_id) DO UPDATE SET clips=excluded.clips, seen_at=excluded.seen_at", (sid, raw, now_iso()))
        return True

    def s_sup_result_noted(self, r):
        """v10.18.0: the poller's Support result, handled exactly as before (api_support.py is untouched: a test pins it), and then, when an ADD finished with the new clip's ID, that clip goes into the story's list at once.
        A problem here never changes the answer the poller gets."""
        out = self.s_sup_result(r); b = r.body
        try:
            if out.get("ok") and b.get("state") == "DONE" and isinstance(b.get("result"), dict) and b["result"].get("clip_id"):
                with self.db.tx() as cur:
                    j = cur.one("SELECT kind, blaze_story_id, media_id, media_name FROM support_jobs WHERE id=?", (int(b["id"]),))
                    if j and j["kind"] == "ADD": self.note_added(cur, j["blaze_story_id"], b["result"]["clip_id"], b["result"].get("mos") or j["media_id"], j["media_name"])
        except Exception: pass
        return out

    def a_hand_preview(self, r):
        """v10.18.0: Play preview of a clip that is in the story in Blaze but was not made by Storigen (added with the + / Add media button or by hand). Storigen does not hold its file,
        so the file is looked for by the clip's name in the Nitro ONAIR day folder(s) every time it is asked for (nothing is remembered, stored or cached), then streamed exactly like any other preview."""
        sid, cid = str(r.q.get("story") or "").strip(), str(r.q.get("clip") or "").strip()
        if not sid or not cid: raise HttpError(400, "story and clip are needed")
        with self.db.tx() as cur: stored, _seen = self.stored_clips(cur, sid)
        c = next((x for x in stored if str(x.get("id")) == cid), None)
        if not c: raise HttpError(404, "Blaze does not list this clip in the story any more (it may have been deleted). The page refreshes by itself.")
        title = (c.get("title") or "").strip()
        if not title: raise HttpError(404, "This clip has no name in Blaze, so its file cannot be looked for on Nitro")
        path, where = preview.find_nitro_file(title)
        if not path: raise HttpError(404, "No file named %s was found in the Nitro ONAIR folder (looked in: %s). It may not be on Nitro yet, or it has another name there." % (title, where))
        return preview.open_stream(path)

    @staticmethod
    def stored_clips(cur, sid):
        """-> (clips, seen_at) the poller last reported for this Blaze story; ([], None) when it never did."""
        x = cur.one("SELECT clips, seen_at FROM story_blaze_clips WHERE blaze_story_id=?", (str(sid),))
        if not x: return [], None
        try: v = json.loads(x["clips"])
        except ValueError: v = []
        return (v if isinstance(v, list) else []), x["seen_at"]

    @staticmethod
    def hand_clips_of(stored, sib):
        """The Blaze clips of a story that the registry does not account for. sib: the registry rows of the story (blaze_clip_id, mos_object_id, state, replaced_at)."""
        ids = {str(x.get("blaze_clip_id")) for x in sib if x.get("blaze_clip_id")}
        mos = {str(x.get("mos_object_id")) for x in sib if x.get("mos_object_id") and x.get("state") == "ATTACHED" and not x.get("replaced_at")}
        return [c for c in stored if str(c.get("id")) not in ids and str(c.get("mos") or "") not in mos]

    def hand_cards(self, stored, sib, sid=None):
        out = []
        for c in self.hand_clips_of(stored, sib):
            out.append({"id": None, "display_id": None, "name_id": c.get("title") or ("clip " + str(c.get("id"))), "version": 0, "role": "hand", "label": "ADDED", "state": "ATTACHED", "mos_object_id": c.get("mos") or None, "item_id": None,
                        "attach_dur": None, "blaze_clip_id": str(c.get("id")), "replaced": False, "replaced_by": None, "on_nitro": False, "duration_s": c.get("dur_s"), "file": None, "by_hand": True, "blaze_story_id": str(sid) if sid else None})
        return out

    def hand_counts(self, cur, rows):
        """{registry story id: how many clips Blaze holds in it that the registry does not account for} for the dashboard's clip total."""
        ids = sorted({x["story_id"] for x in rows}); sid_of = {x["story_id"]: x.get("blaze_story_id") for x in rows}; out = {}
        for i in range(0, len(ids), 400):
            part = ids[i:i + 400]; sib = {}
            for y in cur.q("SELECT story_id, blaze_clip_id, media_id AS mos_object_id, state, replaced_at FROM clip_ids WHERE story_id IN (%s)" % ",".join("?" * len(part)), part): sib.setdefault(y["story_id"], []).append(y)
            for st in part:
                sid = sid_of.get(st)
                if not sid or str(sid).startswith("manual-"): continue
                stored, _ = self.stored_clips(cur, sid)
                if stored:
                    n = len(self.hand_clips_of(stored, sib.get(st, [])))
                    if n: out[st] = n
        return out

    def blaze_clips_now(self, r, rid, sid, wait=8.0):
        """The chat asks Blaze for the real clip list of a story: the same read-only LIST request the Delete button uses, answered by the poller. -> (clips, how, seen_at, note).
        how: 'blaze' (read just now), 'poller' (what the poller last saw; Blaze did not answer in time), 'none' (never seen)."""
        jid = None
        try:
            self.sup_on()
            with self.db.tx() as cur:
                hb = cur.one("SELECT ts FROM heartbeats WHERE component='blaze_poll'")
                if not hb or time.time() - float(hb["ts"]) > 180: raise HttpError(503, "the poller is not running: nobody would answer")      # no waiting for a poller that is not there
                st = self.sup_story(cur, rid, sid); self.sup_expire(cur)
                old = cur.one("SELECT id FROM support_jobs WHERE kind='LIST' AND state IN ('QUEUED','WORKING') AND blaze_story_id=? AND blaze_rundown_id=? ORDER BY id DESC LIMIT 1", (st["blaze_story_id"], st["blaze_rundown_id"]))
                jid = old["id"] if old else cur.insert("""INSERT INTO support_jobs(kind,state,by_user,created_at,updated_at,expires_at,blaze_rundown_id,rundown,blaze_story_id,story) VALUES('LIST','QUEUED',?,?,?,?,?,?,?,?)""",
                    ((r.user or {}).get("username") or "bot", now_iso(), now_iso(), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)), st["blaze_rundown_id"], st["rundown"], st["blaze_story_id"], self.sup_title(st)))
        except HttpError: jid = None
        end = time.time() + wait
        while jid and time.time() < end:
            with self.db.tx() as cur: j = cur.one("SELECT state, result, msg FROM support_jobs WHERE id=?", (jid,))
            if j and j["state"] == "DONE":
                try: res = json.loads(j["result"] or "{}")
                except ValueError: res = {}
                return [{"id": str(c.get("id")), "mos": str(c.get("mos") or ""), "title": c.get("title") or "", "dur_s": c.get("dur_s")} for c in res.get("clips", [])], "blaze", now_iso(), None
            if j and j["state"] in ("FAILED", "BLOCKED", "EXPIRED"): break
            time.sleep(0.25)
        with self.db.tx() as cur: stored, seen = self.stored_clips(cur, sid)
        if stored: return stored, "poller", seen, "Blaze did not answer in time. This is the clip list the poller last saw (%s)." % (seen or "earlier")
        return [], "none", None, "Blaze did not answer and the poller has not reported this story's clips yet, so clips added by hand cannot be seen."
