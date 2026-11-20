"""Blaze DataService client (read only apart from the safety wall) and the Auto-ID server client."""
from __future__ import annotations
import contextlib
import datetime as dt
import json
import re
import threading
import time
import urllib.error, urllib.parse, urllib.request
from . import snapshot as snap
from .people import people_of
from .errors import BlazeError, LoginFailed, SessionExpired
from .keys import attach_body
from .safety import ForbiddenCall, check_call


def script_texts(items, cap=20000):
    """v9.13.2: the two script fields of a story, from GET /stories/<id>/complete/ -> versions[0].items[]: `text1` and `text2`. A story can have several items: each field is the items' texts in arrangeOrder, a blank line between,
    empty ones left out. -> {"online": text1 text, "anchor": text2 text}. Text is kept as Blaze sends it (Tamil and other scripts included): only trimmed at both ends and cut at `cap` characters."""
    order = sorted(items, key=lambda i: i.get("arrangeOrder") if isinstance(i.get("arrangeOrder"), (int, float)) else 1e9)
    join = lambda k: "\n\n".join(t.strip() for t in (i.get(k) for i in order) if isinstance(t, str) and t.strip())[:cap]
    return {"online": join("text1"), "anchor": join("text2")}


# ---------------------------------------------------------------- Blaze (read only)
class Blaze:
    def __init__(self, c): self.c = c; self._tl = threading.local(); self.put_at = 0.0                 # one Blaze object is shared by the reader threads: nothing mutable is shared between them
    @contextlib.contextmanager
    def quick(self, story_id):
        """v9.13: the ONE exception to "BLAZE_ATTACH=dry never writes": inside this block, on THIS thread only, an attach (and the script-duration update the page sends after it) is allowed for exactly this one story.
        Used only for a "Quick test attach" an editor confirmed with Yes on the dashboard. Every other write rule (check_call, one attempt per clip, read-back, kill switch) still applies."""
        self._tl.quick_story = str(story_id)
        try: yield
        finally: self._tl.quick_story = None
    def quick_ok(self, story_id): return getattr(self._tl, "quick_story", None) == str(story_id)
    status = property(lambda self: getattr(self._tl, "status", None))                              # status of the last call made by THIS thread
    def call(self, method, path, params=None, form=None):
        check_call(method, path)
        p = dict(params or {}); hdr = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest", "Referer": self.c.blaze + "/blaze/", "User-Agent": "autoid-lite/1",
                                       "Cookie": "sessionId=%s; username=%s" % (self.c.sid, self.c.user)}
        if method == "GET": p["_"] = int(time.time() * 1000)
        data = None
        if form is not None: data = urllib.parse.urlencode(form).encode(); hdr["Content-Type"] = "application/x-www-form-urlencoded"
        elif method in ("PUT", "POST"): data = b""
        req = urllib.request.Request(self.c.blaze + path + ("?" + urllib.parse.urlencode(p) if p else ""), method=method, data=data, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=self.c.timeout) as r: body = r.read().decode("utf-8", "replace"); ct = r.headers.get("Content-Type", ""); self._tl.status = r.status
        except urllib.error.HTTPError as e:
            eb = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
            if e.code == 400 and "invalid.sessionId" in eb: raise SessionExpired("Blaze answered 400 invalid.sessionId: the session cookie is not valid any more")      # v9.8.1: seen 2026-11-13, an expired or replaced session
            if e.code in (401, 403) or (e.code == 404 and "authenticationFailed" in eb): raise SessionExpired("Blaze answered %d%s: the session cookie is not valid any more" % (e.code, " authenticationFailed" if e.code == 404 else ""))   # seen in the capture: an expired session is a 404 {"errors":["authenticationFailed"]}
            raise BlazeError(e.code, eb)
        if not body.strip(): return None
        if "json" not in ct and body.lstrip().startswith("<"): raise SessionExpired("Blaze returned a web page, not data (login page?): the session cookie has expired")
        return json.loads(body)
    def get(self, path, params=None): return self.call("GET", path, params)
    def login(self):
        """POST /DataService/sessions exactly as the Blaze page does (captured 2026-11-12): form fields username, password (the page's hash of it) and _ (milliseconds). Blaze answers 201 with an empty body and the new
        session ID twice: in Set-Cookie (sessionId=...;Version=1) and in Location (.../sessions/<id>). -> the new session ID. Nothing is printed about the password, and the Cfg is NOT switched here (Cfg.use_session does that)."""
        check_call("POST", "/DataService/sessions"); c = self.c
        hdr = {"Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest", "Referer": c.blaze + "/blaze/", "User-Agent": "autoid-lite/1", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if c.sid: hdr["Cookie"] = "sessionId=%s; username=%s" % (c.sid, c.user)                    # the page sends its old cookies too
        data = urllib.parse.urlencode([("username", c.user), ("password", c.pw), ("_", int(time.time() * 1000))]).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(c.blaze + "/DataService/sessions", method="POST", data=data, headers=hdr), timeout=c.timeout) as r:
                cookies = " ".join(r.headers.get_all("Set-Cookie") or []); loc = r.headers.get("Location") or ""
        except urllib.error.HTTPError as e: raise LoginFailed("Blaze refused the login (HTTP %d): check BLAZE_USERNAME and BLAZE_PASSWORD_HASH" % e.code)
        except (urllib.error.URLError, OSError) as e: raise LoginFailed("could not reach Blaze for the login (%s)" % getattr(e, "reason", e))
        m = re.search(r"sessionId=([^;,\s]+)", cookies) or re.search(r"/sessions/([^/?#\s]+)\s*$", loc)
        if not m: raise LoginFailed("Blaze accepted the login but sent no session ID")
        return m.group(1)
    def ping(self):
        """Keep-alive, as the Blaze page does it (2.2 hours captured): GET /sessions/<id> once a minute and PUT /sessions/<id> every 8 minutes. page = both at that rhythm; get, put and both (every call) remain possible."""
        h, now = self.c.heartbeat, time.time()
        if not self.put_at: self.put_at = now                                  # the 8-minute clock starts with the first call, like the page's
        if h in ("page", "get", "both"): self.call("GET", "/DataService/sessions/" + self.c.sid)
        if h in ("put", "both") or (h == "page" and now - self.put_at >= 480): self.call("PUT", "/DataService/sessions/" + self.c.sid); self.put_at = now

    def slugs(self, show):
        j = self.get("/DataService/shows/%s/slugs" % show) or {}; sl = j.get("slugs", j) if isinstance(j, dict) else j
        out = []
        for s in ([sl] if isinstance(sl, dict) else sl or []):
            if s.get("deleted") in (1, True): continue
            st = s.get("storyId") or {}
            if st.get("id") is None: continue
            out.append({"story_id": str(st["id"]), "slug_id": str(s.get("id")), "title": s.get("slugTitle") or st.get("title") or "", "pos": s.get("finalPosition"), "format": str((st.get("storyFormatId") or {}).get("id")), "clips": st.get("clipCount"),
                        "clip_dur": st.get("clipDur"), "clip_status": st.get("clipStatus"), "clip_state": s.get("clipState"), "cg": st.get("cgCount"), "story_title": st.get("title") or "",
                        "editor": (str(s.get("comment") or "").strip()[:120] if "comment" in s else None)})      # v10.9.5: the slug's comment = the editor's name (None when this Blaze list does not carry the field: nothing is wiped)    # the attachment signals the slug list carries for free
        return out
    def story_media(self, story_id):
        """The identity of every MEDIA clip of a story, from the cheap clip list (about 16 ms; /complete/ took about 167 ms in the capture): Blaze clip ID, media object ID, objId, title, duration, position."""
        j = self.get("/DataService/stories/%s/clips" % story_id, {"clipType": "media"}) or {}
        return [snap.clip_row(c) for c in (j.get("clips") if isinstance(j, dict) else j) or [] if isinstance(c, dict) and str(c.get("clipType", "MEDIA")).upper() == "MEDIA"]
    def show_name(self, show):
        try:
            j = self.get("/DataService/shows/%s" % show) or {}; j = j.get("shows") or j.get("show") or j
            for k in ("title", "showName", "name", "displayName", "showTitle"):       # the real field is title (showName does not exist)
                if isinstance(j, dict) and isinstance(j.get(k), str) and j[k].strip(): return j[k].strip()
        except Exception: pass
        return "SHOW %s" % show
    def media(self, days):
        today = dt.date.today(); f = lambda d: d.strftime("%d/%m/%Y")
        flt = json.dumps({"mosId": "QuickEdge", "fromDate": f(today - dt.timedelta(days=days - 1)), "toDate": f(today)}, separators=(",", ":"))
        j = self.get("/DataService/mosobjects", {"assetsPerPage": 200, "filter": flt, "channelId": 1}) or {}
        return (j.get("results") or {}).get("medias") or []
    def _list_pages(self, days, per_page, max_pages, seen, out, extra=None, group=None):
        """One walk through /DataService/mosobjects pages (newest first). `extra` = more filter fields (the group). Files already in `seen` are not added twice. -> (rows read, totalResults, complete, filter_ignored).
        filter_ignored: the answer to a group query holds files of OTHER groups, i.e. Blaze does not know that filter key (the walk stops after page 1)."""
        today = dt.date.today(); f = lambda d: d.strftime("%d/%m/%Y")
        flt = json.dumps({"mosId": "QuickEdge", **(extra or {}), "fromDate": f(today - dt.timedelta(days=days - 1)), "toDate": f(today)}, separators=(",", ":"))
        n, total, ms = 0, None, []
        for page in range(1, max_pages + 1):
            res = (self.get("/DataService/mosobjects", {"assetsPerPage": per_page, "pageNo": page, "channelId": 1, "filter": flt}) or {}).get("results") or {}
            ms = res.get("medias") or []; total = res.get("totalResults", total); n += len(ms)
            if group and any(m.get("objGroup") not in (None, "", group) for m in ms): return n, total, False, True
            for m in ms:
                if m.get("id") is not None and m["id"] not in seen: seen.add(m["id"]); out.append(m)
            if (isinstance(total, int) and n >= total) or (not isinstance(total, int) and len(ms) < per_page) or not ms: break
        return n, total, (n >= total if isinstance(total, int) else len(ms) < per_page), False
    def media_pages(self, days, per_page=200, max_pages=5):
        """The media list of the last `days` days, newest first: the plain list (what the Blaze page asks for when its search box is empty; 156 files for one day in the capture) and, v10.9.3, ONE LIST PER GROUP
        (BLAZE_MEDIA_GROUPS, filter key BLAZE_MEDIA_GROUP_KEY): the plain list holds only one group (NEWS), so a PROGRAMS / PROMOS / ADS file was never found and never attached.
        -> (medias, totalResults, complete). complete is False when files may be missing (more than max_pages x per_page, or Blaze stopped answering pages). self.group_info says what each group gave."""
        seen, out = set(), []
        _, total, complete, _ = self._list_pages(days, per_page, max_pages, seen, out)
        info = self.group_info = getattr(self, "group_info", {})
        for g in getattr(self.c, "media_groups", []):
            st = info.setdefault(g, {"state": "ok", "files": 0, "fails": 0})
            if st["state"] in ("ignored", "off"): continue
            try: n, gt, gc, ignored = self._list_pages(days, per_page, max_pages, seen, out, {self.c.media_group_key: g}, g)
            except SessionExpired: raise
            except Exception as e:                                                        # one group failing never hides the others
                st["fails"] += 1; st["error"] = "%s: %s" % (type(e).__name__, e)
                if st["fails"] >= 3: st["state"] = "off"
                continue
            st["fails"] = 0; st.pop("error", None)
            if ignored: st["state"] = "ignored"; continue
            st["files"] = n; complete = complete and gc
        return out, total, complete
    def day_shows(self, d1, d2=None):
        """The shows Blaze lists for a date range (the call the rundown panel makes). dates are sent as DD/MM/YY. -> [{id, title, start, slugs, master}]"""
        f = json.dumps({"fromDate": d1.strftime("%d/%m/%y"), "toDate": (d2 or d1).strftime("%d/%m/%y")}, separators=(",", ":"))
        out = []
        for x in (self.get("/DataService/shows", {"filter": f, "channelId": 1}) or {}).get("shows") or []:
            if isinstance(x, dict) and x.get("id") is not None:
                out.append({"id": str(x["id"]), "title": (x.get("title") or "").strip(), "start": x.get("startTime"), "slugs": x.get("slugCount"), "master": None if x.get("masterId") is None else str(x["masterId"])})
        return out
    def set_script_dur(self, story_id, version_id, seconds, wpm):
        """The page's follow-up to every attach or delete: PUT /stories/<id>/versions/<versionId> scriptDur=<seconds>&wpm=<n> (observed 64, 124, 277 for three clips of 64 s, 60 s, 153 s; wpm 100)."""
        if self.c.attach != "live" and not self.quick_ok(story_id): raise ForbiddenCall("the script-duration update is only allowed with BLAZE_ATTACH=live (now %s)" % self.c.attach)
        return self.call("PUT", "/DataService/stories/%s/versions/%s" % (story_id, version_id), form={"scriptDur": int(seconds), "wpm": int(wpm)})
    def media_search(self, text, days, per_page=50):
        """Search Blaze's media list by title text (the page sends this on every keystroke). -> (medias, totalResults). Whether title matches a prefix or any part is not confirmed, so callers still check the name themselves.
        v10.9.3: when the plain search finds nothing, the same search is made inside each group (BLAZE_MEDIA_GROUPS)."""
        today = dt.date.today(); f = lambda d: d.strftime("%d/%m/%Y"); dates = {"fromDate": f(today - dt.timedelta(days=days - 1)), "toDate": f(today)}
        def ask(extra):
            flt = json.dumps({"title": text, "mosId": "QuickEdge", **extra, **dates}, separators=(",", ":"))
            res = (self.get("/DataService/mosobjects", {"assetsPerPage": per_page, "pageNo": 1, "channelId": 1, "filter": flt}) or {}).get("results") or {}
            return res.get("medias") or [], res.get("totalResults")
        ms, total = ask({})
        if ms: return ms, total
        out, seen, tot = [], set(), 0
        for g in getattr(self.c, "media_groups", []):
            if (getattr(self, "group_info", {}).get(g) or {}).get("state") in ("ignored", "off"): continue
            try: gm, gt = ask({self.c.media_group_key: g})
            except SessionExpired: raise
            except Exception: continue
            if any(m.get("objGroup") not in (None, "", g) for m in gm): continue          # the filter key is not known to Blaze: these are not this group's files
            for m in gm:
                if m.get("id") not in seen: seen.add(m.get("id")); out.append(m)
            tot += gt if isinstance(gt, int) else len(gm)
        return out, (tot if out else total)
    def story_info(self, story_id):
        """One read of GET /stories/<id>/complete/ -> {clips: [(mosObjectId, title)], item_id, version_id, shows: [ids]}.
        item_id = the item with the lowest arrangeOrder in versions[0] (what the page sent in every observed attach); None when the story has no item."""
        sc = (self.get("/DataService/stories/%s/complete/" % story_id) or {}).get("storyComplete") or {}
        rows = [{"id": str(c.get("id")), "mos": str((c.get("mosObjectId") or {}).get("id")), "title": c.get("title") or "", "dur": c.get("duration") if isinstance(c.get("duration"), (int, float)) else None, "item": c.get("itemId")} for c in sc.get("clips") or []]
        clips = [(x["mos"], x["title"]) for x in rows]
        vs = sc.get("versions") or []; v = vs[0] if vs and isinstance(vs[0], dict) else {}
        items = [i for i in (v.get("items") or []) if isinstance(i, dict) and i.get("id") is not None]
        item = min(items, key=lambda i: i.get("arrangeOrder") if isinstance(i.get("arrangeOrder"), (int, float)) else 1e9) if items else None
        shows = [str(x.get("id")) for x in (sc.get("shows") or []) if isinstance(x, dict) and x.get("id") is not None]
        ver = {"scriptDur": v.get("scriptDur") or 0, "wpm": v.get("wpm") or 100}
        return {"scripts": script_texts(items), "title": sc.get("title"), "version": ver, "clips": clips, "rows": rows, "item_id": str(item["id"]) if item else None, "version_id": str(v["id"]) if v.get("id") is not None else None, "shows": shows, "people": people_of(sc)}
    def attach(self, story_id, show, m, order, item_id):
        """THE ONLY WRITE THAT ADDS ANYTHING TO BLAZE. POST /stories/<id>/clips/ with the form the page sends (doc section 8). 201 {"story_status","clip_status"}; the new clip ID is not in the reply."""
        if self.c.attach != "live" and not self.quick_ok(story_id): raise ForbiddenCall("attach is only allowed with BLAZE_ATTACH=live (now %s)" % self.c.attach)
        return self.call("POST", "/DataService/stories/%s/clips/" % story_id, form=attach_body(show, m, order, item_id))
    def delete_clip(self, story_id, clip_id):
        """Undo of an attach: DELETE /stories/<id>/clips/<clipId> -> {"story_status","clip_status","duration","itemId","deletedClipDur"}."""
        if self.c.attach != "live" and not self.quick_ok(story_id): raise ForbiddenCall("removing a clip is only allowed with BLAZE_ATTACH=live (now %s) or inside a confirmed Quick test" % self.c.attach)      # v10.5.0: like the attach
        return self.call("DELETE", "/DataService/stories/%s/clips/%s" % (story_id, clip_id))
    def story_clips(self, story_id): return self.story_info(story_id)["clips"]
    def story_media_ids(self, story_id): return {m for m, _ in self.story_clips(story_id)}


class AutoId:
    def __init__(self, c): self.c = c
    def call(self, path, payload=None):
        req = urllib.request.Request(self.c.autoid + path, method="POST" if payload is not None else "GET", headers={"Content-Type": "application/json", "X-API-Key": self.c.key},
                                     data=json.dumps(payload).encode() if payload is not None else None)
        with urllib.request.urlopen(req, timeout=10) as r: return json.loads(r.read())
    def alert(self, text):
        try: self.call("/svc/alert", {"text": text})
        except Exception: pass
