"""v10.1.1: the dashboard's 5 s refresh must not throw the page away (it made inspecting an element, selecting text or holding a drop-down open impossible).
The page code is checked as text here (there is no browser in the tests). tools/dev/check_refresh_dom.js runs the real page in a headless DOM: the last test runs it when node and jsdom are installed."""
import os, pathlib, re, shutil, subprocess, sys
import pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
H = (ROOT / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
def fn(name, nxt):
    a = H.index("function %s(" % name); return H[a:H.index(nxt, a)]

def test_parts_of_the_page_are_rebuilt_only_when_their_data_changed():
    load = fn("load", "$(\"#go\").onclick")
    for k in ("warn", "rdl", "ev", "us"): assert 'changed("%s"' % k in load, k
    assert 'changed("stats"' in fn("renderStats", "function renderChips")
    assert "setHref($(\"#rep\")" in load and "setText($(\"#sub\")" in load and "setText($(\"#sys\")" in load and ".classList.remove(\"hide\")" not in load

def test_story_list_reuses_rows_and_does_not_empty_itself():
    r = fn("renderList", "function emptyDetail"); assert "rowNodes" in r and "insertBefore" in r and "replaceChildren" not in r

def test_detail_panes_are_skipped_when_nothing_in_them_changed():
    d = fn("showDetail", "$(\"#fsel\").onchange"); assert "sigDetail" in d and d.index("sigDetail") < d.index("renderMid(c,same)")

def test_a_ticking_warning_is_updated_in_place():
    load = fn("load", "$(\"#go\").onclick"); assert "if(!wch)st.problems.forEach" in load and 'replace(/\\d+/g,"#")' in load

def test_pause_refresh_button_and_p_key():
    assert 'id="pause"' in H and "Pause refresh" in H and "Resume refresh" in H and "setInterval(()=>{if(me&&!paused)load()},5000)" in H
    assert 'e.key==="p"' in H and "setPaused(!paused)" in H

def test_refresh_in_a_headless_browser():
    node = shutil.which("node"); js = ROOT / "tools" / "dev" / "check_refresh_dom.js"
    if not node: pytest.skip("node is not installed (developer check only)")
    env = dict(os.environ); env["NODE_PATH"] = os.pathsep.join(p for p in [str(ROOT / "tools" / "dev" / "node_modules"), env.get("NODE_PATH", "")] if p)
    if subprocess.run([node, "-e", "require('jsdom')"], env=env, capture_output=True).returncode: pytest.skip("jsdom is not installed: cd tools/dev && npm install jsdom")
    out = ROOT / "tools" / "_refresh_check.html"
    try:
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_standalone.py"), "--out", str(out)], check=True, capture_output=True)
        r = subprocess.run([node, str(js), str(out)], env=env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0 and "ALL CHECKS PASSED" in r.stdout, r.stdout[-1500:] + r.stderr[-500:]
    finally:
        if out.exists(): out.unlink()
