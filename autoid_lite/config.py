"""Settings come from autoid.env (KEY=VALUE lines, # comments) in the program folder, overridden by real environment variables."""
from __future__ import annotations
import os, stat
from pathlib import Path

HOME = Path(os.getenv("AUTOID_HOME") or Path(__file__).resolve().parents[1])

def env_path(): return Path(os.getenv("AUTOID_ENV") or HOME / "autoid.env")
def data_dir(): return Path(os.getenv("DATA_DIR") or HOME / "data")

def load_env(path=None):
    p = Path(path) if path else env_path(); out = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, _, v = line.partition("="); v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'": v = v[1:-1]
            out[k.strip()] = v
    return out

def set_env(updates, path=None):
    """Change (or append) KEY=VALUE lines in autoid.env, leaving every other line, comment and blank line exactly as it is. Written to a temp file and swapped in, so a crash never leaves half a file."""
    p = Path(path) if path else env_path()
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []; todo = dict(updates); out = []
    for line in lines:
        k = line.partition("=")[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and k in todo: out.append("%s=%s" % (k, todo.pop(k)))
        else: out.append(line)
    out += ["%s=%s" % kv for kv in todo.items()]
    mode = stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o600                    # the file holds the API key, the session secret and the Blaze login: keep it as private as it was (init makes it 600)
    tmp = p.with_name(p.name + ".tmp"); fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh: fh.write("\n".join(out) + "\n")
    try: os.chmod(tmp, mode)
    except OSError: pass
    os.replace(tmp, p)

def apply_env(path=None):
    """Put the file's settings into the process environment (real environment variables win)."""
    for k, v in load_env(path).items(): os.environ.setdefault(k, v)
