"""Access rules for the web page: local logins, roles, and the valid-upto date. Roles: editor, admin (same operations; admin also manages users)."""
from __future__ import annotations
import datetime as dt, hashlib, hmac, secrets, time

ROLES = ("editor", "admin")
OPERATIONS = frozenset({"view", "create", "version", "attach", "events"})
PERMS = {"editor": OPERATIONS, "admin": OPERATIONS | {"users"}}
NOT_VALID = "Your access is not valid ({why}). Please contact the admin."

def access_state(profile, today, required=True):
    """(ok, reason). Allowed only if a profile exists with a known role, is active, and valid_upto is set and not passed
    (required=False lets an EMPTY valid_upto in; an expired date still blocks)."""
    if not profile: return False, "no access profile"
    if profile.get("role") not in ROLES: return False, "no valid role"
    if not profile.get("active"): return False, "account disabled"
    v = profile.get("valid_upto")
    if v in (None, ""): return (not required), "valid-upto date not set"
    try: d = v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])
    except ValueError: return False, "valid-upto date unreadable"
    if d < today: return False, "access expired on %s" % d.isoformat()
    return True, ""

def days_left(profile, today):
    v = (profile or {}).get("valid_upto")
    if v in (None, ""): return None
    d = v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])
    return (d - today).days

# ---- passwords: PBKDF2-SHA256, salted ----
def hash_password(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt, hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()

def check_password(pw, salt, want):
    return hmac.compare_digest(hash_password(pw, salt)[1], want)

# ---- session tokens: "<uid>.<expiry>.<hmac>" signed with the server secret ----
def make_token(uid, secret, seconds, now=None):
    exp = int((now or time.time()) + seconds); body = "%s.%d" % (uid, exp)
    return body + "." + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

def verify_token(token, secret, now=None):
    """-> uid or None (bad signature or expired)."""
    try: uid, exp, sig = (token or "").rsplit(".", 2)
    except ValueError: return None
    good = hmac.new(secret.encode(), ("%s.%s" % (uid, exp)).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good): return None
    try: return uid if int(exp) > (now or time.time()) else None
    except ValueError: return None
