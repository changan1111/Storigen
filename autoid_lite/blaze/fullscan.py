"""v11.1.0 Full scan, the poller's part. Reading only: a Full scan is a search of Blaze's media list (BLAZE_FULLSCAN_DAYS days back); it sends nothing to Blaze but that search.
It sits in its own mixin (before SupportMixin) so that support.py, the file that writes to Blaze, stays exactly as it was. Attaching a file the scan found is the normal ADD request: same rules, same read-back."""
from __future__ import annotations
import re
from .keys import media_pending


class FullScanMixin:
    def sup_list(self, j):
        if not j.get("media_name"): return super().sup_list(j)                     # the delete picker's story list: untouched
        if not self.sup_claim(j, "Scanning the full media list in Blaze"): return
        text = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", (j.get("media_name") or "").strip()); days = getattr(self.c, "fullscan_days", 365)
        try: ms, total = self.rt(lambda: self.b.media_search(text, days, 100))
        except Exception as e: return self.sup_post(j, "FAILED", "Blaze did not answer (%s: %s)" % (type(e).__name__, e))
        low, seen, out = text.lower(), set(), []
        for m in ms:
            t = str(m.get("title") or m.get("description") or "")
            if m.get("id") is None or m["id"] in seen or low not in t.lower(): continue      # Blaze's search may match more loosely: only names that really contain the text are listed
            seen.add(m["id"]); out.append({"media_id": str(m["id"]), "name": t, "found_at": m.get("modifiedDate") or m.get("createdDate") or m.get("createdTime"), "group": m.get("objGroup"), "ready": not media_pending(m)})
        self.sup_post(j, "DONE", "%d file(s) found" % len(out), {"media": out, "days": days, "total": total if isinstance(total, int) else len(out), "text": text})
    def sup_find(self, j):
        """The normal look-up first. A file picked from the Full scan can be older than BLAZE_MEDIA_DAYS: only then is that EXACT file id looked for in the wide window (never by name alone)."""
        st, m = super().sup_find(j)
        if st != "missing" or not j.get("media_id") or not j.get("media_name"): return st, m
        from .keys import judge
        text = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", (j.get("media_name") or "").strip()); mid = str(j["media_id"])
        ms, _ = self.rt(lambda: self.b.media_search(text, getattr(self.c, "fullscan_days", 365), 100))
        return judge([x for x in ms if str(x.get("id")) == mid][:1], self.c.settle)
