"""Poller: read every followed story's two script fields from Blaze and hand them to the Auto-ID registry (v9.13.2)."""
from __future__ import annotations
import time
from .errors import SessionExpired
from .util import say


class ScriptMixin:
    def read_scripts(self):
        """The two script fields of a story (storyComplete -> versions[0].items[].text1 / text2) are read for every story of the followed shows, a bounded batch per round, the story read longest ago first.
        A story never read before is first in line, so after the poller starts every story already in the registry is filled in within a few minutes (BLAZE_SCRIPT_BATCH per round), and a story that is new in
        the rundown is read in the very next round. Each story is read again every BLAZE_SCRIPT_SECS, so an edit in Blaze reaches the dashboard that soon. Only a changed text is sent to the registry.
        Reading only: nothing is ever written to Blaze, and a problem here never stops the polling round."""
        c = self.c
        if not c.scripts: return 0
        now = time.time(); seen = getattr(self, "script_at", None)
        if seen is None: seen = self.script_at = {}; self.script_sig = {}
        sids = list(dict.fromkeys(x["story_id"] for sh in c.shows for x in self.stories.get(sh, [])))
        for k in [k for k in seen if k not in set(sids)]: seen.pop(k, None); self.script_sig.pop(k, None)           # memory stays flat: a story that left the followed shows is forgotten
        due = sorted((s for s in sids if now - seen.get(s, 0) >= c.script_secs), key=lambda s: seen.get(s, 0))[: c.script_batch]
        if not due: return 0
        def one(sid):
            try: return sid, "ok", self.rt(lambda: (lambda i: dict(i["scripts"], people=i.get("people") or {}))(self.b.story_info(sid)))
            except SessionExpired as e: return sid, "expired", e
            except Exception as e: return sid, "err", e
        got, bad = {}, 0
        for sid, kind, val in self.pool_map(one, due, "script"):
            if kind == "expired": raise val
            if kind == "ok": got[sid] = val
            else: bad += 1
        sig = lambda v: (v["online"], v["anchor"], tuple(sorted((v.get("people") or {}).items())))      # v10.9.0: who created the story / who it is assigned to travels with the scripts (same read)
        send = [dict({"blaze_story_id": sid, "online": v["online"], "anchor": v["anchor"]}, **(v.get("people") or {})) for sid, v in got.items() if self.script_sig.get(sid) != sig(v)]
        sent = 0
        for i in range(0, len(send), 50):
            chunk = send[i:i + 50]
            try:
                self.a.call("/svc/scripts", {"stories": chunk}); sent += len(chunk)
                for x in chunk: self.script_sig[x["blaze_story_id"]] = sig(got[x["blaze_story_id"]])
            except Exception as e:                                                       # the registry did not take it: those stories are sent again next round
                for x in chunk: got.pop(x["blaze_story_id"], None)
                if "scripts" not in self.said: self.said.add("scripts"); say("could not send story scripts to the registry (%s: %s): they are sent again next round" % (type(e).__name__, e))
        for sid in got: seen[sid] = now
        if sent: self.stats.scripts_sent = getattr(self.stats, "scripts_sent", 0) + sent
        if bad and "scripts_read" not in self.said: self.said.add("scripts_read"); say("%d story script read(s) failed: they are repeated next round" % bad)
        return sent
