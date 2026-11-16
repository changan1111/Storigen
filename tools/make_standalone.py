#!/usr/bin/env python3
"""Build a standalone sample dashboard: ONE html file that opens by double-click, with made-up stories and no server.

It is the real autoid_lite/web/index.html with tools/standalone_shim.js placed in front of the page script, so what you see
is the real page code. Run it again after any change to index.html:

    python3 tools/make_standalone.py                      # -> storigen_standalone.html in the current folder
    python3 tools/make_standalone.py --out demo.html
    python3 tools/make_standalone.py --src old_index.html --out demo_old.html
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MARK = "</style></head><body>"


def build(src: pathlib.Path, out: pathlib.Path, shim: pathlib.Path) -> int:
    html, js = src.read_text(encoding="utf-8"), shim.read_text(encoding="utf-8")
    if html.count(MARK) != 1:
        sys.exit("make_standalone: %s does not have the expected '%s' line exactly once" % (src, MARK))
    html = html.replace(MARK, MARK + "\n<script>\n" + js + "\n</script>", 1).replace("<title>Storigen</title>", "<title>Storigen (sample data)</title>", 1)
    out.write_text(html, encoding="utf-8")
    return len(html.encode("utf-8"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=pathlib.Path, default=ROOT / "autoid_lite" / "web" / "index.html")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("storigen_standalone.html"))
    ap.add_argument("--shim", type=pathlib.Path, default=ROOT / "tools" / "standalone_shim.js")
    a = ap.parse_args()
    print("wrote %s (%d KB)" % (a.out, build(a.src, a.out, a.shim) // 1024))
