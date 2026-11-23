"""v10.17.0: the poller tells the server EVERY clip Blaze holds in a story (not only the ones Storigen made IDs for), so a clip added by hand shows on the dashboard and the chat sees it.
Reading only: it sends nothing to Blaze. It sits in its own mixin (before SupportMixin) so that support.py, the file that writes to Blaze, stays exactly as it was."""
from __future__ import annotations
import time


class ClipReportMixin:
    def sup_read(self, story):
        """Same read as Quick Support always made (story_info), and the full clip list is reported to the server after it: after every Support list, add and delete."""
        info = self.rt(lambda: self.b.story_info(story)); self.report_clips(story, info); return info
    def report_clips(self, story, info, force=False):
        """Sent when the list changed, or at most every 10 minutes when it did not (so the server knows it is still fresh). A problem here never matters to the caller."""
        try:
            if info.get("partial"): return
            clips = [{"id": str(x["id"]), "mos": str(x.get("mos") or ""), "title": x.get("title") or "", "dur_s": None if x.get("dur") is None else int(x["dur"] // 1000)} for x in info.get("rows") or []]
            raw = repr(sorted((c["id"], c["mos"], c["title"]) for c in clips)); sent = self.__dict__.setdefault("_clips_sent", {}); now = time.time(); was = sent.get(story)
            if not force and was and was[0] == raw and now - was[1] < 600: return
            self.a.call("/svc/story_clips", {"story": str(story), "clips": clips}); sent[story] = (raw, now)
        except Exception: pass
