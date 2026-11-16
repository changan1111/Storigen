#!/usr/bin/env python3
"""Polling benchmark against a SIMULATED Blaze whose response times are replayed from a real capture (deciles of the Blaze network capture: slug list median 310 ms, /complete/ 167 ms, clip list 16 ms,
show list 28 ms, media search 66 ms). 36 shows x 18 slugs = 648 stories, about 40% with one clip. It measures how long a polling round takes, and how many requests it makes.
It is NOT a measurement of a real Blaze or a real network: it shows how the engine behaves for a given latency profile.

  python3 tools/bench_polling.py --root /path/to/autoid-lite            run it against any version of the project (v9.3 for the 'before' figures)
"""
import argparse, http.server, json, pathlib, random, re, statistics, sys, tempfile, threading, time, types, urllib.parse as up

DECILES = {"slugs": [62, 75, 98, 173, 290, 310, 335, 378, 421, 501, 1060], "complete": [68, 116, 148, 154, 162, 167, 176, 185, 196, 208, 1271], "clips": [10, 13, 15, 16, 16, 16, 17, 17, 18, 20, 72],
           "shows": [21, 23, 24, 24, 27, 28, 40, 289, 310, 400, 456], "mosobjects": [52, 56, 58, 60, 63, 66, 73, 82, 192, 366, 1959]}
rng = random.Random(7)
def latency(kind):
    d = DECILES[kind]; i = rng.randrange(10); return (d[i] + rng.random() * (d[i + 1] - d[i])) / 1000.0

class World:
    def __init__(self, shows=36, per=18):
        self.shows, self.per = shows, per; self.counts = {}; self.lock = threading.Lock()
        self.slugs = {1000 + i: [self.slug(i, k) for k in range(per)] for i in range(shows)}; self.clips = {}
        for i in range(shows):
            for k in range(per):
                if (i * 7 + k * 3) % 5 < 2: self.set_clip(i, k, 6000 + i * 100 + k)
    def slug(self, i, k): return {"id": 900000 + i * 100 + k, "slugTitle": "STORY %d-%d" % (i, k), "finalPosition": k + 1, "deleted": 0, "clipState": "NONE", "storyId": {"id": 100000 + i * 100 + k, "storyFormatId": {"id": 21}, "clipCount": 0, "clipDur": 0, "clipStatus": "READY", "cgCount": 0}}
    def set_clip(self, i, k, mos, dur=50000):
        sid = str(100000 + i * 100 + k); self.clips[sid] = [{"id": int(sid) * 10, "clipType": "MEDIA", "mosObjectId": {"id": mos}, "objId": "o%d" % mos, "title": "clip%d.mxf" % mos, "duration": dur, "position": 1, "status": "READY"}]
        g = self.slugs[1000 + i][k]["storyId"]; g["clipCount"], g["clipDur"] = 1, dur
    def count(self, kind):
        with self.lock: self.counts[kind] = self.counts.get(kind, 0) + 1
    def show_list(self):
        now = time.time(); IST = __import__("datetime").timezone(__import__("datetime").timedelta(hours=5, minutes=30)); dt = __import__("datetime")
        return {"shows": [{"id": 1000 + i, "title": "09_11_%02d:%02d Bulletin" % (6 + i // 2, 30 * (i % 2)), "startTime": dt.datetime.fromtimestamp(now + (i - 18) * 1800, IST).isoformat(timespec="seconds"), "slugCount": self.per, "masterId": 10 + i % 12} for i in range(self.shows)]}

def serve(w):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def send(self, obj, code=200):
            b = json.dumps(obj).encode()
            try: self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
            except OSError: pass
        def do_PUT(self): self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()
        def do_GET(self):
            p = up.urlparse(self.path).path
            if re.fullmatch(r"/DataService/sessions/[^/]+", p): return self.send({})
            if p == "/DataService/shows": w.count("shows"); time.sleep(latency("shows")); return self.send(w.show_list())
            m = re.fullmatch(r"/DataService/shows/(\d+)/slugs", p)
            if m: w.count("slugs"); time.sleep(latency("slugs")); return self.send({"slugs": w.slugs[int(m.group(1))]})
            m = re.fullmatch(r"/DataService/shows/(\d+)", p)
            if m: return self.send({"shows": {"id": int(m.group(1)), "title": "SHOW"}})
            m = re.fullmatch(r"/DataService/stories/(\d+)/clips", p)
            if m: w.count("clips"); time.sleep(latency("clips")); return self.send({"clips": w.clips.get(m.group(1), [])})
            m = re.fullmatch(r"/DataService/stories/(\d+)/complete/", p)
            if m:
                w.count("complete"); time.sleep(latency("complete")); sid = m.group(1)
                return self.send({"storyComplete": {"title": "T" + sid, "shows": [], "versions": [{"id": 1, "scriptDur": 0, "wpm": 100, "items": [{"id": 5, "arrangeOrder": 1}]}], "clips": [{"id": c["id"], "mosObjectId": c["mosObjectId"], "title": c["title"], "duration": c["duration"]} for c in w.clips.get(sid, [])]}})
            if p == "/DataService/mosobjects": w.count("mosobjects"); time.sleep(latency("mosobjects")); return self.send({"results": {"totalResults": 0, "medias": []}})
            self.send({"error": "no"}, 404)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); srv.daemon_threads = True; threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--root", required=True); ap.add_argument("--rounds", type=int, default=3); a = ap.parse_args(); root = pathlib.Path(a.root).resolve()
    sys.modules["pytest"] = types.SimpleNamespace(fixture=lambda f=None, **k: (f if f else (lambda g: g)), raises=None, mark=None)
    sys.path[:0] = [str(root / "tools"), str(root / "tests"), str(root)]
    from test_server import Srv
    import blaze_poll as bp
    w = World(); blaze = serve(w); tmp = pathlib.Path(tempfile.mkdtemp()); s = Srv(tmp, "story_id")
    cfg = bp.Cfg({"BLAZE_URL": "http://127.0.0.1:%d" % blaze.server_address[1], "BLAZE_SESSION_ID": "S", "BLAZE_USERNAME": "u", "BLAZE_SHOW_IDS": "auto", "WEB_PORT": str(s.port), "SERVICE_API_KEY": "k" * 20,
                  "BLAZE_LEDGER": str(tmp / "l.db"), "BLAZE_REPORT_DIR": str(tmp / "r"), "BLAZE_IGNORE_TITLES": "BREAK"})
    p = bp.Poller(cfg); res = {"root": str(root), "engine": "parallel x%d" % getattr(cfg, "concurrency", 1) if hasattr(cfg, "concurrency") else "serial"}
    def rnd(label):
        w.counts.clear(); t = time.time(); p.cycle(); d = time.time() - t; res[label] = {"seconds": round(d, 2), "requests": dict(sorted(w.counts.items())), "total_requests": sum(w.counts.values())}; print(label, res[label], flush=True)
    rnd("initial_round")
    steady = []
    for k in range(a.rounds): rnd("steady_%d" % (k + 1)); steady.append(res["steady_%d" % (k + 1)]["seconds"])
    res["steady_median_s"] = round(statistics.median(steady), 2)
    w.set_clip(3, 2, 7001); w.set_clip(20, 5, 7002); w.slugs[1010][4]["storyId"]["id"] = 555001; w.slugs[1030].append(w.slug(30, 99)); w.slugs[1002].pop(3); w.set_clip(5, 1, 7003, dur=61000)
    p.last_rec = 0; rnd("busy_round_6_changes")
    if hasattr(p, "store"):                                  # the new engine records what it detected
        import collections; res["changes_detected"] = dict(collections.Counter(c["kind"] for c in p.store.changes())); res["attachment_changes"] = p.stats.attach_changes; print("detected:", res["changes_detected"], flush=True)
    print(json.dumps(res)); open(str(tmp / "bench.json"), "w").write(json.dumps(res)); print("RESULT_JSON " + json.dumps(res))
if __name__ == "__main__": main()
