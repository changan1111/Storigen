"""A small stand-in for Blaze's DataService, for testing on your own machine. Stdlib only. Used by tools/demo.py.
It answers the same calls the poller makes (stories list, show info, media list, story clips, session ping) and accepts the attach POST,
so you can try the whole flow without touching the real Blaze. Any session cookie is accepted until you 'expire' it."""
from __future__ import annotations
import datetime as dt, http.server, json, re, threading, time, urllib.parse

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

class FakeBlaze:
    def __init__(self, show="34459", name="DEMO 12:00 Bulletin", seed=True):
        self.lock = threading.RLock(); self.show, self.name, self.expired = str(show), name, False
        self.stories, self.medias, self.requests = [], [], []
        b = int(time.time()) % 90000                     # new IDs on every start, so a restarted fake never reuses an ID the registry already knows
        self.n_story, self.n_slug, self.n_media, self.n_clip = 700000 + b, 2000000 + b, 1000000 + b, 1100000 + b
        if seed:
            for t, f in (("OPEN MONTAGE", 27), ("OPEN HEADLINE", 25), ("BREAK1", 30), ("HL - DEMO FLOOD 10 AM", 25), ("VO DEMO FLOOD DAMAGE 6 AM", 20), ("PKG DEMO BUDGET 9 AM", 23)): self.add(t, f)
    # ---- what an editor or the desk does in Blaze
    def add(self, title, fmt=20):
        with self.lock:
            self.n_story += 1; self.n_slug += 1; s = {"story": self.n_story, "slug": self.n_slug, "title": title, "fmt": int(fmt), "clips": []}; self.stories.append(s); return s
    def get(self, story_id): return next((s for s in self.stories if str(s["story"]) == str(story_id)), None)
    def rename(self, story_id, title):
        s = self.get(story_id); s and s.update(title=title); return s
    def delete(self, story_id):
        s = self.get(story_id)
        if s: self.stories.remove(s)
        return s
    def add_media(self, title, ms=50880, age=60):
        with self.lock:
            self.n_media += 1; m = {"id": self.n_media, "title": title, "duration": ms, "modified": time.time() - age}; self.medias.append(m); return m
    def item_of(self, story_id): return 930000 + int(story_id) % 10000            # the first script item of a story (lowest arrangeOrder)
    def attach(self, story_id, media_id, item=None):
        with self.lock:
            item = item or self.item_of(story_id)
            s, m = self.get(story_id), next((x for x in self.medias if x["id"] == int(media_id)), None)
            if not s or not m: return None
            self.n_clip += 1; c = {"id": self.n_clip, "mos": m["id"], "title": m["title"], "item": item, "dur": m["duration"]}; s["clips"].append(c); return c
    # ---- JSON in Blaze's shapes
    def slugs(self):
        return {"slugs": [{"id": s["slug"], "slugTitle": s["title"], "finalPosition": i + 1, "deleted": 0, "showId": {"id": int(self.show)},
                           "storyId": {"id": s["story"], "title": s["title"], "storyFormatId": {"id": s["fmt"]}, "clipCount": len(s["clips"]), "clipDur": sum(c["dur"] for c in s["clips"]), "cgCount": 0, "clipDone": 0, "clipStatus": "READY"}}
                          for i, s in enumerate(self.stories)]}
    def clip_list(self, story_id):
        s = self.get(story_id)
        return {"clips": [{"id": c["id"], "clipType": "MEDIA", "mosObjectId": {"id": c["mos"]}, "objId": "obj%d" % c["mos"], "title": c["title"], "duration": c["dur"], "position": k + 1, "status": "READY",
                           "createdTime": "2026-11-06T10:00:00+05:30"} for k, c in enumerate(s["clips"] if s else [])]}
    def media_json(self, text=""):
        ms = [m for m in reversed(self.medias) if text.lower() in m["title"].lower()]
        return {"results": {"assetsPerPage": 50, "currentPage": 1, "totalResults": len(ms), "medias": [{"id": m["id"], "title": m["title"], "description": m["title"], "duration": m["duration"], "mosId": "QuickEdge",
                "objGroup": "NEWS", "status": "NEW", "modifiedDate": dt.datetime.fromtimestamp(m["modified"], IST).isoformat(timespec="seconds")} for m in ms]}}
    def complete(self, story_id):
        s = self.get(story_id)
        if not s: return {"storyComplete": {}}
        it = self.item_of(story_id)
        return {"storyComplete": {"id": s["story"], "title": s["title"], "shows": [{"id": int(self.show)}],
                "versions": [{"id": it + 1, "items": [{"id": it + 1, "arrangeOrder": 2, "itemTypeId": {"id": 11}}, {"id": it, "arrangeOrder": 1, "itemTypeId": {"id": 10}}]}], "clips": [{"clipType": "MEDIA", "id": c["id"], "itemId": c["item"], "mosObjectId": {"id": c["mos"]}, "title": c["title"], "duration": c["dur"]} for c in s["clips"]]}}

def make_handler(fb):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass
        def send(self, code, obj, ctype="application/json"):
            b = (obj if isinstance(obj, str) else json.dumps(obj)).encode("utf-8"); self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def ok(self): return "sessionId=" in (self.headers.get("Cookie") or "") and not fb.expired
        def do_GET(self):
            u = urllib.parse.urlparse(self.path); p = u.path; fb.requests.append(("GET", p))
            if not self.ok(): return self.send(404, {"errors": [" authenticationFailed"]})        # what an expired session looks like (captured: 404 with this body)
            m = re.match(r"^/DataService/(shows|stories)/(\d+)(/.*)?$", p)
            if p == "/DataService/mosobjects":
                try: text = json.loads((urllib.parse.parse_qs(u.query).get("filter") or ["{}"])[0]).get("title", "")
                except ValueError: text = ""
                return self.send(200, fb.media_json(text))
            if re.match(r"^/DataService/sessions/[^/]+$", p): return self.send(200, {"user": {"id": 1}})
            if m and m.group(1) == "shows" and m.group(3) == "/slugs": return self.send(200, fb.slugs())
            if m and m.group(1) == "shows" and not m.group(3): return self.send(200, {"shows": {"id": int(m.group(2)), "title": fb.name, "duration": 1800, "createdTime": "2026-11-06T05:40:13+05:30"}})
            if m and m.group(1) == "stories" and m.group(3) == "/clips": return self.send(200, fb.clip_list(m.group(2)))
            if m and m.group(1) == "stories" and m.group(3) == "/complete/": return self.send(200, fb.complete(m.group(2)))
            self.send(404, {"error": "not in the fake"})
        def do_PUT(self):
            fb.requests.append(("PUT", urllib.parse.urlparse(self.path).path)); n = int(self.headers.get("Content-Length") or 0); n and self.rfile.read(n); self.send(200, "", "application/json")
        def do_DELETE(self):
            p = urllib.parse.urlparse(self.path).path; fb.requests.append(("DELETE", p)); m = re.match(r"^/DataService/stories/(\d+)/clips/(\d+)$", p); st = fb.get(m.group(1)) if m else None
            c = next((x for x in (st["clips"] if st else []) if str(x["id"]) == m.group(2)), None)
            if not c: return self.send(404, {"error": "no such clip"})
            st["clips"].remove(c); self.send(200, {"story_status": "READY", "clip_status": "READY", "duration": sum(x["dur"] for x in st["clips"]) // 1000, "itemId": c["item"], "deletedClipDur": c["dur"]})
        def do_POST(self):
            p = urllib.parse.urlparse(self.path).path; n = int(self.headers.get("Content-Length") or 0); form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8")) if n else {}
            fb.requests.append(("POST", p)); m = re.match(r"^/DataService/stories/(\d+)/clips/$", p)
            if m and fb.get(m.group(1)) and form.get("mosObjectId"):
                c = fb.attach(m.group(1), form["mosObjectId"][0], int((form.get("itemId") or ["0"])[0] or 0)); return self.send(201, {"story_status": "READY", "clip_status": "READY"}) if c else self.send(400, {})
            self.send(404, {"error": "not in the fake"})
    return H

def serve(fb, port=8099, host="127.0.0.1"):
    srv = http.server.ThreadingHTTPServer((host, port), make_handler(fb)); threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv

if __name__ == "__main__":
    fb = FakeBlaze(); serve(fb); print("Fake Blaze on http://127.0.0.1:8099 (show 34459). Ctrl+C to stop.")
    try:
        while True: time.sleep(3600)
    except KeyboardInterrupt: pass
