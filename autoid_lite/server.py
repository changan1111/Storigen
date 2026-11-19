"""Storigen (lite): ID registry + web page + service API in ONE standard-library Python program.
SQLite, no Docker, nothing to pip-install. Runs the same on Mac and Windows.

LINK_MODE decides how a clip is tied to its Blaze story:
  placeholder  the journalist types rundown + story name, gets an ID, and pastes it into the placeholder's Media Slug in the right story.
  story_id     IDs are made automatically when a feed (MOS gateway, tap, poller, script) reports a story with Blaze's own story ID
               (POST /svc/stories); the desk opens the story from a link built from that ID.
Both modes share the same ID format, watcher, states and desk buttons."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .db import DB, now_iso
from pathlib import Path
from .ids import broadcast_day, display_id, id_format, name_id, norm_name
from .config import data_dir
import datetime as dt, json, os, re, secrets, sys, threading, time, urllib.parse
from .alerts import send_alert, send_ready
from .api_auth import AuthMixin  # noqa: F401  (re-export: other code and the tests use server.<name>)
from .api_dashboard import DashboardMixin  # noqa: F401  (re-export: other code and the tests use server.<name>)
from .api_service import ServiceMixin  # noqa: F401  (re-export: other code and the tests use server.<name>)
from .common import APP_VERSION, EMAIL_RE, HOLD, HttpError, MAX_BODY, Req, STATES, norm, opt, removed_message, settings_from_env  # noqa: F401  (re-export: other code and the tests use server.<name>)

class App(ServiceMixin, AuthMixin, DashboardMixin):
    def __init__(self, cfg, db_path, web_dir=None):
        self.cfg = cfg; self.db = DB(db_path); self.web_dir = Path(web_dir or Path(__file__).parent / "web")
        if len(cfg["api_key"]) < 16 or len(cfg["secret"]) < 32:
            raise SystemExit("SERVICE_API_KEY (16+ chars) and SESSION_SECRET (32+ chars) are required. Run: python3 autoid.py init")
        self.fail = {}; self._tz = None
        self.routes = [(m, re.compile("^" + p + "$"), fn, auth) for m, p, fn, auth in [
            ("GET", "/healthz", self.h_healthz, None),
            ("POST", "/svc/stories", self.s_story, "svc"), ("POST", "/svc/rundowns/sync", self.s_sync, "svc"),
            ("POST", "/svc/stories/rename", self.s_rename, "svc"), ("POST", "/svc/stories/delete", self.s_delete, "svc"),
            ("GET", "/svc/match", self.s_match, "svc"), ("POST", "/svc/files", self.s_files, "svc"), ("POST", "/svc/heartbeat", self.s_heartbeat, "svc"), ("POST", "/svc/alert", self.s_alert, "svc"),
            ("POST", "/svc/attach/confirm", self.s_confirm, "svc"), ("POST", "/svc/media", self.s_media, "svc"), ("POST", "/svc/replaced", self.s_replaced, "svc"), ("POST", "/svc/quickattach/result", self.s_qa_result, "svc"), ("POST", "/svc/why", self.s_why, "svc"), ("POST", "/svc/scripts", self.s_scripts, "svc"), ("GET", "/svc/status", self.s_status, "svc"), ("GET", "/svc/clips", self.s_clips, "svc"),
            ("POST", "/api/login", self.a_login, None), ("POST", "/api/logout", self.a_logout, None),
            ("GET", "/api/me", self.a_me, "view"), ("GET", "/api/config", self.a_config, "view"), ("GET", "/api/status", self.a_status, "view"),
            ("GET", "/api/clips", self.a_clips, "view"), ("GET", "/api/feed", self.a_feed, "view"), ("GET", "/api/rundowns", self.a_rundowns, "view"), ("POST", "/api/manual", self.a_manual, "create"),
            ("POST", r"/api/clips/(\d+)/version", self.a_version, "version"), ("GET", r"/api/clips/(\d+)/scope", self.a_scope, "view"), ("POST", r"/api/clips/(\d+)/delete_version", self.a_delete_version, "version"), ("POST", r"/api/clips/(\d+)/attached", self.a_attached, "attach"), ("POST", r"/api/clips/(\d+)/quickattach", self.a_quickattach, "attach"),
            ("GET", r"/api/clips/(\d+)/history", self.a_history, "view"), ("GET", r"/api/clips/(\d+)/preview", self.a_preview, "view"), ("GET", "/api/events", self.a_events, "events"),
            ("GET", "/api/users", self.a_users, "users"), ("POST", "/api/users", self.a_add_user, "users"),
            ("PATCH", r"/api/users/([\w-]+)", self.a_edit_user, "users"), ("POST", r"/api/users/([\w-]+)/password", self.a_password, "users")]]

    # ---------- time ----------
    def now(self):
        if self.cfg["tz"]:
            try:
                from zoneinfo import ZoneInfo
                if self._tz is None: self._tz = ZoneInfo(self.cfg["tz"])
                return dt.datetime.now(self._tz).replace(tzinfo=None)
            except Exception: pass                          # no tz database (Windows without tzdata): fall back to the machine's clock
        return dt.datetime.now()
    def today(self): return broadcast_day(self.now(), self.cfg["day_start"])
    def local_today(self): return self.now().date()          # valid-upto is a calendar date in the newsroom's time zone

    # ---------- helpers ----------
    def log(self, cur, actor, action, details):
        cur.x("INSERT INTO events(time,actor,action,details) VALUES(?,?,?,?)", (now_iso(), actor, action, json.dumps(details, default=str)))
    def alert(self, text): threading.Thread(target=send_alert, args=(text,), daemon=True).start()
    def ready_notify(self, text): threading.Thread(target=send_ready, args=(text,), daemon=True).start()      # v10.2.0: 'this clip is ready' to a chat; no-op without READY_WEBHOOK_URL
    def next_seq(self, cur, day):
        d = day.isoformat(); cur.x("INSERT INTO counters(day,last) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET last=last+1", (d,))
        return cur.one("SELECT last FROM counters WHERE day=?", (d,))["last"]
    def new_clip(self, cur, story_id, slug, day, seq, version=1, name=None):
        """display_id is the unique INTERNAL ID of this story's clip (date, daily number, check letter, name). name_id is the clip NAME the editor puts on the file:
        DDMMYY_STORY_NAME[_Vn], the same for every story with that name that day (a repeated story uses one clip). ID_FORMAT=legacy: no separate name."""
        did = display_id(day, seq, slug, version)
        if id_format() == "legacy": name = None
        elif name is None:
            st = cur.one("SELECT blaze_story_id FROM stories WHERE id=?", (story_id,)); name = name_id(day, slug, st and st["blaze_story_id"]) + ("_V%d" % version if version > 1 else "")
        cid = cur.insert("INSERT INTO clip_ids(display_id,day,seq,story_id,version,created_at,name_id) VALUES(?,?,?,?,?,?,?)", (did, day.isoformat(), seq, story_id, version, now_iso(), name))
        return cur.one("SELECT * FROM clip_ids WHERE id=?", (cid,))
    @staticmethod
    def name_rows(cur, key):
        """Every clip row (one per story) that shares this clip name (case does not matter)."""
        return cur.q("SELECT * FROM clip_ids WHERE UPPER(COALESCE(name_id, display_id))=? ORDER BY id", (norm_name(key),))
    def get_rundown(self, cur, rid, name=None, start=None):
        r = cur.one("SELECT id, name, start_at FROM rundowns WHERE blaze_rundown_id=?", (rid,))
        if r:
            if name and name != r["name"]: cur.x("UPDATE rundowns SET name=? WHERE id=?", (name, r["id"]))
            if start and start != r["start_at"]: cur.x("UPDATE rundowns SET start_at=? WHERE id=?", (start, r["id"]))
            return r["id"]
        return cur.insert("INSERT INTO rundowns(blaze_rundown_id,name,air_date,start_at) VALUES(?,?,?,?)", (rid, name, self.today().isoformat(), start))
    @staticmethod
    def need(body, *keys):
        miss = [k for k in keys if body.get(k) in (None, "")]
        if miss: raise HttpError(422, "missing field: " + ", ".join(miss))

    # ---------- stories: create, refresh, remove (shared by every feed) ----------
    def hold_clips(self, cur, ids, why):
        """ON_NITRO / ATTACH_SUBMITTED clips of these stories -> NEEDS_DESK. Returns their display IDs."""
        if not ids: return []
        ph = ",".join("?" * len(ids)); w = "story_id IN (%s) AND state IN ('ON_NITRO','ATTACH_SUBMITTED')" % ph
        held = [r["display_id"] for r in cur.q("SELECT display_id FROM clip_ids WHERE " + w, ids)]
        cur.x("UPDATE clip_ids SET state='NEEDS_DESK', attach_error=? WHERE " + w, [removed_message(why)] + list(ids))
        return held
    def remove_stories(self, cur, rid, reason, only=None, keep=None):
        where, args = "rundown_id=? AND deleted=0", [rid]
        if only is not None: where += " AND blaze_story_id=?"; args.append(only)
        if keep: where += " AND blaze_story_id NOT IN (%s)" % ",".join("?" * len(keep)); args += list(keep)
        rows = cur.q("SELECT id, blaze_story_id FROM stories WHERE " + where, args); ids = [r["id"] for r in rows]
        if ids:
            cur.x("UPDATE stories SET deleted=1, deleted_at=?, deleted_reason=? WHERE id IN (%s)" % ",".join("?" * len(ids)), [now_iso(), reason] + ids)
        held = self.hold_clips(cur, ids, "this story was removed from the rundown in Blaze (%s)" % reason)
        if rows: self.log(cur, "mos", "stories_removed", {"rundown_id": rid, "reason": reason, "stories": [r["blaze_story_id"] for r in rows], "held": held})
        return ids, held
    def story_removed(self, cur, did):
        r = cur.one("SELECT s.deleted FROM clip_ids c JOIN stories s ON s.id=c.story_id WHERE c.display_id=? AND c.state<>'ATTACHED'", (did,))
        return bool(r and r["deleted"])
    def hold_one(self, cur, did, why):
        if cur.x("UPDATE clip_ids SET state='NEEDS_DESK', attach_error=? WHERE display_id=? AND state IN ('ON_NITRO','ATTACH_SUBMITTED','NEEDS_DESK')", (removed_message(why), did)):
            self.alert("%s: its story is no longer in the rundown (%s). Desk: check Blaze before attaching." % (did, why))
    def rename_clips(self, cur, sid, story_key, old_slug, new_slug, notes=None, old_key=None):
        """v10.9.1: a story was renamed in Blaze (same Blaze story ID, new slug title). Its clip NAME (name_id, DDMMYY_STORY_NAME[_Vn] / [_Un]) was made from the old title and never followed it, so the desk kept being told the OLD name.
        Every clip of the story that is still WAITING_FOR_CLIP (no file seen, nothing sent) gets the name of the new title, its _V / _U ending kept. A clip whose file is already on its way, on Nitro or attached keeps its name: the file carries it.
        display_id (the internal ID) never changes. The old name is remembered so that a file still exported under it gets a clear answer. Returns the list of (old name, new name)."""
        if id_format() != "name" or not (new_slug or "").strip(): return []
        out = []
        for c in cur.q("SELECT id, day, state, name_id FROM clip_ids WHERE story_id=? ORDER BY id", (sid,)):
            if not c["name_id"]: continue
            try: day = dt.date.fromisoformat(c["day"])
            except (TypeError, ValueError): continue
            ob, nb = name_id(day, old_slug, old_key or story_key), name_id(day, new_slug, story_key)
            if ob.upper() == nb.upper(): continue                                           # the title changed but the file-safe name is the same (case, punctuation)
            if c["state"] != "WAITING_FOR_CLIP":
                if notes is not None: notes.append({"kept": c["name_id"], "state": c["state"]})
                continue
            if not c["name_id"].upper().startswith(ob.upper()): continue                    # not made from the old title (typed / imported): leave it alone
            new = nb + c["name_id"][len(ob):]
            cur.x("UPDATE clip_ids SET name_id=? WHERE id=?", (new, c["id"]))
            cur.x("INSERT OR IGNORE INTO clip_old_names(clip_id, name, changed_at) VALUES(?,?,?)", (c["id"], norm_name(c["name_id"]), now_iso()))
            out.append((c["name_id"], new))
        if out:
            self.log(cur, "mos", "story_renamed", {"blaze_story_id": story_key, "from": old_slug, "to": new_slug, "clips": [{"from": a, "to": b} for a, b in out]})
            if notes is not None: notes.append({"renamed": out, "from": old_slug, "to": new_slug})
        return out
    @staticmethod
    def old_name_hint(cur, key):
        """v10.9.1: a clip name that belongs to a story's earlier title -> (old name, current name) or None."""
        return cur.one("SELECT o.name AS old, COALESCE(c.name_id, c.display_id) AS cur FROM clip_old_names o JOIN clip_ids c ON c.id=o.clip_id WHERE o.name=? ORDER BY o.changed_at DESC LIMIT 1", (norm_name(key),))
    def upsert_story_row(self, cur, rid, story_id, slug, slug_id=None, pos=None, story_title=None, notes=None, old_key=None):
        """Create or refresh one story. -> (first clip, created, restored). `notes` (a list, optional) collects what the caller should tell the desk after the transaction (v10.9.1: renames)."""
        row = cur.one("SELECT id, deleted, slug FROM stories WHERE rundown_id=? AND blaze_story_id=?", (rid, story_id))
        if row:
            if slug and row["slug"] and slug.strip() != row["slug"].strip(): self.rename_clips(cur, row["id"], story_id, row["slug"], slug, notes, old_key)      # v10.9.1: the story was renamed in Blaze
            cur.x("UPDATE stories SET slug=COALESCE(NULLIF(?,''),slug), slug_id=COALESCE(?,slug_id), position=COALESCE(?,position), story_title=COALESCE(NULLIF(?,''),story_title), last_seen_at=?, deleted=0, deleted_at=NULL, deleted_reason=NULL WHERE id=?", (slug, slug_id, pos, story_title, now_iso(), row["id"]))
            if row["deleted"]:
                cur.x("UPDATE clip_ids SET attach_error=? WHERE story_id=? AND state='NEEDS_DESK' AND attach_error LIKE ?",
                      (HOLD + "this story left the rundown and has since reappeared. Check Blaze, then press Mark attached.", row["id"], HOLD + "%"))
                self.log(cur, "mos", "story_restored", {"blaze_story_id": story_id, "rundown_id": rid})
            return cur.one("SELECT * FROM clip_ids WHERE story_id=? ORDER BY version LIMIT 1", (row["id"],)), False, bool(row["deleted"])
        sid = cur.insert("INSERT INTO stories(blaze_story_id,rundown_id,slug,slug_id,position,story_title,last_seen_at) VALUES(?,?,?,?,?,?,?)", (story_id, rid, slug, slug_id, pos, story_title or None, now_iso()))
        day = self.today(); clip = self.new_clip(cur, sid, slug, day, self.next_seq(cur, day))
        self.log(cur, "mos", "clip_id_created", {"display_id": clip["display_id"], "story": story_id})
        self.hint_possible_move(cur, rid, story_id)
        return clip, True, False
    def hint_possible_move(self, cur, rid, story_id):
        """Blaze reports a move between rundowns as delete + insert. If the same story ID was just removed elsewhere, tell the desk; never move a clip by guesswork."""
        new_name = (cur.one("SELECT name FROM rundowns WHERE id=?", (rid,)) or {}).get("name") or "another rundown"
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - self.cfg["move_hint"]))
        for old in cur.q("SELECT s.id, r.name FROM stories s JOIN rundowns r ON r.id=s.rundown_id WHERE s.blaze_story_id=? AND s.rundown_id<>? AND s.deleted=1 AND s.deleted_at>?", (story_id, rid, since)):
            cur.x("UPDATE clip_ids SET attach_error=? WHERE story_id=? AND state='NEEDS_DESK' AND attach_error LIKE ?",
                  (HOLD + "the same story ID has just appeared in rundown '%s'. If the story was moved, attach this clip there by hand." % new_name, old["id"], HOLD + "%"))
            self.log(cur, "mos", "possible_story_move", {"blaze_story_id": story_id, "from": old["name"], "to": new_name})

    # ---------- service endpoints (X-API-Key): watcher, MOS gateway, any feed ----------
    def route(self, req):
        if req.method == "GET" and req.path in ("/", "/index.html"):
            return 200, (self.web_dir / "index.html").read_bytes(), "text/html; charset=utf-8"
        if req.method == "GET" and (req.path == "/report" or req.path.startswith("/report/")): return self.report_page(req)
        if req.method == "GET" and req.path == "/api/clips.csv": return self.clips_csv(req)
        for method, rx, fn, auth in self.routes:
            m = rx.match(req.path)
            if method != req.method or not m: continue
            req.m = m.groups()
            if auth == "svc":
                if not secrets.compare_digest(req.headers.get("X-API-Key", ""), self.cfg["api_key"]): raise HttpError(401, "bad api key")
            elif auth: req.user = self.authenticate(req, auth)
            out = fn(req); return 200, out, getattr(out, "ctype", "application/json")
        raise HttpError(404, "not found")

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"; server_version = "AutoID"
    def log_message(self, *a): pass
    def _go(self):
        app = self.server.app; url = urllib.parse.urlsplit(self.path); body = {}; req = None
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY: raise HttpError(413, "request too large")
            raw = self.rfile.read(n) if n else b""
            if self.command in ("POST", "PATCH") and url.path.startswith("/api/") and "json" not in (self.headers.get("Content-Type") or "").lower():
                raise HttpError(415, "JSON required")        # also blocks cross-site form posts
            if raw:
                try: body = json.loads(raw)
                except ValueError: raise HttpError(400, "bad JSON")
                if not isinstance(body, dict): raise HttpError(400, "JSON object expected")
            req = Req(self.command, url.path, dict(urllib.parse.parse_qsl(url.query)), body, self.headers); req.client = self.client_address[0]
            status, payload, ctype = app.route(req)
        except HttpError as e: status, payload, ctype = e.status, {"detail": e.detail, **e.extra}, "application/json"
        except Exception as e:
            print("ERROR %s %s: %r" % (self.command, url.path, e), file=sys.stderr, flush=True); status, payload, ctype = 500, {"detail": "internal error"}, "application/json"
        if hasattr(payload, "run"):      # v10.1.0: a live video stream (preview.py): no Content-Length, nothing stored; the connection closes when it ends
            try:
                self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close"); self.end_headers(); self.close_connection = True; payload.run(self.wfile)
            except OSError: pass
            finally: payload.release()
            return
        data = payload if isinstance(payload, bytes) else json.dumps(payload, default=str).encode()
        self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if req and getattr(req, "filename", None): self.send_header("Content-Disposition", 'attachment; filename="%s"' % req.filename)
        for c in (req.set_cookies if req else []): self.send_header("Set-Cookie", c)
        self.end_headers(); self.wfile.write(data)
    do_GET = do_POST = do_PATCH = _go

def serve(app, host="0.0.0.0", port=8080):
    srv = ThreadingHTTPServer((host, port), Handler); srv.daemon_threads = True; srv.app = app; return srv

def main():
    from .config import apply_env, data_dir
    apply_env(); cfg = settings_from_env(); dd = data_dir(); dd.mkdir(parents=True, exist_ok=True)
    app = App(cfg, dd / "autoid.db"); app.bootstrap_admin()
    threading.Thread(target=app.monitor, daemon=True).start()
    host, port = os.getenv("WEB_HOST", "0.0.0.0"), int(os.getenv("WEB_PORT", "8080"))
    print("Storigen %s listening on http://%s:%d (LINK_MODE=%s)" % (APP_VERSION, host, port, cfg["link_mode"]), flush=True)
    serve(app, host, port).serve_forever()

if __name__ == "__main__": main()
