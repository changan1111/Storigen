"""v10.1.0 three panes: stories | script (online / anchor) | media and IDs, with the date and the bulletin in the top bar.
A browser is not available in the tests, so this guards what can break silently: where each pane sits, the column ratio, the tabs,
the version, and that the sample builder still works."""
import pathlib, re, shutil, subprocess, sys, pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "autoid_lite" / "web" / "index.html"
SHIM = ROOT / "tools" / "standalone_shim.js"
MAKE = ROOT / "tools" / "make_standalone.py"

def text(): return PAGE.read_text(encoding="utf-8")

def test_the_version_is_10_3_0_everywhere_it_is_shown():
    s = text(); assert 'var APP_VER="11.0.0"' in s and '<span class="vb">v11.0.0</span>' in s
    assert 'APP_VERSION = "11.0.0"' in (ROOT / "autoid_lite" / "common.py").read_text(encoding="utf-8")

def test_date_and_bulletin_are_in_the_top_bar_outside_the_panes():
    s = text(); top, panes = s[s.index('class="tb"'):s.index('id="split"')], s[s.index('id="split"'):s.index('id="deskbox"')]
    assert 'id="day"' in top and 'id="showf"' in top and 'id="stats"' in top and 'id="q"' in top
    assert 'id="day"' not in panes and 'id="showf"' not in panes

def test_the_three_panes_are_stories_then_script_then_media_and_ids():
    s = text(); box = s[s.index('id="split"'):s.index('id="deskbox"')]
    assert box.index('id="lpane"') < box.index('id="list"') < box.index('id="mid"') < box.index('id="detail"')
    assert s.count('id="mid"') == 1 and s.count('id="detail"') == 1

def test_the_columns_are_30_38_32_and_stack_under_1000px():
    s = text(); assert ".panes{display:grid;grid-template-columns:minmax(0,30fr) minmax(0,38fr) minmax(0,32fr)" in s
    assert "@media(max-width:999px){.panes{display:block" in s

def test_the_script_pane_has_both_tabs_counts_and_font_buttons():
    s = text(); mid = s[s.index("function renderMid("):s.index("function kvr(")]
    for t in ("scriptParts(c,tab)", "cfg.script_labels", '"Words: "', '"A-"', '"A+"', "Next needing action"): assert t in mid, t

def test_the_media_pane_shows_every_id_the_poller_stores():
    s = text(); r = s[s.index("function renderRight("):s.index("async function showDetail(")]
    for t in ("Media ID (Clip ID)", "Blaze Story ID", '"Slug ID"', '"Show ID"', "MOS object ID", '"Item ID"', "Blaze clip ID", "Internal ID", "Workflow", "acts(c,true)"): assert t in r, t

def test_a_story_is_always_selected_so_the_panes_are_never_empty_when_there_are_stories():
    s = text(); d = s[s.index("async function showDetail("):s.index("$(\"#fsel\").onchange")]
    assert "sel=clips.length?clips[0].id:null" in d

def test_the_sample_shim_answers_every_call_the_page_makes_on_load():
    js = SHIM.read_text(encoding="utf-8")
    for p in ("/api/me", "/api/config", "/api/status", "/api/rundowns", "/api/clips", "/api/events"): assert '"%s"' % p in js, p
    assert "history$" in js and "attached|quickattach" in js and "11.0.0 sample" in js

@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_the_shim_is_valid_javascript():
    r = subprocess.run(["node", "--check", str(SHIM)], capture_output=True, text=True); assert r.returncode == 0, r.stderr

def test_the_standalone_builder_makes_one_self_contained_file(tmp_path):
    out = tmp_path / "demo.html"
    r = subprocess.run([sys.executable, str(MAKE), "--out", str(out)], capture_output=True, text=True); assert r.returncode == 0, r.stderr
    h = out.read_text(encoding="utf-8"); assert h.count("window.fetch = async function") == 1 and "<title>Storigen (sample data)</title>" in h
    assert h.index("window.fetch = async function") < h.index("async function api(")      # the shim must be in place before the page script runs
    assert not re.search(r'(?:src|href)=\"https?://', h), "a standalone page must not load anything from the internet"
