#!/usr/bin/env python3
"""Storigen: where does the database space go?  Read-only: safe to run while the services are running.

    python3 tools/db_usage.py [data_dir]          (default: DATA_DIR or ./data)

Looks at autoid.db (registry, events, scripts) and blaze_ledger.db (poller snapshot, changes, ledger): file sizes incl. the -wal file,
size and rows per table, free space inside the file (VACUUM would give it back), and the biggest contributors per day."""
import os, sqlite3, sys, time
from pathlib import Path

def mb(n): return "%.2f MB" % ((n or 0) / 1048576)
def open_ro(p): c = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=30); c.row_factory = sqlite3.Row; return c
def q(c, sql, a=()):
    try: return c.execute(sql, a).fetchall()
    except sqlite3.Error as e: return []
def one(c, sql, a=()): r = q(c, sql, a); return r[0][0] if r else None

def files(p):
    print("  files:", ", ".join("%s %s" % (x.name, mb(x.stat().st_size)) for x in sorted(p.parent.glob(p.name + "*")) if x.is_file()))

def tables(c):
    ps = one(c, "PRAGMA page_size") or 4096; free = (one(c, "PRAGMA freelist_count") or 0) * ps
    print("  pages: %s used by data, %s free inside the file (reusable; VACUUM returns it)" % (mb((one(c, "PRAGMA page_count") or 0) * ps - free), mb(free)))
    dbstat = bool(q(c, "SELECT 1 FROM dbstat LIMIT 1"))
    out = []
    for r in q(c, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        t = r["name"]; n = one(c, 'SELECT COUNT(*) FROM "%s"' % t) or 0
        size = one(c, "SELECT SUM(pgsize) FROM dbstat WHERE name=?", (t,)) if dbstat else None
        out.append((size or 0, t, n))
    for size, t, n in sorted(out, reverse=True): print("  %-16s %9d rows  %s" % (t, n, mb(size) if dbstat else "(no dbstat in this SQLite)"))
    if not dbstat: print("  (this SQLite has no dbstat: sizes below are estimated from the text length)")
    return dbstat

def main():
    dd = Path(sys.argv[1] if len(sys.argv) > 1 else os.getenv("DATA_DIR", "data"))
    main_db, led = dd / "autoid.db", dd / "blaze_ledger.db"
    print("Storigen DB usage, %s   (%s)\n" % (dd.resolve(), time.strftime("%Y-%m-%d %H:%M")))
    if main_db.exists():
        c = open_ro(main_db); print("== autoid.db"); files(main_db); tables(c)
        print("\n  events per day (append-only: never deleted)")
        for r in q(c, "SELECT substr(time,1,10) d, COUNT(*) n, SUM(length(details)) b FROM events GROUP BY d ORDER BY d DESC LIMIT 7"): print("    %s %7d events %s" % (r["d"], r["n"], mb(r["b"])))
        print("  events by kind (all time)")
        for r in q(c, "SELECT actor||'.'||action k, COUNT(*) n, SUM(length(details)) b FROM events GROUP BY k ORDER BY b DESC LIMIT 6"): print("    %-30s %7d  %s" % (r["k"], r["n"], mb(r["b"])))
        print("\n  story scripts (online + anchor text kept per story row)")
        r = q(c, "SELECT COUNT(*) n, SUM(length(CAST(online_script AS BLOB))+length(CAST(anchor_script AS BLOB))) b, MAX(length(CAST(online_script AS BLOB))+length(CAST(anchor_script AS BLOB))) m FROM stories WHERE online_script IS NOT NULL OR anchor_script IS NOT NULL")
        if r and r[0]["n"]: print("    %d stories hold %s of script text (largest one %s B)" % (r[0]["n"], mb(r[0]["b"]), r[0]["m"]))
        print("  script text per clip day")
        for r in q(c, "SELECT ci.day d, COUNT(DISTINCT s.id) n, SUM(length(CAST(s.online_script AS BLOB))+length(CAST(s.anchor_script AS BLOB))) b FROM stories s JOIN clip_ids ci ON ci.story_id=s.id GROUP BY d ORDER BY d DESC LIMIT 5"): print("    %s %6d stories %s" % (r["d"], r["n"], mb(r["b"])))
        print("  rows per day: clip_ids / stories")
        for r in q(c, "SELECT day d, COUNT(*) n FROM clip_ids GROUP BY d ORDER BY d DESC LIMIT 5"): print("    %s %6d clips" % (r["d"], r["n"]))
    else: print("no", main_db)
    print()
    if led.exists():
        c = open_ro(led); print("== blaze_ledger.db (poller)"); files(led); tables(c)
        print("\n  snap_change per day (every position / title / clip change is a row; kept 14 days)")
        for r in q(c, "SELECT day d, COUNT(*) n, SUM(length(old)+length(new)) b FROM snap_change GROUP BY d ORDER BY d DESC LIMIT 5"): print("    %s %7d changes %s" % (r["d"], r["n"], mb(r["b"])))
        print("  snap_change by kind")
        for r in q(c, "SELECT kind, COUNT(*) n FROM snap_change GROUP BY kind ORDER BY n DESC LIMIT 8"): print("    %-16s %7d" % (r["kind"], r["n"]))
        print("  snap_slug rows per day"); [print("    %s %7d slugs in %d shows" % (r["d"], r["n"], r["s"])) for r in q(c, "SELECT day d, COUNT(*) n, COUNT(DISTINCT show_id) s FROM snap_slug GROUP BY d ORDER BY d DESC LIMIT 5")]
    else: print("no", led)
    print("\nSend this output back: the biggest line in each block is the answer.")

if __name__ == "__main__": main()
