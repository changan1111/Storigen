"""Poller: find each clip's media object in Blaze's media list."""
from __future__ import annotations
import time
from .errors import SessionExpired
from .keys import find_indexed, find_media, index_media, rkey
from .util import say


class MediaMixin:
    def prefetch_media(self, rows):
        """Find the Blaze file of every clip in `rows`. List mode (default, v9.7.4): read the day's media list ONCE per round (1 to 5 requests, whatever the number of clips), match every clip in code and remember
        the answer for each; a clip that is not in the list is simply checked again next round. Only when the list could not be read, or is too long to be read whole (clips not in it may still exist), the
        affected clips are searched by title one by one (search_media). Clips with the same name share one answer."""
        rows = [r for r in rows if rkey(r)]
        if not rows: return
        if self.c.media_mode == "list":
            rest = self.list_media(rows)
            if rest is not None: rows = rest
        self.search_media(rows)
    def list_media(self, rows):
        """-> None when there is no usable list (every clip falls back to the title search), else the clips the list cannot settle (not in it, but the list was cut short): [] when all are settled.
        The list is read like every other Blaze read: in the pool, never longer than the round's deadline. An answer that is late is used by the next round; meanwhile the last list (at most
        a few rounds old) is used, so a slow Blaze never turns into 40 extra searches."""
        now = time.time()
        def one(_):
            try: return "ok", self.rt(lambda: self.b.media_pages(self.c.days, self.c.media_page, self.c.media_max_pages))
            except SessionExpired as e: return "expired", e
            except Exception as e: return "err", e
        got = self.pool_map(one, [0], "medialist")
        for kind, val in got[-1:]:                                                          # the newest answer if an older late one also came in
            if kind == "expired": raise val
            if kind == "err":
                if not self.list_err: say("media list could not be read (%s: %s): searching clip by clip until it works again" % (type(val).__name__, val))
                self.list_err = True; return None
            medias, total, complete = val
            if self.list_err: say("media list readable again"); self.list_err = False
            if not complete and not self.list_partial: say("WARNING: Blaze has %s files in the last %d day(s) but only %d were read (BLAZE_MEDIA_MAX_PAGES x BLAZE_MEDIA_PAGE): clips not among them are searched by title" % (total, self.c.days, len(medias)))
            self.list_partial = not complete; self.mlist = (now, index_media(medias), complete)
        if not self.mlist or now - self.mlist[0] > max(120, 4 * self.c.poll): return []     # nothing usable yet (Blaze is slow): these clips are looked at again next round
        _, idx, complete = self.mlist; rest = []
        for r in rows:
            st, m = find_indexed(idx, rkey(r), self.c.settle)
            if st == "missing" and not complete: rest.append(r); continue            # may be beyond the part of the list that was read: ask Blaze by title
            self.mcache[r["display_id"]] = (now, st, m)
        return rest
    def search_media(self, rows):
        """The v9.7.3 way (BLAZE_MEDIA_MODE=search, and the fallback of list mode): search Blaze's media list by title for the clips that are due, in parallel and in a bounded batch, so 600+ clips never turn one round into a long queue of single requests.
        Clips whose export the watcher has seen are searched every BLAZE_MEDIA_RETRY_SECS; clips with no export seen yet, every BLAZE_MEDIA_WAIT_SECS, oldest first, BLAZE_MEDIA_BATCH per pass."""
        now = time.time(); due = []
        for r in rows:
            key = rkey(r)
            if not key: continue
            c = self.mcache.get(r["display_id"]); wait = self.c.media_wait if r["state"] == "WAITING_FOR_CLIP" else self.c.retry
            if c is None or now - c[0] >= wait: due.append((0 if r["state"] != "WAITING_FOR_CLIP" else 1, c[0] if c else 0, r, key))
        due = [(r, key) for _, _, r, key in sorted(due, key=lambda x: (x[0], x[1]))[: self.c.media_batch]]
        def one(item):
            r, key = item
            try: return r, key, "ok", self.rt(lambda: self.b.media_search(key[0], self.c.days))
            except SessionExpired as e: return r, key, "expired", e
            except Exception as e: return r, key, "err", e
        for r, key, kind, val in self.pool_map(one, due, "media", key=lambda it: it[0]["display_id"]):
            if kind == "expired": raise val
            if kind == "err": continue                                               # searched again next pass
            medias, total = val
            if total and total > len(medias): say("WARNING: Blaze has %s files matching %s but returned only %d: raise the page size" % (total, key[0], len(medias)))
            st, m = find_media(medias, key, self.c.settle); self.mcache[r["display_id"]] = (now, st, m)
    def prefetch_info(self, stories):
        """The story details behind a plan line (item, linked shows), read in parallel, a bounded batch, and kept for BLAZE_INFO_SECS."""
        now = time.time(); due = [x for x in dict.fromkeys(stories) if x not in self.info_cache or now - self.info_cache[x][0] >= self.c.info_secs][: self.c.recon_batch]
        def one(sid):
            try: return sid, "ok", self.rt(lambda: self.b.story_info(sid))
            except SessionExpired as e: return sid, "expired", e
            except Exception as e: return sid, "err", e
        for sid, kind, val in self.pool_map(one, due, "info"):
            if kind == "expired": raise val
            if kind == "ok": self.info_cache[sid] = (now, val)
    def tell_media(self, did, m):
        """Blaze's media object (mosObjectId) for this clip was found: tell the registry once per media id, so the dashboard's NITRO step turns green. Records a fact only; sends nothing to Blaze."""
        name = str(m.get("title") or m.get("description") or "").strip()[:120]; k, v = "media:" + did, str(m["id"]) + "|" + name
        if self.led.get(k) == v: return
        try: self.a.call("/svc/media", {"display_id": did, "media_id": str(m["id"]), "media_name": name}); self.led.put(k, v)
        except Exception: pass       # tried again next round
