"""Server methods for sign-in, roles and user management."""
from __future__ import annotations
from .security import NOT_VALID, PERMS, ROLES, access_state, check_password, days_left, hash_password, make_token, verify_token
import datetime as dt, os, time, uuid
from .db import now_iso
from .ids import suffix_on
from .common import APP_VERSION, EMAIL_RE, HttpError
from . import quality, clipsummary, scanassets

class AuthMixin:
    def profile(self, cur, uid):
        u = cur.one("SELECT * FROM users WHERE id=?", (uid,))
        if u: u["active"] = bool(u["active"])
        return u
    def user_view(self, p):
        t = self.local_today(); ok, why = access_state(p, t, self.cfg["valid_required"]); vu = p.get("valid_upto")
        return {"id": p["id"], "email": p["email"], "username": p["email"], "name": p.get("full_name"), "role": p["role"], "active": p["active"],
                "valid_upto": str(vu) if vu else None, "days_left": days_left(p, t), "valid": ok, "status": "valid" if ok else why}
    def not_valid(self, why):
        c = self.cfg["admin_contact"]; return NOT_VALID.format(why=why) + (" " + c if c else "")
    def authenticate(self, r, perm):
        uid = verify_token(r.cookie("sid"), self.cfg["secret"])
        if not uid: raise HttpError(401, "login required")
        with self.db.tx() as cur: p = self.profile(cur, uid)
        ok, why = access_state(p, self.local_today(), self.cfg["valid_required"])
        if not ok: raise HttpError(401, self.not_valid(why))
        if perm not in PERMS[p["role"]]: raise HttpError(403, "not allowed for your role")
        u = self.user_view(p); u["perms"] = sorted(PERMS[p["role"]]); return u
    def throttled(self, keys):
        now = time.time(); return any(self.fail.get(k, (0, 0))[0] >= 5 and now - self.fail[k][1] < 60 for k in keys)
    def bootstrap_admin(self, env=None):
        e = env if env is not None else os.environ; email = (e.get("ADMIN_EMAIL") or "").strip().lower(); pw = e.get("ADMIN_PASSWORD") or ""
        with self.db.tx() as cur:
            if cur.one("SELECT 1 AS x FROM users WHERE role='admin'"): return False
            if not email or len(pw) < 8: print("No admin exists and ADMIN_EMAIL / ADMIN_PASSWORD (8+ chars) are not set: run `python3 autoid.py init`.", flush=True); return False
            until = self.local_today() + dt.timedelta(days=int(e.get("ADMIN_VALID_DAYS", "3650"))); salt, h = hash_password(pw)
            cur.x("INSERT INTO users(id,email,full_name,role,active,valid_upto,pw_salt,pw_hash,created_at) VALUES(?,?,?,?,1,?,?,?,?)",
                  (str(uuid.uuid4()), email, "Administrator", "admin", until.isoformat(), salt, h, now_iso()))
            self.log(cur, "system", "first_admin_created", {"user": email, "valid_upto": until}); print("first admin created: %s" % email, flush=True); return True
    def a_login(self, r):
        b = r.body; email = (b.get("email") or "").strip().lower(); pw = b.get("password") or ""; keys = ("e:" + email, "i:" + r.client)
        if self.throttled(keys): raise HttpError(429, "too many attempts, wait a minute")
        if len(self.fail) > 2000: self.fail.clear()
        with self.db.tx() as cur:
            p = self.profile(cur, (cur.one("SELECT id FROM users WHERE email=?", (email,)) or {}).get("id", ""))
            if not p or not check_password(pw, p["pw_salt"], p["pw_hash"]):
                for k in keys: self.fail[k] = (self.fail.get(k, (0, 0))[0] + 1, time.time())
                self.log(cur, email, "login_failed", {}); raise HttpError(401, "wrong email or password")
            for k in keys: self.fail.pop(k, None)
            ok, why = access_state(p, self.local_today(), self.cfg["valid_required"])
            if not ok: self.log(cur, email, "login_blocked", {"reason": why}); raise HttpError(403, self.not_valid(why))
            self.log(cur, email, "login_ok", {"role": p["role"]})
        tok = make_token(p["id"], self.cfg["secret"], self.cfg["session_secs"])
        r.set_cookies.append("sid=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d%s" % (tok, self.cfg["session_secs"], "; Secure" if self.cfg["cookie_secure"] else ""))
        u = self.user_view(p); u["perms"] = sorted(PERMS[p["role"]]); return u
    def a_logout(self, r): r.set_cookies.append("sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"); return {"ok": True}
    def a_me(self, r): return r.user
    def manual_enabled(self): return self.cfg["link_mode"] == "placeholder" or self.cfg["allow_manual"] == "1"
    def a_config(self, r):
        return {"story_url": self.cfg["story_url"], "version": APP_VERSION, "link_mode": self.cfg["link_mode"], "watcher_enabled": self.cfg["watcher_enabled"], "manual_enabled": self.manual_enabled(), "quick_attach": self.cfg["quick_attach"], "support": self.cfg.get("support", True), "support_wait_min": self.cfg.get("support_wait_min", 60), "script_labels": self.cfg["script_labels"], "preview": os.getenv("PREVIEW_ENABLED", "1") != "0", "version_suffix": suffix_on(), "keep_days": self.cfg.get("keep_days", 7), "quality": quality.enabled(), "frames": clipsummary.frames_enabled(), "ai_summary": clipsummary.ai_available(), "scan": scanassets.status(), "standards_key": clipsummary.key() != "", "features": self.feat_view()}
    def admins_still_valid(self, cur, excluding):
        t = self.local_today()
        for p in cur.q("SELECT * FROM users WHERE role='admin' AND id<>?", (excluding,)):
            p["active"] = bool(p["active"])
            if access_state(p, t, self.cfg["valid_required"])[0]: return True
        return False
    def a_users(self, r):
        with self.db.tx() as cur: return [self.user_view({**p, "active": bool(p["active"])}) for p in cur.q("SELECT * FROM users ORDER BY email")]
    def a_add_user(self, r):
        b = r.body; email = (b.get("email") or "").strip().lower(); role = b.get("role"); pw = b.get("password") or ""; vu = b.get("valid_upto") or None
        if not EMAIL_RE.match(email): raise HttpError(400, "enter a valid email address")
        if role not in ROLES: raise HttpError(400, "role must be editor or admin")
        if len(pw) < 8: raise HttpError(400, "password needs 8+ characters")
        if vu is None and self.cfg["valid_required"]: raise HttpError(400, "valid upto date is required (the user cannot log in without it)")
        if vu:
            try: dt.date.fromisoformat(vu)
            except ValueError: raise HttpError(400, "valid upto must be a date like 2027-03-31")
        with self.db.tx() as cur:
            if cur.one("SELECT 1 AS x FROM users WHERE email=?", (email,)): raise HttpError(409, "that email already has a login; edit it in the list instead")
            salt, h = hash_password(pw); uid = str(uuid.uuid4())
            cur.x("INSERT INTO users(id,email,full_name,role,active,valid_upto,pw_salt,pw_hash,created_at) VALUES(?,?,?,?,1,?,?,?,?)", (uid, email, (b.get("full_name") or "").strip() or None, role, vu, salt, h, now_iso()))
            self.log(cur, r.user["username"], "user_created", {"user": email, "role": role, "valid_upto": vu}); return self.user_view(self.profile(cur, uid))
    def a_edit_user(self, r):
        uid, ch = r.m[0], {k: v for k, v in r.body.items() if k in ("role", "valid_upto", "active", "full_name")}
        if not ch: raise HttpError(400, "nothing to change")
        if "role" in ch and ch["role"] not in ROLES: raise HttpError(400, "role must be editor or admin")
        if "valid_upto" in ch and not ch["valid_upto"] and self.cfg["valid_required"]: raise HttpError(400, "valid upto date cannot be empty")
        with self.db.tx() as cur:
            old = self.profile(cur, uid)
            if not old: raise HttpError(404, "no such user")
            new = {**old, **ch}; still = new["role"] == "admin" and new["active"] and access_state(new, self.local_today(), self.cfg["valid_required"])[0]
            if uid == r.user["id"] and not still: raise HttpError(409, "you cannot remove your own admin access (ask another admin)")
            if old["role"] == "admin" and not still and not self.admins_still_valid(cur, uid): raise HttpError(409, "this is the last valid admin: make another admin first")
            sets = {k: (int(v) if k == "active" else (v or None)) for k, v in ch.items()}
            cur.x("UPDATE users SET " + ",".join("%s=?" % k for k in sets) + " WHERE id=?", list(sets.values()) + [uid])
            self.log(cur, r.user["username"], "user_changed", {"user": old["email"], **ch}); return self.user_view(self.profile(cur, uid))
    def a_password(self, r):
        pw = r.body.get("password") or ""
        if len(pw) < 8: raise HttpError(400, "password needs 8+ characters")
        with self.db.tx() as cur:
            p = self.profile(cur, r.m[0])
            if not p: raise HttpError(404, "no such user")
            salt, h = hash_password(pw); cur.x("UPDATE users SET pw_salt=?, pw_hash=? WHERE id=?", (salt, h, p["id"]))
            self.log(cur, r.user["username"], "user_password_reset", {"user": p["email"]}); return {"ok": True}
