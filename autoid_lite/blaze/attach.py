"""Poller: plan the attach, the live attach itself, replace/undo of older versions, reconcile against Blaze's read-back."""
from __future__ import annotations
from pathlib import Path
import contextlib
import datetime as dt
import json
import time
from .errors import BlazeError, SessionExpired
from ..ids import kind_of, suffix_on, vlabel
from .keys import age_secs, attach_call, attached_facts, clip_secs, ignored, media_key, rkey
from .states import LIVE_STATES
from .util import say


def main_ver(k):
    """The version that counts for 'the newest clip of the story': None for a _Vn clip when VERSION_SUFFIX=on (an added clip never takes the place of another), else the key's number."""
    return None if suffix_on() and kind_of(k[1]) == "V" else k[1]


class AttachMixin:
    CURRENT_MIN = 60                     # v10.4.0: a bulletin that started less than this many minutes ago counts as "the current bulletin"

    def carrier(self, story, row_show):
        """v10.4.0: a Blaze clip belongs to the STORY, not to a bulletin: a story that sits in several bulletins shows the clip in all of them after ONE attach.
        Which bulletin carries that one attach: the current bulletin when the story is in it, else the next future one, else (everything has aired) the latest one that aired.
        -> (show id, why). Only followed shows that really hold the story (their row in that show is known) are candidates."""
        now = dt.datetime.now(dt.timezone.utc); cand = []
        for sh in self.story_shows.get(story) or []:
            if sh not in self.c.shows or (sh, story) not in self.posin: continue
            try: st = dt.datetime.fromisoformat((self.show_meta.get(sh) or {}).get("start"))
            except (TypeError, ValueError): continue
            if st.tzinfo is None: st = st.replace(tzinfo=dt.timezone.utc)
            cand.append((st, sh))
        if not cand: return row_show, "the row's own bulletin"
        cand.sort(); past = [c for c in cand if c[0] <= now]; future = [c for c in cand if c[0] > now]
        if past and (now - past[-1][0]).total_seconds() / 60 < self.CURRENT_MIN: return past[-1][1], "the current bulletin"
        if future: return future[0][1], "the next bulletin"
        return past[-1][1], "the latest bulletin (all have aired)"

    @staticmethod
    def with_ident(info, idn, m):
        """The plan calls a file 'already in the story' when EITHER reading shows it (the story details or the attachment identity read). confirm_group counts the story details only,
        so a file that only the identity read shows was reported but never marked. This gives confirm_group the same view the plan used (a copy: the cached details are not changed)."""
        mid = str(m["id"])
        if not idn or any(x == mid for x, _ in info.get("clips") or []): return info
        hit = [x for x in idn[0] if x.get("mos") == mid]
        if len(hit) != 1: return info
        x = hit[0]; return dict(info, clips=list(info.get("clips") or []) + [(mid, x.get("title") or "")], rows=list(info.get("rows") or []) + [{"id": x.get("id"), "mos": mid, "title": x.get("title") or "", "dur": x.get("dur"), "item": None}], partial=True)

    def confirm_group(self, r, story, info, m, source, new=None, item_id=None):
        """v10.4.0: the file sits in the story. Every registry row of that story with the same clip name and version (one clip ID per bulletin that holds the story) is marked ATTACHED,
        each one only when Blaze's own read-back lists its bulletin among the story's shows. A row whose bulletin is not in that list is left alone and said once."""
        did0 = r["display_id"]; self.confirm_why.pop(did0, None)
        if source == "blaze_readback" and not self.c.confirm: self.confirm_why[did0] = "BLAZE_CONFIRM=0: the poller never marks a clip ATTACHED from Blaze's read-back"; return False
        n = sum(1 for mos, _ in info.get("clips") or [] if mos == str(m["id"]))
        if n != 1: self.confirm_why[did0] = "the file shows %d times in the story (a duplicate): the desk checks" % n if n else "Blaze's story read does not list the file yet"; return False      # twice in the story is a DUPLICATE (reconcile says so), not an attach
        key = rkey(r); sibs = [x for x in self.rows if not x.get("deleted") and x.get("blaze_story_id") == story and key and rkey(x) == key]
        if r not in sibs: sibs.insert(0, r)
        row = new or next((x for x in info.get("rows") or [] if x["mos"] == str(m["id"])), None) or {}
        seen = {str(s) for s in info.get("shows") or []}; done = False                      # an empty or missing show list proves nothing: no sibling is marked on it
        for x in sibs:
            if x["state"] == "ATTACHED": continue
            did, sh = x["display_id"], x["blaze_rundown_id"]
            if x is not r and sh not in seen:
                if self.announce("sharedmiss:" + did, "1"): self.event("SHARED NOT SEEN", "clip %s: its file is in story %s but Blaze %s show %s (%s) for that story: not marked ATTACHED, the desk checks" % (did, story, "does not list" if seen else "gave no show list for the story, so cannot confirm", sh, (self.names.get(sh) or ("", 0))[0]))
                continue
            body = dict(attached_facts(row, m, item_id), display_id=did, blaze_rundown_id=sh, blaze_story_id=story, source=source)
            if source == "blaze_readback": body["media_mode"] = (self.c.when == "media")
            try: res = self.a.call("/svc/attach/confirm", body)
            except Exception as e: say("confirm failed for %s: %s" % (did, e)); self.confirm_why[did] = "Auto-ID could not be reached (%s)" % e; continue
            if not res.get("ok"): self.confirm_why[did] = str(res.get("error") or res.get("note") or "the clip is %s" % res.get("state"))
            if res.get("ok"):
                x["state"] = "ATTACHED"; x["mos_object_id"] = str(m["id"]); done = True
                if body["item_id"]: x["item_id"] = body["item_id"]
                if x is not r: self.event("SHARED ATTACHED", "clip %s (show %s %s) is marked ATTACHED: story %s is shared and the file is in it" % (did, sh, (self.names.get(sh) or ("", 0))[0], story))
        return done

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
        latest = {}                                                                                  # v10.4.0: the newest version whose file is ready, per story and clip name: that one is used in every show of the story
        for r, st, m in looked:
            k = rkey(r)
            if st == "found" and k and r not in back and main_ver(k): latest[(r["blaze_story_id"], k[0])] = max(latest.get((r["blaze_story_id"], k[0]), 0), main_ver(k))
        for r, st, m in looked:
            did, story, show = r["display_id"], r["blaze_story_id"], r["blaze_rundown_id"]
            if st == "found": self.led.plan(did, story, show, m["id"], m["title"]); self.tell_media(did, m)
            if r in back: continue
            if r["state"] == "ATTACHED":                                                              # v10.4.0: already marked through the other rows of its shared story in this pass
                if r.get("qa_state") == "REQUESTED": self.quick_done(r, "SENT", "this story is shared: the clip was attached once for all its bulletins and this clip ID is marked ATTACHED")
                continue
            k = rkey(r)
            if st == "found" and k and (self.c.version_mode == "auto" or suffix_on()) and main_ver(k) and main_ver(k) < latest.get((story, k[0]), 0):      # in desk mode the desk owns every numbered version above 1: nothing changes there (v10.5.0, VERSION_SUFFIX=on: a ready _Un takes the place of the plain clip and of every older _Un; a _Vn is never superseded)
                why[did] = wtxt = "Superseded: version %s of this clip is the one used in every show of the story" % vlabel(latest[(story, k[0])]); self.last[did] = wtxt
                if r.get("qa_state") == "REQUESTED": self.quick_done(r, "BLOCKED", wtxt)
                continue
            detail, kind, go, replace = None, None, False, None; qa = did in qa_all; qa_why = None; wtxt = None
            if st == "found":
                if story not in self.info_cache: continue                              # its details are read next pass (beyond this pass's batch, or Blaze did not answer)
                info = self.info_cache[story][1]; car, car_how = self.carrier(story, show); pos = self.posin.get((car, story)); pos = self.pos.get(story) if pos is None and car == show else pos; order = pos + 1 if isinstance(pos, int) else None
                idn = self.ident.get(story); have = {x for x, _ in info["clips"]} | ({x["mos"] for x in idn[0]} if idn else set())     # in the story by either reading
                if str(m["id"]) in have:
                    kind, note = "ALREADY IN STORY", "clip %s: file %s is already in %s: nothing to do" % (did, m["title"], self.where(r)); qa_why = "the file is already in the story: nothing was sent"; wtxt = "The file is already in the story"
                    self.confirm_group(r, story, self.with_ident(info, idn, m), m, "blaze_readback"); cw = self.confirm_why.get(did)
                    if r["state"] == "ATTACHED":
                        if qa: self.quick_done(r, "SENT", "the file was already in the story (the desk attached it): nothing was sent by the tool, and this clip ID is now marked ATTACHED"); qa_why = None      # v10.6.1: not a refusal: the clip is attached
                    else:
                        wtxt = "The file is already in the story, but the clip is not marked ATTACHED yet" + ((": " + cw) if cw else "")
                        qa_why = "the file is already in the story: nothing was sent. The clip is not marked ATTACHED yet" + ((" (" + cw + ")") if cw else "")
                else:
                    ver = int(r.get("version") or 1); old = self.older_versions(r, info) if ver > 1 else []
                    if ver > 1 and self.c.version_mode == "desk" and not qa and not (suffix_on() and kind_of(ver)):      # v10.5.0: with VERSION_SUFFIX=on a _Un / _Vn clip is the tool's job, whatever BLAZE_VERSION_MODE says
                        kind = "NEW VERSION READY"; wtxt = "New version: the desk attaches it (BLAZE_VERSION_MODE=desk)"; have_old = ("the story still holds the older version: Blaze clip %s (%s)" % (old[0]["id"], old[0]["title"])) if len(old) == 1 else ("the story holds %d older versions of this clip" % len(old) if old else "the story holds no older version of this clip")
                        note = "clip %s is version %d: its file %s is in Blaze (%s). NOT attached by the tool (BLAZE_VERSION_MODE=desk): the desk attaches it and removes the older version's clip" % (did, ver, m["title"], have_old)
                        if self.c.attach == "live" and self.live_show(r): self.to_desk(r, "New version ready (version %d, file %s). Not attached by the tool (BLAZE_VERSION_MODE=desk): attach it by hand in Blaze and remove the older version's clip." % (ver, m["title"]))
                    else:
                        kind = "GOING TO ATTACH"; flags = []
                        if self.fmt.get(story) not in self.c.verified: flags.append("CHECK: itemId rule not yet verified for story format %s (BLAZE_VERIFIED_FORMATS)" % self.fmt.get(story))
                        if info["item_id"] is None: flags.append("CHECK: no script item found in the story, itemId unknown")
                        if order is None: flags.append("CHECK: story row position unknown")
                        if len(old) > 1: flags.append("CHECK: the story holds %d older versions of this clip (%s): the tool will not choose, remove them by hand" % (len(old), ", ".join(x["id"] for x in old)))
                        sendable = self.c.attach == "live" or qa                                      # v9.13: a confirmed quick test is sent even while BLAZE_ATTACH=dry
                        block = self.live_block(r, flags, qa) if sendable else None; go = sendable and not block; qa_why = block
                        wtxt = "Being attached now" if go else ("Blocked: %s" % block if block else "Dry mode: nothing is sent by itself (BLAZE_ATTACH=dry). Use Quick test attach, or set BLAZE_ATTACH=live")
                        mode = (("QUICK TEST (confirmed on the dashboard by %s): sending now" % (r.get("qa_by") or "?")) if qa else "LIVE: sending now") if go else ("DRY RUN: nothing sent to Blaze" if not sendable else "NOT SENT (%s blocked: %s)" % ("quick test" if qa else "live", block))
                        note = "clip %s (file %s, media %s, %ds) to %s | order=%s itemId=%s%s | %s" % (
                            did, m["title"], m["id"], (m.get("duration") or 0) // 1000, self.where(r), "?" if order is None else order, info["item_id"] or "?", "".join(" | " + f for f in flags), mode)
                        detail = ("sending: " if go else "would send: ") + attach_call(story, car, m, order, info["item_id"])
                        if len(info["shows"]) > 1: note += " | SHARED story: it sits in shows %s; ONE attach in show %s (%s) shows the clip in all of them, every clip ID of the story is then marked ATTACHED" % (",".join(info["shows"]), car, car_how)
                        if qa and old and not (suffix_on() and kind_of(ver) == "U"): note += " | QUICK TEST only ADDS this clip: the older version's clip is not removed (do that by hand)"
                        elif len(old) == 1:
                            replace = old[0]; note += " | REPLACES version %s: Blaze clip %s (%s) is removed AFTER the attach is verified" % (vlabel(media_key(replace["title"])[1]), replace["id"], replace["title"]); detail += "\nthen, only if the read-back is exactly right: DELETE /DataService/stories/%s/clips/%s" % (story, replace["id"])
                        elif info["rows"] and not old: note += " | the story already has %d clip(s): this one is ADDED, it does not replace them" % len(info["rows"]) + (" (%s)" % vlabel(ver) if kind_of(ver) == "V" and suffix_on() else "")
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
                    ok = self.live_replace(r, m, order, info["item_id"], replace, show=car, quick=qa) if replace else self.live_attach(r, m, order, info["item_id"], show=car, quick=qa)
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
        if suffix_on() and kind_of(key and key[1]) == "V": return []                                # v10.5.0: a _Vn clip is ADDED, it replaces nothing
        return [] if not key else [x for x in info["rows"] if (k := media_key(x["title"])) and k[0] == key[0] and k[1] < key[1] and not (suffix_on() and kind_of(k[1]) == "V")]
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
    def live_attach(self, r, m, order, item_id, duration=True, quick=False, show=None):
        """v9.13: quick=True is a dashboard "Quick test attach" the editor confirmed: the Blaze client then allows this one story's attach even while BLAZE_ATTACH=dry (see BlazeClient.quick)."""
        if not quick: return self._live_attach(r, m, order, item_id, duration, show)
        with self.b.quick(r["blaze_story_id"]): return self._live_attach(r, m, order, item_id, duration, show)
    def _live_attach(self, r, m, order, item_id, duration=True, show=None):
        """Send ONE attach, then read the story back. At most one attempt per clip, ever (the ledger row is written before the call)."""
        did, story, rshow = r["display_id"], r["blaze_story_id"], r["blaze_rundown_id"]; show = show or rshow          # v10.4.0: show = the bulletin that carries the one attach, rshow = this clip ID's own bulletin
        fresh = self.b.story_info(story)                                  # the last look before sending
        inst = {x for x, _ in fresh["clips"]}
        for op in self.led.live_opens(story):                              # an earlier unclear attempt whose EXACT file (media object id) is now in the story is settled: it did arrive
            if op["status"] in ("SENDING", "UNKNOWN") and op["media_id"] in inst: self.led.live_finish(op["display_id"], "SENT", error="seen in the story by a later read (media %s)" % op["media_id"])
        if m["id"] is None or str(m["id"]) in {x for x, _ in fresh["clips"]}: return False
        if fresh["item_id"] != item_id: return say("%s: the story changed while planning (itemId %s -> %s): not sent, will be planned again" % (did, item_id, fresh["item_id"])) and False
        fs = {str(x) for x in fresh.get("shows") or []}
        if fs and show not in fs: return say("%s: Blaze no longer lists show %s for story %s (it lists %s): not sent, will be planned again" % (did, show, story, ",".join(sorted(fs)))) and False       # v10.4.0: the bulletin chosen to carry the attach lost the story while planning
        if not self.led.live_start(did, story, show, m["id"], m["title"]):
            own = self.led.live_of(did); ops = self.led.live_opens(story)
            if own is not None:                                           # this clip ID has an attempt on record: never repeated; if it ended unclear and the file is still not in the story, the desk is told once (the clock runs from its FIRST send, in the ledger, so a restart does not reset it)
                age = time.time() - own["sent_at"]
                if own["status"] in ("SENDING", "UNKNOWN") and age > self.c.unclear_secs and r["state"] in LIVE_STATES:
                    self.live_fail(r, "an earlier attach attempt ended unclear (%s, %d min ago) and file %s is not in the story. It may still arrive: look at the story in Blaze before attaching by hand, then run live-retry for this clip. Nothing is repeated automatically" % (own["status"], age // 60, m["id"]), "UNKNOWN")
            elif ops and self.announce("openattempt:" + did, ops[0]["display_id"]): say("%s: clip %s of the same story has an attempt that is not settled (%s): nothing is sent for this story until it is; the next read of the story decides" % (did, ops[0]["display_id"], ops[0]["status"]))
            return False
        before = {x["id"] for x in fresh["rows"]}
        self.event("ATTACHING", "clip %s -> %s | order=%s itemId=%s | sending to Blaze now" % (did, self.where(r), order, item_id), attach_call(story, show, m, order, item_id))
        try: self.b.attach(story, show, m, order, item_id)
        except SessionExpired as e: self.led.live_finish(did, "UNKNOWN", error=str(e)); raise              # unclear whether it arrived: never repeated; the read-back below the next pass decides
        except BlazeError as e: return self.live_fail(r, "Blaze refused the attach (%s)" % e) and False
        except Exception as e: return self.live_fail(r, "the attach call failed (%s: %s)" % (type(e).__name__, e), "UNKNOWN") and False
        try: after = self.b.story_info(story)
        except SessionExpired as e: self.led.live_finish(did, "UNKNOWN", error="session expired after the attach: %s" % e); raise            # the attach was sent: never repeated, the next read of the story decides
        except Exception as e:
            self.led.live_finish(did, "UNKNOWN", error="read-back failed after the attach: %s" % e)
            self.event("READ-BACK FAILED", "clip %s: the attach was sent but Blaze did not answer the read-back (%s: %s). It is NOT sent again: the next read of the story decides, check the story if it stays open" % (did, type(e).__name__, e)); return False
        new = [x for x in after["rows"] if x["id"] not in before]
        if len(new) == 1 and new[0]["mos"] == str(m["id"]) and len(after["rows"]) == len(before) + 1:
            self.led.live_finish(did, "SENT", new[0]["id"]); self.led.seen(did, story, rshow, m["id"], m["title"], 1)
            self.event("ATTACHED", "clip %s is attached to %s (Blaze clip id %s, %d clip(s) in the story now)" % (did, self.where(r), new[0]["id"], len(after["rows"])))
            if duration: self.live_duration(r, story, fresh, after)
            self.confirm_group(r, story, after, m, "blaze_live", new=new[0], item_id=item_id)            # v10.4.0: this clip ID and every other clip ID of the shared story
            return True
        else:
            self.live_fail(r, "read-back does not show exactly one new clip with file %s (new clips: %s, %d -> %d clips). Check the story, then use: blaze_poll.py undo %s [clipId]" % (
                m["id"], ",".join("%s=%s" % (x["id"], x["mos"]) for x in new) or "none", len(before), len(after["rows"]), did), "CHECK_FAILED", ",".join(x["id"] for x in new) or None)
        return False
    def live_replace(self, r, m, order, item_id, old, show=None, quick=False):
        """BLAZE_VERSION_MODE=auto: version N takes the place of version N-1 in the story, in two calls and in THIS order: (1) the normal live attach of the new clip with its read-back, (2) only when that was verified, the DELETE of the
        older version's clip and a second read-back. Never the other way round: a failed attach must not leave the story without a clip. Each step happens at most once per clip. Whatever goes wrong after step 1 leaves BOTH clips in the story
        (the safe side), says so in the log and alerts the desk."""
        did, story = r["display_id"], r["blaze_story_id"]; orig = self.b.story_info(story)
        if not any(x["id"] == old["id"] and x["mos"] == old["mos"] for x in orig["rows"]): return say("%s: the older version's clip %s is no longer in the story: nothing sent, will be planned again" % (did, old["id"]))
        qx = lambda: self.b.quick(story) if quick else contextlib.nullcontext()      # v10.5.0: a confirmed Quick test on a _Un clip does the whole replace (attach, then remove), even while BLAZE_ATTACH=dry
        if not self.live_attach(r, m, order, item_id, duration=False, quick=quick, show=show): return
        self.led.put("replace:" + did, "attached; removing clip %s of story %s" % (old["id"], story))
        if Path(self.c.stopfile).exists(): return self.replace_problem(r, old, "the kill switch file %s exists" % self.c.stopfile)
        self.event("REMOVING OLD VERSION", "clip %s is attached; now removing its older version's Blaze clip %s (%s) from story %s" % (did, old["id"], old["title"], story), "DELETE /DataService/stories/%s/clips/%s" % (story, old["id"]))
        try:
            with qx(): rep = self.b.delete_clip(story, old["id"])
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
        try:
            with qx(): self.b.set_script_dur(story, final["version_id"], a, orig["version"]["wpm"])
            self.event("DURATION SET", "story %s script duration is now %d s (the clips' total), as the Blaze page does" % (story, a))
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
        results = {s["story_id"]: ("ok", {"clips": [(x["mos"], x["title"]) for x in self.ident[s["story_id"]][0]], "title": None, "partial": True, "rows": [{"id": x["id"], "mos": x["mos"], "title": x["title"], "dur": x.get("dur"), "item": None} for x in self.ident[s["story_id"]][0]]}) for _, s in urgent if fresh(s["story_id"])}   # v10.4.0: with rows (before, confirm failed with 'rows')   # the identity read is fresh: no request
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
                        row = next((x for x in info.get("rows") or [] if x["mos"] == str(mid)), None) or {}
                        was = r["state"]; res = self.a.call("/svc/attach/confirm", dict(attached_facts(row, {"id": mid}, None), display_id=did, blaze_rundown_id=sh, blaze_story_id=s["story_id"], source="blaze_readback", media_mode=(self.c.when == "media")))
                        if res.get("ok") and was != "ATTACHED": say("%-34s Blaze shows it in story %s: marked ATTACHED" % (did, s["story_id"])); r["state"] = "ATTACHED"
                        if res.get("ok"): r["mos_object_id"] = str(mid); r["item_id"] = r.get("item_id") or row.get("item") or (None if info.get("partial") else "-")          # a partial read does not know the item: the next full read fills it
                    except Exception as e: say("confirm failed for %s: %s" % (did, e))
        live = {s["story_id"] for sl in self.stories.values() for s in sl}                   # forget what is no longer on any followed show, so memory stays flat over weeks
        for d in (self.cc_read, self.clipcount, self.pos, self.fmt, self.ident, self.info_cache):
            for k in [k for k in d if k not in live]: d.pop(k, None)
        for k in [k for k in self.posin if k[1] not in live]: self.posin.pop(k, None)
        ids = {r["display_id"] for r in self.rows}
        for d in (self.mcache, self.last):
            for k in [k for k in d if k not in ids]: d.pop(k, None)
        return n
