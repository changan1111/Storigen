"""Poller: plan the attach, the live attach itself, replace/undo of older versions, reconcile against Blaze's read-back."""
from __future__ import annotations
from pathlib import Path
import json
import time
from .errors import BlazeError, SessionExpired
from .keys import age_secs, attach_call, attached_facts, clip_secs, ignored, media_key, rkey
from .states import LIVE_STATES
from .util import say


class AttachMixin:
    def plan(self):
        """What the tool WOULD attach. Logged only (GOING TO ATTACH ...); every plan is also remembered in the ledger for the daily tool-vs-desk report."""
        qa_all = {r["display_id"]: r for r in self.rows if r.get("qa_state") == "REQUESTED"}      # v9.13: clips whose "Quick test attach" the editor confirmed on the dashboard
        self.why_map = why = {}                                                                    # v9.13.1: clip ID -> why it is not attached yet (shown on the dashboard card)
        if self.c.attach == "off":
            for r in qa_all.values(): self.quick_done(r, "BLOCKED", "BLAZE_ATTACH=off: the poller does not look at Blaze's media list, so it cannot attach")
            return []
        rows = [r for r in self.rows if not r.get("deleted") and r.get("blaze_rundown_id") in self.c.shows and not ignored(r.get("slug"), self.c.manual_titles)]
        inrows = {r["display_id"] for r in rows}
        for r in self.rows:
            if r["display_id"] in inrows or r.get("deleted") or r["state"] not in LIVE_STATES: continue
            why[r["display_id"]] = ("The poller does not follow show %s (BLAZE_SHOW_IDS)" % r.get("blaze_rundown_id")) if r.get("blaze_rundown_id") not in self.c.shows else "On the desk-only list (BLAZE_NO_AUTO_ATTACH): the desk attaches it"
        for did, r in qa_all.items():                                                              # a request the normal plan would never look at: say why, once
            if did not in inrows: self.quick_done(r, "BLOCKED", "the story was removed from the rundown" if r.get("deleted") else ("show %s is not followed by the poller (BLAZE_SHOW_IDS)" % r.get("blaze_rundown_id") if r.get("blaze_rundown_id") not in self.c.shows else "this story is on the desk-only list (BLAZE_NO_AUTO_ATTACH): the tool never attaches it"))
            elif r["state"] not in LIVE_STATES: self.quick_done(r, "BLOCKED", "the clip is %s: nothing to attach" % r["state"])
        qa_all = {d: r for d, r in qa_all.items() if d in inrows and r["state"] in LIVE_STATES}
        states = ("ON_NITRO",) if self.c.when == "watcher" else LIVE_STATES
        live = [r for r in rows if r["state"] in states or r["display_id"] in qa_all]
        back = [r for r in rows if r["state"] == "ATTACHED" and not self.led.has_plan(r["display_id"])]       # attached already (by the desk): still record what the tool would have done
        out = []; cand = live + back; self.prefetch_media(cand); looked = [(r,) + self.lookup(r) for r in cand]
        self.prefetch_info([r["blaze_story_id"] for r, st, m in looked if st == "found" and r not in back])
        for r, st, m in looked:
            did, story, show = r["display_id"], r["blaze_story_id"], r["blaze_rundown_id"]
            if st == "found": self.led.plan(did, story, show, m["id"], m["title"]); self.tell_media(did, m)
            if r in back: continue
            detail, kind, go, replace = None, None, False, None; qa = did in qa_all; qa_why = None; wtxt = None
            if st == "found":
                if story not in self.info_cache: continue                              # its details are read next pass (beyond this pass's batch, or Blaze did not answer)
                info = self.info_cache[story][1]; pos = self.pos.get(story); order = pos + 1 if isinstance(pos, int) else None
                idn = self.ident.get(story); have = {x for x, _ in info["clips"]} | ({x["mos"] for x in idn[0]} if idn else set())     # in the story by either reading
                if str(m["id"]) in have: kind, note = "ALREADY IN STORY", "clip %s: file %s is already in %s: nothing to do" % (did, m["title"], self.where(r)); qa_why = "the file is already in the story: nothing was sent"; wtxt = "The file is already in the story"
                else:
                    ver = int(r.get("version") or 1); old = self.older_versions(r, info) if ver > 1 else []
                    if ver > 1 and self.c.version_mode == "desk" and not qa:
                        kind = "NEW VERSION READY"; wtxt = "New version: the desk attaches it (BLAZE_VERSION_MODE=desk)"; have_old = ("the story still holds the older version: Blaze clip %s (%s)" % (old[0]["id"], old[0]["title"])) if len(old) == 1 else ("the story holds %d older versions of this clip" % len(old) if old else "the story holds no older version of this clip")
                        note = "clip %s is version %d: its file %s is in Blaze (%s). NOT attached by the tool (BLAZE_VERSION_MODE=desk): the desk attaches it and removes the older version's clip" % (did, ver, m["title"], have_old)
                        if self.c.attach == "live" and self.live_show(r): self.to_desk(r, "New version ready (version %d, file %s). Not attached by the tool (BLAZE_VERSION_MODE=desk): attach it by hand in Blaze and remove the older version's clip." % (ver, m["title"]))
                    else:
                        kind = "GOING TO ATTACH"; flags = []
                        if self.fmt.get(story) not in self.c.verified: flags.append("CHECK: itemId rule not yet verified for story format %s" % self.fmt.get(story))
                        if info["item_id"] is None: flags.append("CHECK: no script item found in the story, itemId unknown")
                        if order is None: flags.append("CHECK: story row position unknown")
                        if len(info["shows"]) > 1: flags.append("CHECK: story is linked in shows %s, using followed show %s" % (",".join(info["shows"]), show))
                        if len(old) > 1: flags.append("CHECK: the story holds %d older versions of this clip (%s): the tool will not choose, remove them by hand" % (len(old), ", ".join(x["id"] for x in old)))
                        sendable = self.c.attach == "live" or qa                                      # v9.13: a confirmed quick test is sent even while BLAZE_ATTACH=dry
                        block = self.live_block(r, flags, qa) if sendable else None; go = sendable and not block; qa_why = block
                        wtxt = "Being attached now" if go else ("Blocked: %s" % block if block else "Dry mode: nothing is sent by itself (BLAZE_ATTACH=dry). Use Quick test attach, or set BLAZE_ATTACH=live")
                        mode = (("QUICK TEST (confirmed on the dashboard by %s): sending now" % (r.get("qa_by") or "?")) if qa else "LIVE: sending now") if go else ("DRY RUN: nothing sent to Blaze" if not sendable else "NOT SENT (%s blocked: %s)" % ("quick test" if qa else "live", block))
                        note = "clip %s (file %s, media %s, %ds) to %s | order=%s itemId=%s%s | %s" % (
                            did, m["title"], m["id"], (m.get("duration") or 0) // 1000, self.where(r), "?" if order is None else order, info["item_id"] or "?", "".join(" | " + f for f in flags), mode)
                        detail = ("sending: " if go else "would send: ") + attach_call(story, show, m, order, info["item_id"])
                        if qa and old: note += " | QUICK TEST only ADDS this clip: the older version's clip is not removed (do that by hand)"
                        elif len(old) == 1:
                            replace = old[0]; note += " | REPLACES version %d: Blaze clip %s (%s) is removed AFTER the attach is verified" % (media_key(replace["title"])[1], replace["id"], replace["title"]); detail += "\nthen, only if the read-back is exactly right: DELETE /DataService/stories/%s/clips/%s" % (story, replace["id"])
                        elif info["rows"] and not old: note += " | the story already has %d clip(s): this one is ADDED, it does not replace them" % len(info["rows"])
                key = "%s|%s|%s|%s|%s" % (m["id"], order, info["item_id"], len(info["clips"]), ("qa|" if qa else "") + ((block or "go") if kind == "GOING TO ATTACH" and (self.c.attach == "live" or qa) else ""))
            elif st == "ambiguous": kind, key, note = "AMBIGUOUS", "|".join(sorted(str(x["id"]) for x in m)), "clip %s: %d Blaze files carry this ID (%s): desk must choose" % (did, len(m), ", ".join(x["title"] for x in m)); qa_why = "%d Blaze files carry this ID: nothing was sent" % len(m); wtxt = "%d Blaze files carry this ID: the desk must choose" % len(m)
            elif st == "converting": note, key = "clip %s: file is in Blaze but Blaze is still converting it (status NEW): waiting, checked again next round" % did, None; wtxt = "Blaze is still converting the file"
            elif st == "settling": note, key = "clip %s: file found but still changing: waiting" % did, None; wtxt = "File found: waiting until Blaze has not changed it for %d s" % self.c.settle
            else: note, key = "clip %s: not in Blaze's media list yet" % did, None; wtxt = "Not in Blaze's media list yet (the file is not there, or its name does not carry this ID)"
            if qa and not kind and (age_secs(r.get("qa_at")) or 0) > 600: self.quick_done(r, "BLOCKED", "Blaze's media list does not show this clip (%s) after 10 minutes: nothing was sent" % st)
            if wtxt: why[did] = wtxt
            out.append({"display_id": did, "state": r["state"], "story": story, "slug_id": r.get("slug_id"), "result": st, "note": (kind + ": " if kind else "") + note + ("\n" + detail if detail else "")})
            if kind:
                if self.announce("plan:" + did, key): self.event(kind, note, detail)
                if go:
                    ok = self.live_replace(r, m, order, info["item_id"], replace) if replace else self.live_attach(r, m, order, info["item_id"], quick=qa)
                    if qa: self.quick_finish(r, ok)
                elif qa and qa_why: self.quick_done(r, "BLOCKED", qa_why)
            elif self.last.get(did) != note:
                self.last[did] = note
                if not (st == "missing" and r["state"] == "WAITING_FOR_CLIP"): say("%-34s %-17s %s" % (did, r["state"], note))      # no export seen and no file in Blaze yet: the result is returned but not printed (600 such lines every morning would hide the real ones)
        return out
    # ---- live attach (OFF unless BLAZE_ATTACH=live and the other locks are set; see Cfg)
    def live_scope(self, r):
        """None when this clip may be attached for real, else the reason. With nothing narrowed, every followed show is in scope; QUICKTEST_STORY_ID / QUICKTEST_SHOW_ID / QUICKTEST_SLOT_ID (and the older BLAZE_LIVE_SHOW_IDS / BLAZE_LIVE_MASTER_IDS) narrow it, and every narrowing that is set must match."""
        c = self.c; sh = r["blaze_rundown_id"]; master = (self.show_meta.get(sh) or {}).get("master")
        if c.qt_stories and str(r["blaze_story_id"]) not in c.qt_stories: return "story %s is not QUICKTEST_STORY_ID (quicktest: only that story)" % r["blaze_story_id"]
        if (c.qt_shows or c.qt_masters) and not (sh in c.qt_shows or (master and master in c.qt_masters)): return "show %s is not QUICKTEST_SHOW_ID / QUICKTEST_SLOT_ID (quicktest: only that show)" % sh
        if (c.live_shows or c.live_masters) and not (sh in c.live_shows or (master and master in c.live_masters)): return "show %s is not allowed for live (BLAZE_LIVE_SHOW_IDS / BLAZE_LIVE_MASTER_IDS)" % sh
        return None
    def live_show(self, r):
        """Is the tool in charge of this clip (quicktest scope, or BLAZE_LIVE_SHOW_IDS / BLAZE_LIVE_MASTER_IDS)?"""
        return self.live_scope(r) is None
    def older_versions(self, r, info):
        """The clips in the story that carry an OLDER version of this clip's ID (same date and number, lower _Vn): what a new version replaces."""
        key = rkey(r)
        return [] if not key else [x for x in info["rows"] if (k := media_key(x["title"])) and k[0] == key[0] and k[1] < key[1]]
    def to_desk(self, r, why):
        try: self.a.call("/svc/files", {"display_id": r["display_id"], "state": "NEEDS_DESK", "error": why}); r["state"] = "NEEDS_DESK"; self.event("HANDED TO DESK", "clip %s: %s" % (r["display_id"], why))
        except Exception as e: say("could not tell Auto-ID about %s: %s" % (r["display_id"], e))
    def quick_done(self, r, status, msg):
        """v9.13: tell the dashboard what became of a confirmed "Quick test attach" (SENT / BLOCKED / FAILED). Said once: the server then no longer lists the request as waiting."""
        self.event("QUICK TEST " + status, "clip %s: %s" % (r["display_id"], msg))
        try: self.a.call("/svc/quickattach/result", {"display_id": r["display_id"], "status": status, "message": msg}); r["qa_state"] = status
        except Exception as e: say("could not report the quick test of %s to the dashboard: %s (it is reported again next round)" % (r["display_id"], e))
    def quick_finish(self, r, ok):
        did = r["display_id"]
        if ok: return self.quick_done(r, "SENT", "attached to Blaze story %s and read back: exactly one new clip with this file" % r["blaze_story_id"])
        row = self.led.live_of(did)
        if row is None: return                                       # the story changed while planning: nothing was sent, planned again next round (still requested)
        self.quick_done(r, "FAILED", "not attached (%s%s). The clip goes to the desk; a clip is never sent twice by itself: check the story in Blaze, then blaze_poll.py live-retry %s" % (row["status"], (": " + row["error"]) if row["error"] else "", did))
    def live_block(self, r, flags, quick=False):
        """Why this clip may NOT be sent for real right now, or None. Every rule must pass. A quick test (confirmed by an editor on the dashboard) skips only the narrowing scopes, the watcher wait and the hourly cap:
        the verified-format and itemId checks, one settled file, the kill switch and one attempt per clip all still apply."""
        why = None if quick else self.live_scope(r)
        if why: return why
        if self.c.when == "watcher" and r["state"] != "ON_NITRO" and not quick: return "clip is not on Nitro yet (state %s)" % r["state"]       # v9.8.1: BLAZE_ATTACH_WHEN=media (default): the file found in Blaze's media list is enough, the watcher need not have seen it
        if r["state"] not in LIVE_STATES: return "clip is not waiting to be attached (state %s)" % r["state"]
        if flags: return "; ".join(flags)
        if Path(self.c.stopfile).exists(): return "kill switch file %s exists" % self.c.stopfile
        if not quick and self.led.live_count_since(time.time() - 3600) >= self.c.live_cap > 0: return "hourly limit of %d reached" % self.c.live_cap
        return None
    def halt(self, why):
        try: Path(self.c.stopfile).parent.mkdir(parents=True, exist_ok=True); Path(self.c.stopfile).write_text(why + "\n", encoding="utf-8")
        except OSError: pass
        self.event("LIVE HALTED", "%s. Nothing more is sent until the file %s is deleted." % (why, self.c.stopfile))
        self.a.alert("Blaze live attach HALTED: %s. Nothing more is sent until the file %s is deleted." % (why, self.c.stopfile))
    def live_fail(self, r, why, status="FAILED", clip_id=None):
        did = r["display_id"]; self.led.live_finish(did, status, clip_id, why)
        self.event("ATTACH FAILED", "clip %s for %s: %s. Handed to the desk (NEEDS_DESK); it will not be tried again by itself." % (did, self.where(r), why))
        try: self.a.call("/svc/files", {"display_id": did, "state": "NEEDS_DESK", "error": "Automatic attach did not work: " + why}); r["state"] = "NEEDS_DESK"
        except Exception as e: say("could not tell Auto-ID about %s: %s" % (did, e))
        last = self.led.live_rows(self.c.live_halt_after)
        if len(last) >= self.c.live_halt_after and all(x["status"] != "SENT" for x in last): self.halt("%d live attaches in a row did not work" % self.c.live_halt_after)
    def live_duration(self, r, story, before, after):
        """What the page does after an attach: set the story's script duration to the clips' total seconds. Done only when the story's script time is exactly its clips' total so far (the captured case);
        a story with real script text uses a formula we have not seen, so it is left alone and said so."""
        if not self.c.live_scriptdur: return
        secs = lambda rows: None if any(x["dur"] is None for x in rows) else sum(int(x["dur"] // 1000) for x in rows)
        b, a = secs(before["rows"]), secs(after["rows"])
        if a is None or b is None or not after["version_id"]: return self.event("DURATION NOT SET", "story %s: clip durations or the version are not known: set the story duration in Blaze" % story)
        if before["version"]["scriptDur"] != b: return self.event("DURATION NOT SET", "story %s already has %s s of script time (its clips are %s s): the page's formula for that is not known, check the duration in Blaze" % (story, before["version"]["scriptDur"], b))
        try: self.b.set_script_dur(story, after["version_id"], a, before["version"]["wpm"]); self.event("DURATION SET", "story %s script duration is now %d s (the clips' total), as the Blaze page does" % (story, a))
        except SessionExpired: raise
        except Exception as e: self.event("DURATION NOT SET", "story %s: Blaze did not accept the duration update (%s): set it in Blaze" % (story, e))
    def live_attach(self, r, m, order, item_id, duration=True, quick=False):
        """v9.13: quick=True is a dashboard "Quick test attach" the editor confirmed: the Blaze client then allows this one story's attach even while BLAZE_ATTACH=dry (see BlazeClient.quick)."""
        if not quick: return self._live_attach(r, m, order, item_id, duration)
        with self.b.quick(r["blaze_story_id"]): return self._live_attach(r, m, order, item_id, duration)
    def _live_attach(self, r, m, order, item_id, duration=True):
        """Send ONE attach, then read the story back. At most one attempt per clip, ever (the ledger row is written before the call)."""
        did, story, show = r["display_id"], r["blaze_story_id"], r["blaze_rundown_id"]
        fresh = self.b.story_info(story)                                  # the last look before sending
        if m["id"] is None or str(m["id"]) in {x for x, _ in fresh["clips"]}: return False
        if fresh["item_id"] != item_id: return say("%s: the story changed while planning (itemId %s -> %s): not sent, will be planned again" % (did, item_id, fresh["item_id"])) and False
        if not self.led.live_start(did, story, show, m["id"], m["title"]): return False
        before = {x["id"] for x in fresh["rows"]}
        self.event("ATTACHING", "clip %s -> %s | order=%s itemId=%s | sending to Blaze now" % (did, self.where(r), order, item_id), attach_call(story, show, m, order, item_id))
        try: self.b.attach(story, show, m, order, item_id)
        except SessionExpired as e: self.led.live_finish(did, "UNKNOWN", error=str(e)); raise              # unclear whether it arrived: never repeated; the read-back below the next pass decides
        except BlazeError as e: return self.live_fail(r, "Blaze refused the attach (%s)" % e) and False
        except Exception as e: return self.live_fail(r, "the attach call failed (%s: %s)" % (type(e).__name__, e), "UNKNOWN") and False
        after = self.b.story_info(story); new = [x for x in after["rows"] if x["id"] not in before]
        if len(new) == 1 and new[0]["mos"] == str(m["id"]) and len(after["rows"]) == len(before) + 1:
            self.led.live_finish(did, "SENT", new[0]["id"]); self.led.seen(did, story, show, m["id"], m["title"], 1)
            self.event("ATTACHED", "clip %s is attached to %s (Blaze clip id %s, %d clip(s) in the story now)" % (did, self.where(r), new[0]["id"], len(after["rows"])))
            if duration: self.live_duration(r, story, fresh, after)
            try:
                if self.a.call("/svc/attach/confirm", dict(attached_facts(new[0], m, item_id), display_id=did, blaze_rundown_id=show, blaze_story_id=story, source="blaze_live")).get("ok"): r["state"] = "ATTACHED"
            except Exception as e: say("confirm failed for %s: %s" % (did, e))
            return True
        else:
            self.live_fail(r, "read-back does not show exactly one new clip with file %s (new clips: %s, %d -> %d clips). Check the story, then use: blaze_poll.py undo %s [clipId]" % (
                m["id"], ",".join("%s=%s" % (x["id"], x["mos"]) for x in new) or "none", len(before), len(after["rows"]), did), "CHECK_FAILED", ",".join(x["id"] for x in new) or None)
        return False
    def live_replace(self, r, m, order, item_id, old):
        """BLAZE_VERSION_MODE=auto: version N takes the place of version N-1 in the story, in two calls and in THIS order: (1) the normal live attach of the new clip with its read-back, (2) only when that was verified, the DELETE of the
        older version's clip and a second read-back. Never the other way round: a failed attach must not leave the story without a clip. Each step happens at most once per clip. Whatever goes wrong after step 1 leaves BOTH clips in the story
        (the safe side), says so in the log and alerts the desk."""
        did, story = r["display_id"], r["blaze_story_id"]; orig = self.b.story_info(story)
        if not any(x["id"] == old["id"] and x["mos"] == old["mos"] for x in orig["rows"]): return say("%s: the older version's clip %s is no longer in the story: nothing sent, will be planned again" % (did, old["id"]))
        if not self.live_attach(r, m, order, item_id, duration=False): return
        self.led.put("replace:" + did, "attached; removing clip %s of story %s" % (old["id"], story))
        if Path(self.c.stopfile).exists(): return self.replace_problem(r, old, "the kill switch file %s exists" % self.c.stopfile)
        self.event("REMOVING OLD VERSION", "clip %s is attached; now removing its older version's Blaze clip %s (%s) from story %s" % (did, old["id"], old["title"], story), "DELETE /DataService/stories/%s/clips/%s" % (story, old["id"]))
        try: rep = self.b.delete_clip(story, old["id"])
        except SessionExpired as e: self.replace_problem(r, old, "the session expired during the delete: unknown whether it arrived"); raise
        except Exception as e: return self.replace_problem(r, old, "the delete failed (%s: %s)" % (type(e).__name__, e))
        final = self.b.story_info(story); gone = not any(x["id"] == old["id"] and x["mos"] == old["mos"] for x in final["rows"]); has_new = any(x["mos"] == str(m["id"]) for x in final["rows"])
        if not (gone and has_new and len(final["rows"]) == len(orig["rows"])):
            return self.replace_problem(r, old, "the read-back after the delete is not as expected (older clip gone: %s, new file present: %s, %d clip(s) before, %d now)" % (gone, has_new, len(orig["rows"]), len(final["rows"])))
        self.led.put("replace:" + did, "done"); self.event("REPLACED", "clip %s replaced the older version's Blaze clip %s in story %s (%d clip(s) in the story now). Blaze said: %s" % (did, old["id"], story, len(final["rows"]), json.dumps(rep)))
        if not self.c.live_scriptdur: return
        b, a = clip_secs(orig["rows"]), clip_secs(final["rows"])
        if None in (a, b) or not final["version_id"]: return self.event("DURATION NOT SET", "story %s: clip durations or the version are not known: check the story duration in Blaze" % story)
        if orig["version"]["scriptDur"] != b: return self.event("DURATION NOT SET", "story %s had %s s of script time (its clips were %s s): the page's formula for that is not known, check the duration in Blaze" % (story, orig["version"]["scriptDur"], b))
        try: self.b.set_script_dur(story, final["version_id"], a, orig["version"]["wpm"]); self.event("DURATION SET", "story %s script duration is now %d s (the clips' total), as the Blaze page does" % (story, a))
        except SessionExpired: raise
        except Exception as e: self.event("DURATION NOT SET", "story %s: Blaze did not accept the duration update (%s): set it in Blaze" % (story, e))
    def replace_problem(self, r, old, why):
        did, story = r["display_id"], r["blaze_story_id"]; self.led.put("replace:" + did, "INCOMPLETE: " + why)
        msg = "clip %s IS attached to story %s but its older version's Blaze clip %s (%s) was NOT removed: %s. The story holds both clips: remove clip %s by hand in Blaze." % (did, story, old["id"], old["title"], why, old["id"])
        self.event("REPLACE INCOMPLETE", msg); self.a.alert("Blaze version replace incomplete: " + msg)
    def reconcile(self):
        """READ every followed story's clips from Blaze. A clip carrying one of our IDs is recorded in the ledger (where it sits, which file); when it sits in the story the
        registry expects, the clip is marked ATTACHED in Auto-ID (BLAZE_CONFIRM=1). Catches clips the desk attached by hand. Blaze is the truth, not our memory."""
        byk = {}
        for r in self.rows:
            k = rkey(r)
            if k and not r.get("deleted"): byk.setdefault(k, []).append(r)             # one clip name can belong to several stories
        n = 0; now = time.time(); urgent, due, done = [], [], set()
        for show, sl in self.stories.items():
            for s in sl:
                sid = s["story_id"]
                if sid in done: continue                                                  # a story that sits in several shows is read once
                done.add(sid); cc = self.clipcount.get(sid); prev = self.cc_read.get(sid)
                if sid in self.dirty or (cc is not None and prev and prev[0] != cc): urgent.append((show, s))            # layer A or B saw its attachments change
                elif cc is None or prev is None or now - prev[1] >= self.c.full_recon: due.append((prev[1] if prev else 0, show, s))   # layer C: the full read, oldest first
        batch = [(show, s) for _, show, s in sorted(due, key=lambda x: x[0])[: self.c.recon_batch]]            # a bounded batch per pass, so 600+ stories never stall a polling round
        fresh = lambda sid: self.ident.get(sid) is not None and now - self.ident[sid][1] < self.c.ident_secs + self.c.poll
        results = {s["story_id"]: ("ok", {"clips": [(x["mos"], x["title"]) for x in self.ident[s["story_id"]][0]], "title": None}) for _, s in urgent if fresh(s["story_id"])}   # the identity read is fresh: no request
        def read(item):
            try: return item[1]["story_id"], "ok", self.rt(lambda: self.b.story_info(item[1]["story_id"]))
            except SessionExpired as e: return item[1]["story_id"], "expired", e
            except Exception as e: return item[1]["story_id"], "err", e
        reads = [it for it in urgent if it[1]["story_id"] not in results] + batch
        for sid, kind, val in self.pool_map(read, reads, "recon", key=lambda it: it[1]["story_id"]): results[sid] = (kind, val)
        for show, s in [it for it in urgent if it[1]["story_id"] in results] + batch:
            sid = s["story_id"]; kind, info = results.get(sid, ("err", None))
            if kind == "expired": raise info
            if kind == "err": continue                                                    # not remembered, so it is read again next pass
            self.cc_read[sid] = (self.clipcount.get(sid), now); self.dirty.discard(sid); story_clips = info["clips"]
            if info.get("title") is not None:                                             # the full read also carries the STORY title (not always the slug title)
                old = self.store.story_title(sid)
                if old is not None and old != info["title"]: self.event("STORY TITLE CHANGED", "%s: %r -> %r" % (self.where_story(sid), old, info["title"])); self.stats.changed_stories.add(sid)
                self.store.set_story_title(sid, info["title"], now)
                if old != info["title"]:
                    for sh in self.story_shows.get(sid) or []: self.synced[sh] = False         # the registry shows the story name: send it again in the next round
            found = {}
            for mid, title in story_clips:
                k = media_key(title); rs = byk.get(k) if k else None
                r = next((x for x in rs if x["blaze_story_id"] == s["story_id"]), rs[0]) if rs else None            # the row of THIS story when the name is shared
                mine = [x for x in rs if x["blaze_story_id"] == s["story_id"]] if rs else []       # v9.11: a story that sits in several bulletins has one clip ID per bulletin: all of them are in the story, not just the first
                for r in (mine or ([rs[0]] if rs else [])): d = found.setdefault((r["display_id"], mid), [r, title, 0]); d[2] += 1
            for (did, mid), (r, title, cnt) in found.items():
                sh = r["blaze_rundown_id"] if s["story_id"] == r["blaze_story_id"] else show       # the clip ID's own bulletin (the registry compares it)
                self.led.seen(did, s["story_id"], sh, mid, title, cnt); n += 1
                if self.c.confirm and cnt == 1 and s["story_id"] == r["blaze_story_id"] and (r["state"] != "ATTACHED" or not r.get("item_id") or not r.get("mos_object_id")):
                    try:                                                          # also for a clip that is already ATTACHED but whose item / duration were never recorded (desk attach, or before v9.8): the server only fills the gaps
                        row = next((x for x in info["rows"] if x["mos"] == str(mid)), None) or {}
                        was = r["state"]; res = self.a.call("/svc/attach/confirm", dict(attached_facts(row, {"id": mid}, None), display_id=did, blaze_rundown_id=sh, blaze_story_id=s["story_id"], source="blaze_readback", media_mode=(self.c.when == "media")))
                        if res.get("ok") and was != "ATTACHED": say("%-34s Blaze shows it in story %s: marked ATTACHED" % (did, s["story_id"])); r["state"] = "ATTACHED"
                        if res.get("ok"): r["mos_object_id"] = str(mid); r["item_id"] = r.get("item_id") or row.get("item") or "-"
                    except Exception as e: say("confirm failed for %s: %s" % (did, e))
        live = {s["story_id"] for sl in self.stories.values() for s in sl}                   # forget what is no longer on any followed show, so memory stays flat over weeks
        for d in (self.cc_read, self.clipcount, self.pos, self.fmt, self.ident, self.info_cache):
            for k in [k for k in d if k not in live]: d.pop(k, None)
        ids = {r["display_id"] for r in self.rows}
        for d in (self.mcache, self.last):
            for k in [k for k in d if k not in ids]: d.pop(k, None)
        return n
