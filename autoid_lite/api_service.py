"""Server methods for the feeds (poller, watcher, MOS gateway): story sync, files, media, attach confirmation, quick-attach, status."""
from __future__ import annotations
from .ids import check_char, enc_version, id_format, kind_of, name_base, norm_name, split_suffix, vlabel
import datetime as dt, json, time
from .db import now_iso
from .common import APP_VERSION, HttpError, STATES, opt

class ServiceMixin:
    def h_healthz(self, r):
        with self.db.tx() as cur: cur.one("SELECT 1 AS ok")
        return {"ok": True, "version": APP_VERSION}
    def s_story(self, r):
        b = r.body; self.need(b, "blaze_rundown_id", "blaze_story_id"); notes = []
        with self.db.tx() as cur:
            rid = self.get_rundown(cur, b["blaze_rundown_id"], b.get("rundown_name"))
            out = self.upsert_story_row(cur, rid, b["blaze_story_id"], b.get("slug") or "", opt(b.get("slug_id")), opt(b.get("position")), notes=notes)[0]
        self.tell_renames(notes, b.get("rundown_name") or b["blaze_rundown_id"])
        return out
    def tell_renames(self, notes, where):
        """v10.9.1: after the transaction, tell the desk about every story renamed in Blaze and the clip name that followed it."""
        for n in notes:
            if n.get("renamed"): self.alert("Story renamed in Blaze (%s): '%s' -> '%s'. The clip name is now %s (was %s). Name the file with the NEW name; a file with the old name is refused." % (where, n["from"], n["to"], ", ".join(b for _, b in n["renamed"]), ", ".join(a for a, _ in n["renamed"])))
    def s_sync(self, r):
        """The COMPLETE story list of one rundown (roCreate / roReplace): create or refresh every listed story, remove the rest and hold their clips."""
        b = r.body; self.need(b, "blaze_rundown_id"); notes = []
        with self.db.tx() as cur:
            rid = self.get_rundown(cur, b["blaze_rundown_id"], b.get("rundown_name"), opt(b.get("rundown_start"))); seen, created, restored = [], 0, 0
            moved = self.adopt_replaced(cur, rid, b.get("stories") or [])
            for st in b.get("stories") or []:
                if not st.get("blaze_story_id"): continue
                _, c, rs = self.upsert_story_row(cur, rid, st["blaze_story_id"], st.get("slug") or "", opt(st.get("slug_id")), opt(st.get("position")), st.get("story_title") or None, notes=notes, old_key=moved.get(st["blaze_story_id"])); seen.append(st["blaze_story_id"]); created += c; restored += rs
            ids, held = self.remove_stories(cur, rid, "rundown replaced", keep=seen)
            if created or restored or ids or held: self.log(cur, "mos", "rundown_synced", {"rundown": b["blaze_rundown_id"], "stories": len(seen), "created": created, "restored": restored, "removed": len(ids), "held": held})
        self.tell_renames(notes, b.get("rundown_name") or b["blaze_rundown_id"])
        if held: self.alert("Rundown %s: %d stories removed in Blaze; %d clips already on Nitro are now NEEDS DESK (%s). Desk: check them before attaching." %
                            (b.get("rundown_name") or b["blaze_rundown_id"], len(ids), len(held), ", ".join(held[:8]) + (" ..." if len(held) > 8 else "")))
        return {"stories": len(seen), "created": created, "restored": restored, "removed": len(ids), "held": held}
    def adopt_replaced(self, cur, rid, stories):
        """v10.9.2: Blaze gives a story renamed in the rundown a NEW story ID in the same slug. Without this the old story was struck out (removed) and a second row was made. Now, when a story ID we do not know takes over a slug that
        holds a story that is no longer listed, and every clip of that old story is still WAITING_FOR_CLIP (no file seen, nothing sent), the old row is kept and moves to the new story ID: its clip keeps its ID and, through the
        title change that follows, gets the new name. Anything else (a clip with a file, two candidates, no slug ID) stays as before: struck out and a new row. -> {new story id: old story id}"""
        incoming = {str(x["blaze_story_id"]) for x in stories if x.get("blaze_story_id")}; moved, taken = {}, set()
        for st in stories:
            nid, slug_id = str(st.get("blaze_story_id") or ""), opt(st.get("slug_id"))
            if not nid or not slug_id or cur.one("SELECT 1 AS x FROM stories WHERE rundown_id=? AND blaze_story_id=?", (rid, nid)): continue
            cand = [c for c in cur.q("SELECT id, blaze_story_id FROM stories WHERE rundown_id=? AND slug_id=? AND deleted=0", (rid, slug_id)) if c["blaze_story_id"] not in incoming and c["id"] not in taken]
            if len(cand) != 1: continue
            old = cand[0]; states = [x["state"] for x in cur.q("SELECT state FROM clip_ids WHERE story_id=?", (old["id"],))]
            if not states or any(x != "WAITING_FOR_CLIP" for x in states): continue
            cur.x("UPDATE stories SET blaze_story_id=? WHERE id=?", (nid, old["id"])); taken.add(old["id"]); moved[nid] = old["blaze_story_id"]
            self.log(cur, "mos", "story_id_changed", {"blaze_rundown_id": rid, "old_id": old["blaze_story_id"], "new_id": nid, "slug_id": slug_id, "why": "renamed in the rundown (new story ID in the same slug, clip still waiting)"})
        return moved
    def s_rename(self, r):
        b = r.body; self.need(b, "blaze_rundown_id", "old_id", "new_id")
        with self.db.tx() as cur:
            rid = self.get_rundown(cur, b["blaze_rundown_id"])
            if cur.one("SELECT 1 AS x FROM stories WHERE rundown_id=? AND blaze_story_id=?", (rid, b["new_id"])):
                self.log(cur, "mos", "story_rename_skipped", b); return {"updated": 0}
            n = cur.x("UPDATE stories SET blaze_story_id=? WHERE rundown_id=? AND blaze_story_id=?", (b["new_id"], rid, b["old_id"]))
            self.log(cur, "mos", "story_id_changed", b); return {"updated": n}
    def s_delete(self, r):
        b = r.body; self.need(b, "blaze_rundown_id")
        with self.db.tx() as cur:
            rid = self.get_rundown(cur, b["blaze_rundown_id"])
            ids, held = self.remove_stories(cur, rid, "story deleted" if b.get("blaze_story_id") else "rundown deleted", only=b.get("blaze_story_id") or None)
        if held: self.alert("Rundown %s: %d stories removed in Blaze; %d clips already on Nitro are now NEEDS DESK (%s). Desk: check them before attaching." %
                            (b["blaze_rundown_id"], len(ids), len(held), ", ".join(held[:8])))
        return {"updated": len(ids), "held": held}
    def s_match(self, r):
        """Match on date + number only (legacy IDs; if a check letter was typed it must be right), or on the whole ID with ?name=DDMMYY_STORY_NAME (case does not matter)."""
        q = r.q
        if q.get("name"):
            name = self.canon_name(q["name"]); fresh = False
            with self.db.tx() as cur:
                rows = self.name_rows(cur, name)
                if not rows: rows = self.auto_versions(cur, name); fresh = bool(rows)      # v10.5.0: a _U01 / _V01 file whose clip has no entry yet gets one here (VERSION_SUFFIX=on)
                if not rows:                                                                # v10.9.1: the name the story had before it was renamed in Blaze: say what it is called now
                    sp = split_suffix(norm_name(name)); h = self.old_name_hint(cur, name); tail = ""
                    if not h and sp: h = self.old_name_hint(cur, sp[0]); tail = "_%s%02d" % (sp[1], sp[2])
                    if h: self.refused[name] = "this story was renamed in Blaze: the clip name is now %s%s, not %s. Name the file %s%s" % (h["cur"], tail, h["old"] + tail, h["cur"], tail)
            if fresh: self.alert("%s detected from the file name: clip ID %s made for %d stor%s." % ("UPDATE (replaces the story's main clip)" if kind_of(rows[0]["version"]) == "U" else "NEW CLIP (added beside the clips already in the story)", rows[0]["name_id"], len(rows), "y" if len(rows) == 1 else "ies"))
            if not rows: raise HttpError(404, self.refused.pop(name, None) or "no such clip id")
            return dict(rows[0], group=[x["display_id"] for x in rows])      # one clip name can belong to several stories: the file event is applied to all of them
        try: d = dt.datetime.strptime(q["day"], "%Y%m%d").date(); seq = int(q["seq"]); ver = int(q.get("version", 1))
        except (KeyError, ValueError): raise HttpError(422, "day (YYYYMMDD), seq and version are required")
        if q.get("chk") and q["chk"] != check_char(d, seq): raise HttpError(422, "check character mismatch: the ID was probably mistyped")
        with self.db.tx() as cur: row = cur.one("SELECT * FROM clip_ids WHERE day=? AND seq=? AND version=?", (d.isoformat(), seq, ver))
        if not row: raise HttpError(404, "no such clip id")
        return row
    @staticmethod
    def canon_name(name):
        """v10.5.0: 111126_fire_u2 and 111126_FIRE_U02 are one clip name (VERSION_SUFFIX=on); anything else is returned unchanged."""
        sp = split_suffix(norm_name(name)); return name if not sp else "%s_%s%02d" % sp
    refused = {}                  # v10.7.0: clip name -> why no clip ID was made for it (the 404's detail; the watcher puts it in its alert)
    AIRED_GRACE_MIN = 60          # v10.7.0: a bulletin that started more than this many minutes ago has aired: a new update / clip is not made for its story
    @staticmethod
    def aired(start_at):
        try: st = dt.datetime.fromisoformat(start_at)
        except (TypeError, ValueError): return False
        if st.tzinfo is None: st = st.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - st).total_seconds() > ServiceMixin.AIRED_GRACE_MIN * 60
    def auto_versions(self, cur, name):
        """v10.5.0, VERSION_SUFFIX=on: the file 111126_FIRE_U02.mxf has been seen and no clip of that name exists. When the plain clip 111126_FIRE exists, the stories that hold it get a clip entry for this
        version (under the same day and number as the plain clip, so the database's own uniqueness stops a second one). Nothing else changes.
        v10.7.0, two rules so that a typo or a late file does no harm: (1) the number must be the NEXT one of its kind (_U01 first, then _U02; _U07 with no _U06 is refused, with the reason in self.refused);
        (2) stories of bulletins that have already aired are skipped (they keep what they have); if every bulletin has aired, the newest one's story gets it.
        Returns the new rows, or [] when the name has no suffix, the plain clip is unknown (a typo stays a 404), the number is not the next one, or the ID format is legacy."""
        sp = split_suffix(norm_name(name))
        if not sp or id_format() != "name": return []
        base, kind, n = sp; ver = enc_version(kind, n); plain = self.name_rows(cur, base)
        if not plain: return []
        top = 0
        for x in cur.q("SELECT version, COALESCE(name_id, display_id) AS nm FROM clip_ids WHERE UPPER(COALESCE(name_id, display_id)) LIKE ? ESCAPE '\\'", (base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "\\_%",)):
            if kind_of(x["version"]) == kind and name_base(x["nm"]).upper() == base: top = max(top, x["version"] % 1000)      # not 111126_FIRE_2's own updates
        if n != top + 1:
            self.refused[name] = "%s is not the next number: the next %s for %s is %s%02d" % (name, "update" if kind == "U" else "added clip", base, kind, top + 1); return []
        live = []
        for x in plain:
            st = cur.one("SELECT s.slug, s.deleted, ru.start_at FROM stories s JOIN rundowns ru ON ru.id=s.rundown_id WHERE s.id=?", (x["story_id"],))
            if not st or st["deleted"] or cur.one("SELECT id FROM clip_ids WHERE story_id=? AND version=?", (x["story_id"], ver)): continue
            live.append((st["start_at"] or "", x, st))
        live.sort(key=lambda t: (t[0], t[1]["id"])); targets = [t for t in live if not self.aired(t[0])] or live[-1:]
        made = [self.new_clip(cur, x["story_id"], st["slug"], dt.date.fromisoformat(x["day"]), x["seq"], ver, name="%s_%s%02d" % (base, kind, n)) for _, x, st in targets]
        if made: self.log(cur, "watcher", "version_auto", {"name_id": made[0]["name_id"], "kind": kind, "stories": len(made), "skipped_aired": len(live) - len(targets), "from_file": True})
        return made
    def s_replaced(self, r):
        """v10.7.0: the poller attached an update (_Un) and removed the older main clip from the story, verified. The older clip IDs (one per bulletin of that story) are marked replaced, so the dashboard
        says so and the story's clip count is right. display_id = the update; replaced = the older clips' display_ids, all of the SAME Blaze story."""
        b = r.body; self.need(b, "display_id", "replaced")
        if not isinstance(b["replaced"], list): raise HttpError(422, "replaced must be a list of display_id")
        with self.db.tx() as cur:
            new = cur.one("SELECT c.id, c.display_id, s.blaze_story_id FROM clip_ids c JOIN stories s ON s.id=c.story_id WHERE c.display_id=?", (b["display_id"],))
            if not new: raise HttpError(404, "unknown display_id")
            done = []
            for did in b["replaced"][:50]:
                old = cur.one("SELECT c.id, c.display_id, c.replaced_at, s.blaze_story_id FROM clip_ids c JOIN stories s ON s.id=c.story_id WHERE c.display_id=?", (did,))
                if not old or old["blaze_story_id"] != new["blaze_story_id"] or old["id"] == new["id"] or old["replaced_at"]: continue
                cur.x("UPDATE clip_ids SET replaced_at=?, replaced_by=? WHERE id=?", (now_iso(), new["display_id"], old["id"])); done.append(old["display_id"])
            if done: self.log(cur, "blaze", "clip_replaced", {"by": new["display_id"], "replaced": done, "blaze_story_id": new["blaze_story_id"]})
        return {"ok": True, "marked": len(done)}
    def s_files(self, r):
        f = r.body; self.need(f, "display_id", "state")
        if f["state"] not in STATES: raise HttpError(400, "bad state")
        with self.db.tx() as cur:
            c = cur.one("SELECT id, display_id, name_id FROM clip_ids WHERE display_id=?", (f["display_id"],))
            if not c: raise HttpError(404, "unknown display_id")
            rows = self.name_rows(cur, c["name_id"]) if c["name_id"] else [c]      # a clip name shared by several stories: the file belongs to all of them
            st = f["state"]
            for x in rows:
                cur.x("INSERT INTO files(clip_id,nas_path,nitro_path,size,sha256,state,error,duration_s,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (x["id"], f.get("nas_path"), f.get("nitro_path"), f.get("size"), f.get("sha256"), st, f.get("error"), f.get("duration_s"), now_iso()))
                cur.x("""UPDATE clip_ids SET state=?, verified_at=CASE WHEN ?='VERIFIED' THEN ? ELSE verified_at END, on_nitro_at=CASE WHEN ?='ON_NITRO' THEN ? ELSE on_nitro_at END
                         WHERE id=? AND state NOT IN ('ATTACHED','ATTACH_SUBMITTED') AND NOT (?='VERIFIED' AND state IN ('ON_NITRO','NEEDS_DESK'))""",
                      (st, st, now_iso(), st, now_iso(), x["id"], st))
                if st == "ON_NITRO" and self.story_removed(cur, x["display_id"]): self.hold_one(cur, x["display_id"], "the clip reached Nitro after its story was removed")
            self.log(cur, "watcher", "file_" + st.lower(), dict(f, stories=len(rows)))
        return {"ok": True, "clips": len(rows)}
    def s_alert(self, r):
        """A component (the Blaze poller) asks for an alert: expired session, live attach halted. Same channels as the server's own alerts."""
        b = r.body; self.need(b, "text"); text = str(b["text"])[:500]; self.alert(text)
        with self.db.tx() as cur: self.log(cur, "svc", "alert", {"text": text[:200]})
        return {"ok": True}
    def s_heartbeat(self, r):
        b = r.body; self.need(b, "component")
        with self.db.tx() as cur:
            cur.x("INSERT INTO heartbeats(component,ts,detail) VALUES(?,?,?) ON CONFLICT(component) DO UPDATE SET ts=excluded.ts, detail=excluded.detail",
                  (b["component"], time.time(), json.dumps(b.get("detail") or {})))
        return {"ok": True}
    def s_why(self, r):
        """v9.13.1: the poller says, per waiting clip, why it is not attached yet. Kept in memory (the poller sends the whole list again every few seconds); shown on the dashboard card."""
        b = r.body; self.need(b, "why")
        if not isinstance(b["why"], dict): raise HttpError(422, "why must be an object {clip ID: text}")
        self.why = ({str(k): str(v)[:300] for k, v in list(b["why"].items())[:5000]}, time.time()); return {"ok": True}
    SCRIPT_CAP = 20000
    def s_scripts(self, r):
        """v9.13.2: the poller sends the two script fields it read from Blaze (storyComplete versions[0].items[].text1 / text2) for up to 200 stories at a time:
        {"stories": [{"blaze_story_id", "online", "anchor"}]}. A story that sits in several bulletins has one row each: all of them are filled. Only a changed text is written; a story the registry does not know is skipped."""
        b = r.body; self.need(b, "stories")
        if not isinstance(b["stories"], list): raise HttpError(422, "stories must be a list")
        txt = lambda v: v[: self.SCRIPT_CAP] if isinstance(v, str) else ""
        n = 0
        with self.db.tx() as cur:
            for x in b["stories"][:200]:
                if not isinstance(x, dict) or not x.get("blaze_story_id"): continue
                o, a = txt(x.get("online")), txt(x.get("anchor"))
                n += cur.x("UPDATE stories SET online_script=?, anchor_script=?, script_at=? WHERE blaze_story_id=? AND (script_at IS NULL OR COALESCE(online_script,'')<>? OR COALESCE(anchor_script,'')<>?)", (o, a, now_iso(), str(x["blaze_story_id"]), o, a))
                who = [str(x.get(k) or "").strip()[:80] or None for k in ("created_by", "created_by_id", "assigned_to", "assigned_to_id")]      # v10.9.0: sent by the same read; a field the story does not carry never wipes what is stored
                if any(who): cur.x("UPDATE stories SET created_by=COALESCE(?,created_by), created_by_id=COALESCE(?,created_by_id), assigned_to=COALESCE(?,assigned_to), assigned_to_id=COALESCE(?,assigned_to_id) WHERE blaze_story_id=?", (*who, str(x["blaze_story_id"])))
        return {"ok": True, "updated": n}
    def s_media(self, r):
        """The poller found this clip's file in Blaze's media list (its mosObjectId): the NITRO stage turns green. Records the fact only; it changes no state and attaches nothing."""
        b = r.body; self.need(b, "display_id", "media_id"); mid = str(b["media_id"])[:64]; mname = (str(b.get("media_name") or "").strip()[:200]) or None; push = None
        with self.db.tx() as cur:
            c = cur.one("SELECT id, display_id, name_id FROM clip_ids WHERE display_id=?", (b["display_id"],))
            if not c: raise HttpError(404, "unknown display_id")
            rows = self.name_rows(cur, c["name_id"]) if c["name_id"] else [c]
            fresh = []                                                                        # rows for which this media object is new (the first time, or a replaced file)
            for x in rows:
                old = cur.one("SELECT media_id, state FROM clip_ids WHERE id=?", (x["id"],))
                if old["media_id"] != mid: fresh.append((x, old["state"]))
                cur.x("UPDATE clip_ids SET media_id=?, media_found_at=COALESCE(media_found_at, ?), media_name=COALESCE(?, media_name) WHERE id=?", (mid, now_iso(), mname, x["id"]))
            if fresh:                                                                         # a repeat of the same media object (or a name backfill) is not news: no event, no message
                self.log(cur, "blaze", "media_found", {"display_id": c["display_id"], "media_id": mid, "media_name": mname, "stories": len(rows)})
                todo = [x for x, st in fresh if st != "ATTACHED"]                              # nobody needs telling about a clip that is already in the story
                if todo:
                    i = cur.one("SELECT s.slug, s.story_title, ru.name AS rundown, c.version FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id WHERE c.id=?", (todo[0]["id"],)) or {}
                    tag = {"U": "UPDATED clip READY on Nitro (will replace the main clip)", "V": "ADDED clip READY on Nitro (goes beside the clips already there)"}.get(kind_of(i.get("version")), "READY on Nitro")
                    push = tag + ": %s | clip %s | MOS %s | media %s%s%s" % (i.get("story_title") or i.get("slug") or "-", c["name_id"] or c["display_id"], mid, mname or "-",
                           (" | " + i["rundown"]) if i.get("rundown") else "", (" | +%d more stor%s with this clip" % (len(todo) - 1, "y" if len(todo) == 2 else "ies")) if len(todo) > 1 else "")
        if push: self.ready_notify(push)
        return {"ok": True, "clips": len(rows)}
    @staticmethod
    def attach_info(b):
        """What Blaze shows for the attached clip: (mosObjectId, itemId, duration in seconds, Blaze clip id); None where the caller did not know."""
        t = lambda v: None if v in (None, "") else str(v)[:64]
        d = b.get("duration_s"); return t(b.get("mos_object_id")), t(b.get("item_id")), (int(d) if isinstance(d, (int, float)) and not isinstance(d, bool) and d >= 0 else None), t(b.get("blaze_clip_id"))
    def s_confirm(self, r):
        """Blaze itself reported that this clip object sits in a story. Accept only if it is the RIGHT story; a wrong story needs a human."""
        b = r.body; self.need(b, "display_id", "blaze_rundown_id", "blaze_story_id")
        with self.db.tx() as cur:
            sel = """SELECT c.id, c.display_id, c.state, s.blaze_story_id, ru.blaze_rundown_id FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id """
            c = cur.one(sel + "WHERE c.display_id=?", (b["display_id"],))
            if not c:                                                           # Blaze names the clip by the shared clip NAME: take the row of THIS story, else any row of that name (then it is the wrong story)
                key = b["display_id"].strip().upper()
                c = cur.one(sel + "WHERE UPPER(COALESCE(c.name_id, c.display_id))=? AND s.blaze_story_id=? AND ru.blaze_rundown_id=?", (key, b["blaze_story_id"], b["blaze_rundown_id"])) \
                    or cur.one(sel + "WHERE UPPER(COALESCE(c.name_id, c.display_id))=? ORDER BY c.id", (key,))
            if not c: raise HttpError(404, "unknown display_id")
            b = dict(b, display_id=c["display_id"], clip_name=b["display_id"])
            info = self.attach_info(b)
            if c["state"] == "ATTACHED":                                        # already attached (by the desk, or before this version): only fill in what Blaze shows now, never change the state
                if any(v is not None for v in info) and c["blaze_story_id"] == b["blaze_story_id"] and c["blaze_rundown_id"] == b["blaze_rundown_id"]:
                    cur.x("UPDATE clip_ids SET media_id=COALESCE(media_id, ?), item_id=COALESCE(item_id, ?), attach_dur=COALESCE(attach_dur, ?), blaze_clip_id=COALESCE(blaze_clip_id, ?) WHERE id=?", info + (c["id"],))
                return {"ok": True, "state": "ATTACHED", "note": "already attached"}
            if c["blaze_story_id"] != b["blaze_story_id"] or c["blaze_rundown_id"] != b["blaze_rundown_id"]:
                msg = "WRONG STORY: Blaze shows %s in %s/%s, registry expects %s/%s" % (b["clip_name"], b["blaze_rundown_id"], b["blaze_story_id"], c["blaze_rundown_id"], c["blaze_story_id"])
                cur.x("UPDATE clip_ids SET state='NEEDS_DESK', attach_error=? WHERE id=?", (msg, c["id"])); self.log(cur, "attach", "attach_wrong_story", b); self.alert(msg)
                return {"ok": False, "state": "NEEDS_DESK", "error": msg}
            if c["state"] not in ("ATTACH_SUBMITTED", "ON_NITRO", "NEEDS_DESK") + (("WAITING_FOR_CLIP", "EXPORTING", "VERIFIED") if (b.get("source") == "blaze_live" or (b.get("source") == "blaze_readback" and b.get("media_mode") is True)) else ()): return {"ok": False, "state": c["state"], "note": "clip not in an attachable state"}
            if self.story_removed(cur, b["display_id"]):
                self.hold_one(cur, b["display_id"], "Blaze read-back arrived for a story the registry has as removed"); return {"ok": False, "state": "NEEDS_DESK", "error": "story removed in registry"}
            cur.x("""UPDATE clip_ids SET state='ATTACHED', attached_at=?, attach_method=?, attach_error=NULL, media_id=COALESCE(?, media_id), item_id=COALESCE(?, item_id), attach_dur=COALESCE(?, attach_dur),
                     blaze_clip_id=COALESCE(?, blaze_clip_id), media_found_at=COALESCE(media_found_at, ?) WHERE id=?""", (now_iso(), (b.get("source") or "mos_item") + "+verified") + info + (now_iso(), c["id"]))
            self.log(cur, "blaze", "attached_verified", b); return {"ok": True, "state": "ATTACHED"}
    QA_STATES = ("WAITING_FOR_CLIP", "EXPORTING", "VERIFIED", "ON_NITRO")                    # a clip the tool may still attach (same list as the poller's LIVE_STATES)
    def a_quickattach(self, r):
        """v9.13 dashboard "Quick test attach" (after the editor answered Yes): ask the poller to attach THIS ONE clip to its story for real, even while BLAZE_ATTACH=dry.
        Only when the NITRO step is green (Blaze's media object was found). Nothing is sent from here: the request is recorded and the poller, which owns the Blaze session and every safety check, does the attach and reports back."""
        if not self.cfg["quick_attach"]: raise HttpError(403, "Quick test attach is switched off (QUICK_TEST_BUTTON=0)")
        if (r.body or {}).get("confirm") is not True: raise HttpError(400, "confirmation missing: the editor must answer Yes")
        cid = int(r.m[0])
        with self.db.tx() as cur:
            c = cur.one("""SELECT c.id, c.display_id, c.state, c.media_id, c.media_found_at, c.qa_state, s.deleted, s.blaze_story_id, ru.blaze_rundown_id, ru.name AS rundown
                           FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id WHERE c.id=?""", (cid,))
            if not c: raise HttpError(404, "unknown clip")
            if c["blaze_rundown_id"].startswith("name:") or c["blaze_story_id"].startswith("manual-"): raise HttpError(409, "this story was typed by hand: it has no real Blaze story to attach to")
            if c["deleted"]: raise HttpError(409, "the story is no longer in the rundown in Blaze")
            if c["state"] == "ATTACHED": raise HttpError(409, "already attached")
            if c["state"] not in self.QA_STATES: raise HttpError(409, "the clip is %s: quick test attach is only for a clip that is waiting to be attached" % c["state"])
            if not c["media_found_at"] or not c["media_id"]: raise HttpError(409, "NITRO is not green yet: Blaze's media object for this clip has not been found, so there is nothing to attach")
            if c["qa_state"] == "REQUESTED": raise HttpError(409, "a quick test for this clip is already waiting for the poller")
            cur.x("UPDATE clip_ids SET qa_state='REQUESTED', qa_by=?, qa_at=?, qa_msg=NULL WHERE id=?", (r.user["username"], now_iso(), cid))
            self.log(cur, r.user["username"], "quickattach_requested", {"display_id": c["display_id"], "blaze_story_id": c["blaze_story_id"], "show": c["blaze_rundown_id"], "media_id": c["media_id"]})
            return {"ok": True, "state": "REQUESTED", "display_id": c["display_id"]}
    def s_qa_result(self, r):
        """The poller's answer to a quick test: SENT (attached and read back), BLOCKED (a safety rule said no, nothing was sent) or FAILED."""
        b = r.body; self.need(b, "display_id", "status")
        if b["status"] not in ("SENT", "BLOCKED", "FAILED"): raise HttpError(422, "status must be SENT, BLOCKED or FAILED")
        with self.db.tx() as cur:
            c = cur.one("SELECT id, display_id FROM clip_ids WHERE display_id=?", (b["display_id"],))
            if not c: raise HttpError(404, "unknown display_id")
            cur.x("UPDATE clip_ids SET qa_state=?, qa_msg=? WHERE id=?", (b["status"], str(b.get("message") or "")[:500], c["id"]))
            self.log(cur, "blaze", "quickattach_" + b["status"].lower(), {"display_id": c["display_id"], "message": str(b.get("message") or "")[:500]})
        return {"ok": True}
    def s_status(self, r):
        h = self.compute_health()
        return {"problems": [m for _, (ok, m) in h.items() if not ok], "checks": {n: ok for n, (ok, _) in h.items()}, "day": self.today().isoformat(), "day_ends": self.day_ends().isoformat(timespec="seconds")}
    def day_ends(self):
        """When the current broadcast day ends (the next BROADCAST_DAY_START), with the server's UTC offset."""
        h, m = (int(x) for x in self.cfg["day_start"].split(":")); n = self.now()
        end = (n - dt.timedelta(hours=h, minutes=m)).replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1, hours=h, minutes=m)
        return end.replace(tzinfo=self._tz) if (self.cfg["tz"] and self._tz is not None) else end.astimezone()      # now() is wall-clock time: give it AUTOID_TZ's offset, or the machine's own when no zone is set
    def s_clips(self, r):
        d = dt.datetime.strptime(r.q["day"], "%Y%m%d").date() if r.q.get("day") else self.today()
        try: lim = min(20000, max(1, int(r.q.get("limit") or 5000)))          # was 500: a day of 36 shows holds 540 to 720 stories (and versions), so a reader would have missed clips beyond the 500th
        except ValueError: raise HttpError(422, "limit must be a number")
        with self.db.tx() as cur: return cur.q("""SELECT c.display_id, COALESCE(c.name_id, c.display_id) AS name_id, c.media_id AS mos_object_id, c.item_id, c.attach_dur, c.blaze_clip_id, c.state, c.version, c.attach_error, c.qa_state, c.qa_by, c.qa_at, s.blaze_story_id, s.slug_id, s.position, s.slug, s.deleted, ru.blaze_rundown_id
                                    FROM clip_ids c JOIN stories s ON s.id=c.story_id JOIN rundowns ru ON ru.id=s.rundown_id
                                    WHERE c.day=? ORDER BY c.seq, c.id LIMIT ?""", (d.isoformat(), lim))

    # ---------- health and alerts ----------
    def compute_health(self):
        with self.db.tx() as cur: hb = {x["component"]: x for x in cur.q("SELECT * FROM heartbeats")}
        now, res = time.time(), {}
        for c in self.cfg["components"]:
            x = hb.get(c)
            res[c] = (False, "%s has never reported" % c) if x is None else (now - x["ts"] < self.cfg["stale"], "%s last seen %ds ago" % (c, now - x["ts"]))
        g = hb.get("gateway")
        if g and "gateway" in self.cfg["components"] and self.cfg["blaze_silent"] > 0:
            d = json.loads(g["detail"] or "{}"); la, up = d.get("last_mos_age"), d.get("uptime", 0)
            res["blaze_link"] = ((la is not None and la <= self.cfg["blaze_silent"]) or (la is None and up < self.cfg["blaze_silent"]),
                                 "no MOS traffic from Blaze for %s s" % (int(la) if la is not None else "any"))
            if d.get("spool_dead", 0) > 0: res["gateway_queue"] = (False, "the MOS gateway gave up on %d messages for the registry (see spool.dead.jsonl); stories may be out of date" % d["spool_dead"])
        w = hb.get("watcher")
        if w and "watcher" in self.cfg["components"]:                  # v9.12: an old heartbeat of a watcher that is switched off must not keep a red warning
            wd = json.loads(w["detail"] or "{}"); res["nas_nitro"] = (bool(wd.get("nas_ok", True)), wd.get("problem") or "NAS or Nitro folder not reachable from the watcher")
        bp = hb.get("blaze_poll")
        if bp:
            bd = json.loads(bp["detail"] or "{}"); res["blaze_shows"] = (not bd.get("problem"), bd.get("problem") or "")
            if bd.get("differs"): res["blaze_settings"] = (False, "autoid.env was changed but the Blaze poller still runs the old settings (%s). Restart the service to apply them." % "; ".join(bd["differs"][:3]))      # v9.13.1       # stale shows or slow polling, worked out by the poller and shown on the status pill
        return res
    def monitor(self):
        time.sleep(60); state = {}
        while True:
            try:
                for name, (ok, msg) in self.compute_health().items():
                    if state.get(name, True) != ok:
                        state[name] = ok; self.alert(("RECOVERED: %s" % name) if ok else ("DOWN: %s - %s" % (name, msg)))
                        with self.db.tx() as cur: self.log(cur, "monitor", "recovered" if ok else "down", {"check": name, "msg": msg})
            except Exception: pass
            time.sleep(30)

    # ---------- users and sessions ----------
