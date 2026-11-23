"""v10.10.0 Quick Support, the poller's part: the requests an editor made in the dashboard's Support menu (see api_support.py) are carried out here.

  ADD     attach one Blaze file to one story. A file that is not in Blaze's media list yet waits (the request stays QUEUED, up to SUPPORT_QUEUE_MINUTES) and is attached when it appears.
  REMOVE  delete one clip from one story (the clip only: the file stays on Nitro / in Blaze's media list).
  LIST    read a story's clips from Blaze, for the delete picker (read only).

It does NOT touch the normal polling: it runs AFTER the round has finished and reported its heartbeat, in its own guard (nothing here can raise into the round), it reuses the media list the round already read,
and it writes nothing to the registry or the ledger that the automatic attach counts (the hourly cap and the 'N attaches in a row failed' halt never see it). The list requests are answered by a small thread of their own (read only).
Every write keeps the rules of a confirmed Quick test: one attempt per request (WORKING is recorded BEFORE the call; a request that was WORKING after a restart is settled by reading the story, never sent again),
read-back that must show exactly the one change, the kill switch, the story format / item rule, and 'BLAZE_ATTACH=dry' does not stop it because an editor confirmed it."""
from __future__ import annotations
from pathlib import Path
import re
import threading
import time
from .errors import BlazeError, SessionExpired
from .keys import attach_call, judge, media_key, rkey
from .util import say

SEARCH_EVERY = 30        # seconds between two searches by title for the same waiting request (the media list the round already read is checked every round, for free)
SEARCHES_PER_ROUND = 3   # at most this many title searches per round, whatever the number of waiting requests
WORK_PER_ROUND = 8      # v10.10.1: at most this many requests are STARTED (claimed) per round. Requests that only keep waiting do not count: they never use up the places of the ones behind them


class SupportMixin:
    # ---------- the loop ----------
    def sup_thread_alive(self): return bool(getattr(self, "_sup_thread", None) and self._sup_thread.is_alive())
    def sup_start(self):
        """Called by run(): a small thread that answers LIST requests every SUPPORT_LIST_SECS (read only), so the delete picker is quick. Add and delete run in the polling thread, after the round."""
        if not self.c.support or self.sup_thread_alive(): return
        def loop():
            while True:
                try: self.support_round("LIST")
                except BaseException: pass                                           # never ends, never matters to the round
                time.sleep(self.c.support_list_secs)
        self._sup_thread = threading.Thread(target=loop, name="support-list", daemon=True); self._sup_thread.start()
    def support_round(self, kind="ACTION"):
        """kind LIST | ACTION (add and delete) | ALL. Every error stays in here."""
        if not self.c.support: return
        try: jobs = self.a.call("/svc/support/jobs?kind=" + kind)
        except Exception: return                                                     # an older server without the endpoint, or Auto-ID busy: nothing to do
        if kind != "LIST": self.sup_searches = 0; self.sup_acted = 0                   # (the list thread must not reset the counters of the polling thread)
        for j in jobs:
            if kind != "LIST" and getattr(self, "sup_acted", 0) >= WORK_PER_ROUND: break      # the rest is for the next round
            try:
                if j.get("recovered"): self.sup_recover(j)
                elif j["kind"] == "LIST": self.sup_list(j)
                elif j["kind"] == "ADD": self.sup_add(j)
                elif j["kind"] == "REMOVE": self.sup_remove(j)
            except Exception as e:                                                   # SessionExpired included: the next normal round notices it and logs in again
                if self.announce("supfail:%s" % j.get("id"), "%s: %s" % (type(e).__name__, str(e)[:120])): say("Quick Support request %s could not be handled now (%s: %s): it is tried again" % (j.get("id"), type(e).__name__, e))

    # ---------- small helpers ----------
    def sup_post(self, j, state, msg, result=None, **more):
        return self.a.call("/svc/support/result", dict({"id": j["id"], "state": state, "message": msg, "result": result}, **more))
    def sup_end(self, j, state, msg, result=None):
        kind = "SUPPORT " + j["kind"] + (" " + state if state != "DONE" else " DONE")
        self.event(kind, "request %s by %s, story %s \"%s\": %s" % (j["id"], j.get("by_user"), j["blaze_story_id"], j.get("story"), msg))
        try: self.sup_post(j, state, msg, result)
        except Exception as e: say("Quick Support request %s: could not report %s to Auto-ID (%s): the next round settles it by reading the story" % (j["id"], state, e))
    def sup_wait(self, j, msg):
        """Still queued: say why, once per change (the request is NOT touched otherwise)."""
        if getattr(self, "_sup_msg", {}).get(j["id"]) == msg or j.get("msg") == msg: return
        self._sup_msg = getattr(self, "_sup_msg", {}); self._sup_msg[j["id"]] = msg
        try: self.sup_post(j, "QUEUED", msg)
        except Exception: pass
    def sup_claim(self, j, msg, **more):
        """QUEUED -> WORKING, recorded BEFORE anything is sent: from here on the request is never sent again by itself. False when someone else got it or an editor cancelled it."""
        r = self.sup_post(j, "WORKING", msg, **dict({"from": "QUEUED"}, **more))
        if r.get("ok") and j["kind"] != "LIST": self.sup_acted = getattr(self, "sup_acted", 0) + 1
        return bool(r.get("ok"))
    def sup_gate(self, j):
        """Rules that stop a write for now. -> a sentence (the request is BLOCKED) or None."""
        if self.c.attach == "off": return "BLAZE_ATTACH=off: the poller does not read or write Blaze's media, so nothing is sent"
        if Path(self.c.stopfile).exists(): return "the kill switch file %s exists: nothing is sent until it is deleted" % self.c.stopfile
        if j["blaze_rundown_id"] not in self.c.shows: return "the poller does not follow this bulletin (BLAZE_SHOW_IDS): it cannot send to it"
        return None
    def sup_read(self, story): return self.rt(lambda: self.b.story_info(story))

    # ---------- LIST ----------
    def sup_list(self, j):
        if not self.sup_claim(j, "Reading the story from Blaze"): return
        try: info = self.sup_read(j["blaze_story_id"])
        except Exception as e: return self.sup_post(j, "FAILED", "Blaze did not answer (%s: %s)" % (type(e).__name__, e))
        names = [(self.names.get(sh) or ("", 0))[0] or "bulletin " + sh for sh in info["shows"]]
        self.sup_post(j, "DONE", "%d clip(s) in the story" % len(info["rows"]), {"clips": [{"id": x["id"], "mos": x["mos"], "title": x["title"], "dur_s": None if x["dur"] is None else int(x["dur"] // 1000)} for x in info["rows"]],
                                                                                "shows": info["shows"], "show_names": names, "story_title": info["title"]})

    # ---------- ADD ----------
    def sup_find(self, j):
        """The Blaze file of an ADD request: (state, media). state: found | missing | ambiguous | converting | settling.
        The media list the round already read is looked at first (free); only when the file is not in it, a title search runs, at most every SEARCH_EVERY seconds per request."""
        mid = str(j["media_id"]) if j.get("media_id") else None; key = media_key(j.get("media_name")); hits = []
        if self.mlist and time.time() - self.mlist[0] <= max(120, 4 * self.c.poll):
            idx = self.mlist[1]
            if mid: hits = [m for d in idx.values() for i, m in d.items() if str(i) == mid][:1]
            elif key: hits = list((idx.get(key) or {}).values())
        if not hits and (key or mid) and time.time() - getattr(self, "_sup_at", {}).get(j["id"], 0) >= SEARCH_EVERY and self.sup_searches < SEARCHES_PER_ROUND:
            self.sup_searches += 1; self._sup_at = getattr(self, "_sup_at", {}); self._sup_at[j["id"]] = time.time()
            text = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", (j.get("media_name") or "").strip())
            ms, _ = self.rt(lambda: self.b.media_search(text, self.c.days))
            hits = list({m["id"]: m for m in ms if (str(m["id"]) == mid if mid else key and media_key(m.get("title") or m.get("description")) == key)}.values())
        return judge(hits, self.c.settle)
    def sup_add(self, j):
        story, show, title = j["blaze_story_id"], j["blaze_rundown_id"], j.get("story")
        why = self.sup_gate(j)
        if why: return self.sup_end(j, "BLOCKED", why)
        st, m = self.sup_find(j)
        if st == "ambiguous": return self.sup_end(j, "BLOCKED", "%d Blaze files carry this name (%s): pick the right file from the list instead" % (len(m), ", ".join(str(x.get("title")) for x in m[:4])))
        if st != "found":
            return self.sup_wait(j, {"missing": "Queued: waiting for this file to appear in Blaze's media list", "converting": "Queued: the file is in Blaze, which is still converting it",
                                     "settling": "Queued: the file was found, waiting until Blaze has stopped changing it"}[st])
        mid = str(m["id"]); info = self.sup_read(story)
        if any(x == mid for x, _ in info["clips"]):                                    # already there (the automatic attach, or the desk, got there first): nothing is sent
            self.sup_registry(story, m, info, None, info["item_id"]); return self.sup_end(j, "DONE", "The file %s is already in the story: nothing was sent" % m["title"], {"mos": mid})
        fs = {str(x) for x in info["shows"]}
        if fs and show not in fs: return self.sup_end(j, "BLOCKED", "Blaze does not list this story in the chosen bulletin any more (it lists %s): nothing was sent" % (", ".join(sorted(fs)) or "none"))
        if self.fmt.get(story) not in self.c.verified: return self.sup_end(j, "BLOCKED", "story format %s: the itemId rule is not verified (BLAZE_VERIFIED_FORMATS): the desk attaches this one by hand" % self.fmt.get(story))
        if info["item_id"] is None: return self.sup_end(j, "BLOCKED", "the story has no script item, so Blaze would not know where to put the clip")
        pos = self.posin.get((show, story)); pos = self.pos.get(story) if pos is None else pos
        if not isinstance(pos, int): return self.sup_wait(j, "Queued: the story's row in this bulletin is not known yet")
        if self.led.live_opens(story): return self.sup_wait(j, "Queued: an earlier attach for this story has not settled yet")        # the automatic attach rule: nothing new is sent for a story while an attempt is unclear
        order = pos + 1
        if not self.sup_claim(j, "Attaching now", media_id=mid, media_name=m["title"]): return
        before = {x["id"] for x in info["rows"]}
        self.event("SUPPORT ADD", "request %s by %s: %s -> story %s \"%s\" (show %s) | order=%s itemId=%s | sending now%s" % (j["id"], j.get("by_user"), m["title"], story, title, show, order, info["item_id"], " (BLAZE_ATTACH=dry: sent because an editor confirmed it)" if self.c.attach != "live" else ""), attach_call(story, show, m, order, info["item_id"]))
        try:
            with self.b.quick(story): self.b.attach(story, show, m, order, info["item_id"])
        except SessionExpired as e: return self.sup_end(j, "FAILED", "The session expired while sending: it is unclear whether the clip arrived. Look at the story in Blaze. Nothing is sent again.")
        except BlazeError as e: return self.sup_end(j, "FAILED", "Blaze refused the attach (%s)" % e)
        except Exception as e: return self.sup_end(j, "FAILED", "The attach call failed (%s: %s): it is unclear whether the clip arrived. Look at the story in Blaze. Nothing is sent again." % (type(e).__name__, e))
        try: after = self.sup_read(story)
        except Exception as e: return self.sup_end(j, "FAILED", "The attach was sent but Blaze did not answer the read-back (%s: %s). Look at the story in Blaze. Nothing is sent again." % (type(e).__name__, e))
        new = [x for x in after["rows"] if x["id"] not in before]
        if not (len(new) == 1 and new[0]["mos"] == mid and len(after["rows"]) == len(before) + 1):
            return self.sup_end(j, "FAILED", "The read-back does not show exactly one new clip with this file (new clips: %s, %d -> %d clips). Check the story in Blaze. Nothing is sent again." % (",".join("%s=%s" % (x["id"], x["mos"]) for x in new) or "none", len(before), len(after["rows"])))
        with self.b.quick(story): self.live_duration(None, story, info, after)         # the script duration, as the Blaze page does after an attach (same rule as the automatic attach)
        self.sup_registry(story, m, after, new[0], info["item_id"])
        self.sup_end(j, "DONE", "Attached: %s was added to the story (%d clip(s) in it now)" % (m["title"], len(after["rows"])), {"mos": mid, "clip_id": new[0]["id"]})
    def sup_registry(self, story, m, after, new, item_id):
        """If the registry has a clip ID for this file in this story, mark it ATTACHED now (the same call the automatic attach makes), so the dashboard is right at once. A problem here never matters to the request."""
        try:
            key = media_key(m.get("title")); rs = [x for x in self.rows if x.get("blaze_story_id") == story and not x.get("deleted") and key and rkey(x) == key]
            if rs: self.confirm_group(rs[0], story, after, m, "blaze_live", new=new, item_id=item_id)
        except Exception as e: say("Quick Support: the registry was not updated for story %s (%s: %s): the next read of the story does it" % (story, type(e).__name__, e))

    # ---------- REMOVE ----------
    def sup_remove(self, j):
        story, cid = j["blaze_story_id"], str(j["blaze_clip_id"])
        why = self.sup_gate(j)
        if why: return self.sup_end(j, "BLOCKED", why)
        info = self.sup_read(story); row = next((x for x in info["rows"] if str(x["id"]) == cid), None)
        if row is None: return self.sup_end(j, "DONE", "The clip is not in the story any more: nothing to delete", {"mos": None})
        if j.get("clip_title") and (row["title"] or "").strip() != j["clip_title"].strip(): return self.sup_end(j, "BLOCKED", "Blaze clip %s is now called %r, not %r: the story changed. Open the list again and choose the clip" % (cid, row["title"], j["clip_title"]))
        if not self.sup_claim(j, "Deleting now"): return
        self.event("SUPPORT DELETE", "request %s by %s: removing clip %s (%s) from story %s \"%s\" | sending now%s" % (j["id"], j.get("by_user"), cid, row["title"], story, j.get("story"), " (BLAZE_ATTACH=dry: sent because an editor confirmed it)" if self.c.attach != "live" else ""), "DELETE /DataService/stories/%s/clips/%s" % (story, cid))
        try:
            with self.b.quick(story): self.b.delete_clip(story, cid)
        except SessionExpired: return self.sup_end(j, "FAILED", "The session expired while deleting: it is unclear whether the clip was deleted. Look at the story in Blaze. Nothing is sent again.")
        except BlazeError as e: return self.sup_end(j, "FAILED", "Blaze refused the delete (%s)" % e)
        except Exception as e: return self.sup_end(j, "FAILED", "The delete call failed (%s: %s): it is unclear whether the clip was deleted. Look at the story in Blaze. Nothing is sent again." % (type(e).__name__, e))
        try: after = self.sup_read(story)
        except Exception as e: return self.sup_end(j, "FAILED", "The delete was sent but Blaze did not answer the read-back (%s: %s). Look at the story in Blaze. Nothing is sent again." % (type(e).__name__, e))
        if any(str(x["id"]) == cid for x in after["rows"]) or len(after["rows"]) != len(info["rows"]) - 1:
            return self.sup_end(j, "FAILED", "The read-back is not as expected (clip still there: %s, %d -> %d clips). Check the story in Blaze. Nothing is sent again." % (any(str(x["id"]) == cid for x in after["rows"]), len(info["rows"]), len(after["rows"])))
        with self.b.quick(story): self.live_duration(None, story, info, after)
        self.sup_end(j, "DONE", "Deleted: %s was removed from the story (%d clip(s) left in it)" % (row["title"], len(after["rows"])), {"mos": row["mos"], "clip_id": cid})

    # ---------- after a restart ----------
    def sup_recover(self, j):
        """A request that was WORKING when this program stopped (or whose result could not be reported): whether it went through is unclear, so it is settled by READING the story. Never sent again."""
        story = j["blaze_story_id"]; info = self.sup_read(story)
        if j["kind"] == "ADD":
            mid = str(j["media_id"] or "")
            if mid and any(x == mid for x, _ in info["clips"]): return self.sup_end(j, "DONE", "Attached: %s is in the story (settled by reading the story after a restart)" % j.get("media_name"), {"mos": mid})
            return self.sup_end(j, "FAILED", "It is unclear whether the clip was attached (the program stopped in the middle) and the file is not in the story. Look at the story in Blaze. Nothing is sent again.")
        if not any(str(x["id"]) == str(j["blaze_clip_id"]) for x in info["rows"]): return self.sup_end(j, "DONE", "The clip is gone from the story (settled by reading the story after a restart)", {"mos": None, "clip_id": j["blaze_clip_id"]})
        self.sup_end(j, "FAILED", "It is unclear whether the delete was sent (the program stopped in the middle) and the clip is still in the story. Look at the story in Blaze. Nothing is sent again.")
