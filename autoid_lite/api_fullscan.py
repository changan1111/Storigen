"""v11.1.0 Full scan (Add media): the dashboard's Add media lists the files Quick Support already knows (the last BLAZE_MEDIA_DAYS days). With the 'Full scan' check box ON, the typed text is searched in ALL of Blaze's media
(BLAZE_FULLSCAN_DAYS days back, default 365) and the editor picks one of the files found. The check box is OFF by default, and everything with it OFF is exactly the old behaviour.
Nothing here writes to Blaze. A scan is a read-only LIST request that carries the search text (the poller answers it, see blaze/fullscan.py); an attach of a file found that way is the normal ADD request
(same Yes first, same poller rules, same read-back). It sits in its own mixin (before SupportMixin) so that api_support.py, the Quick Support source, stays exactly as it was."""
from __future__ import annotations
import re
from .api_support import NAME_MAX, TITLE_MAX, PICK_SECS, LIST_SECS, iso_in, sup_text
from .blaze.keys import media_key
from .common import HttpError, opt
from .db import now_iso


class FullScanMixin:
    def a_sup_find(self, r):
        """Ask the poller to search the whole Blaze media list for files whose name contains the typed text. Read only."""
        self.sup_on(); b = r.body; text = sup_text(b.get("name"), "the search text", NAME_MAX)
        if len(text) < 3: raise HttpError(422, "type at least 3 characters of the clip name to scan the full media list")
        with self.db.tx() as cur:
            st = self.sup_story(cur, opt(b.get("rundown")), opt(b.get("story"))); self.sup_expire(cur); sid = "find:" + st["blaze_story_id"]      # 'find:' keeps it apart from the delete picker's story list
            old = cur.one("SELECT id FROM support_jobs WHERE kind='LIST' AND state IN ('QUEUED','WORKING') AND blaze_story_id=? AND blaze_rundown_id=? AND media_name=? ORDER BY id DESC LIMIT 1", (sid, st["blaze_rundown_id"], text))
            if old: return {"id": old["id"]}
            jid = cur.insert("""INSERT INTO support_jobs(kind,state,by_user,created_at,updated_at,expires_at,blaze_rundown_id,rundown,blaze_story_id,story,media_name) VALUES('LIST','QUEUED',?,?,?,?,?,?,?,?,?)""",
                             (r.user["username"], now_iso(), now_iso(), iso_in(LIST_SECS), st["blaze_rundown_id"], st["rundown"], sid, self.sup_title(st), text))
            return {"id": jid}

    def a_sup_add(self, r):
        """Without full_scan: the Quick Support add, untouched. With full_scan: attach one exact Blaze file the Full scan found (it may be older than the registry's window)."""
        b = r.body
        if b.get("full_scan") is not True: return super().a_sup_add(r)
        self.sup_on()
        if b.get("confirm") is not True: raise HttpError(400, "confirmation missing: the editor must answer Yes")
        mid = opt(b.get("media_id")); title = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", sup_text(b.get("media_title"), "the clip title", TITLE_MAX))
        if not mid or not re.fullmatch(r"\d{1,18}", str(mid)) or not title or not media_key(title): raise HttpError(400, "pick one file from the Full scan list")
        with self.db.tx() as cur:
            st = self.sup_story(cur, opt(b.get("rundown")), opt(b.get("story"))); self.sup_expire(cur)
            for x in cur.q("SELECT id, media_id FROM support_jobs WHERE kind='ADD' AND state IN ('QUEUED','WORKING') AND blaze_story_id=?", (st["blaze_story_id"],)):
                if x["media_id"] == mid: raise HttpError(409, "this clip is already queued for this story (request %d)" % x["id"])
            jid = cur.insert("""INSERT INTO support_jobs(kind,state,by_user,created_at,updated_at,expires_at,blaze_rundown_id,rundown,blaze_story_id,story,media_id,media_name,msg) VALUES('ADD','QUEUED',?,?,?,?,?,?,?,?,?,?,?)""",
                             (r.user["username"], now_iso(), now_iso(), iso_in(PICK_SECS), st["blaze_rundown_id"], st["rundown"], st["blaze_story_id"], self.sup_title(st), mid, title, "Queued: waiting for the poller (Full scan)"))
            self.log(cur, r.user["username"], "support_add_queued", {"id": jid, "story": self.sup_title(st), "blaze_story_id": st["blaze_story_id"], "show": st["blaze_rundown_id"], "bulletin": st["rundown"], "media": title, "media_id": mid, "typed": False, "full_scan": True, "bulletin_aired": self.aired(st["start_at"])})
            return {"ok": True, "id": jid, "aired": self.aired(st["start_at"])}
