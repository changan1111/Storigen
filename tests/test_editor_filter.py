"""v10.9.5: the editor name. The video editors write their name in the slug's comment in Blaze ("VD VIGNESH", "VD VIGNESH_sekar_karthik"): it is stored per story and the dashboard can filter by it, and the top search finds it."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest, urllib.parse
Q = lambda **k: "?" + urllib.parse.urlencode(k)
from test_blaze_poll import bp, env, live_env, ready_clip, posts, clips, slug       # noqa: F401  (fixtures)
from test_story_scripts import rows, row, spy, sent
from test_ready_feed import story_set, media_found, feed, sql                              # noqa: F401
from test_server import sid                                                                # noqa: F401

def with_comment(sl, text): return dict(sl, comment=text)

def test_the_poller_stores_the_slug_comment_and_the_dashboard_filters_by_it(env):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [with_comment(slug(724921, "AUTO ID 05", 14), "VD VIGNESH"), with_comment(slug(724905, "AUTO ID 03", 13), "VD VIGNESH_sekar_karthik"), slug(724900, "AUTO ID 01", 12)]
    p.cycle(); a, b, c = row(s, 724921), row(s, 724905), row(s, 724900)
    assert a["editor"] == "VD VIGNESH" and b["editor"] == "VD VIGNESH_sekar_karthik" and c["editor"] is None
    d = s.call("GET", "/api/clips")[1]; assert [(e["name"], e["n"]) for e in d["editors"]] == [("VD VIGNESH", 1), ("VD VIGNESH_sekar_karthik", 1)]
    ids = lambda q: sorted(x["blaze_story_id"] for x in s.call("GET", "/api/clips" + q)[1]["clips"])
    assert ids(Q(editor="VD VIGNESH")) == ["724921"] and ids(Q(editor="vd vignesh")) == ["724921"]          # exact name, any letter case
    assert ids(Q(editor="VD VIGNESH,VD VIGNESH_sekar_karthik")) == ["724905", "724921"]                   # several ticked: any of them
    assert ids(Q(editor="nobody")) == [] and len(ids("")) == 3
    cnt = s.call("GET", "/api/clips" + Q(editor="VD VIGNESH", per_page=50))[1]; assert cnt["total"] == 1 and cnt["day_counts"]["all"] == 3 and sum(x["n"] for x in cnt["bulletins"]) == 1

def test_the_top_search_finds_an_editor_name(env):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [with_comment(slug(724921, "AUTO ID 05", 14), "VD VIGNESH"), with_comment(slug(724905, "AUTO ID 03", 13), "VD KARTHIK")]; p.cycle()
    ids = lambda q: sorted(x["blaze_story_id"] for x in s.call("GET", "/api/clips" + q)[1]["clips"])
    assert ids("?q=vignesh") == ["724921"] and ids("?q=karthik") == ["724905"] and ids("?q=VD") == ["724905", "724921"]
    assert ids(Q(q="vignesh", editor="VD KARTHIK")) == []                                                    # search and filter both apply

def test_a_changed_or_emptied_comment_follows_blaze_and_a_missing_field_never_wipes_it(env):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [with_comment(slug(724921, "AUTO ID 05", 14), "VD VIGNESH")]; p.cycle(); assert row(s, 724921)["editor"] == "VD VIGNESH"
    p.synced_at.clear(); f.slugs = [with_comment(slug(724921, "AUTO ID 05", 14), "VD VIGNESH_id name checking")]; p.cycle(); assert row(s, 724921)["editor"] == "VD VIGNESH_id name checking"   # the page shows the text as it is typed in Blaze
    p.synced_at.clear(); f.slugs = [slug(724921, "AUTO ID 05", 14)]; p.cycle(); assert row(s, 724921)["editor"] == "VD VIGNESH_id name checking"                                         # this Blaze list has no comment field: nothing is wiped
    p.synced_at.clear(); f.slugs = [with_comment(slug(724921, "AUTO ID 05", 14), "   ")]; p.cycle(); assert row(s, 724921)["editor"] is None                                                   # comment cleared in Blaze: cleared here

def test_the_service_call_takes_the_editor_and_the_feed_and_csv_carry_it(sid):
    import urllib.request
    story_set(sid, 2)
    sid.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "R1", "stories": [{"blaze_story_id": "700000", "slug": "S0", "editor": "VD VIGNESH"}, {"blaze_story_id": "700001", "slug": "S1", "editor": "x" * 300}]})
    n = {x["blaze_story_id"]: x for x in sid.call("GET", "/api/clips")[1]["clips"]}
    assert n["700000"]["editor"] == "VD VIGNESH" and len(n["700001"]["editor"]) == 120                    # junk is cut, not trusted
    for k in ("700000", "700001"): media_found(sid, n[k]["display_id"], "MOS-" + k, k + ".mxf")
    fd = sid.call("GET", "/api/feed" + Q(editor="VD VIGNESH"))[1]; assert [i["blaze_story_id"] for i in fd["items"]] == ["700000"] and fd["items"][0]["editor"] == "VD VIGNESH" and len(fd["editors"]) == 2
    assert [i["blaze_story_id"] for i in sid.call("GET", "/api/feed?q=vignesh")[1]["items"]] == ["700000"]
    get = lambda q: urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/api/clips.csv%s" % (sid.port, q), headers={"Cookie": sid.cookie}), timeout=10).read().decode("utf-8-sig")
    t = get(Q(editor="VD VIGNESH")); assert "700000" in t and "700001" not in t and t.splitlines()[0].endswith("Editor") and t.splitlines()[1].endswith("VD VIGNESH")
    assert sid.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "R1", "stories": [{"blaze_story_id": "700000", "slug": "S0"}, {"blaze_story_id": "700001", "slug": "S1"}]})[0] == 200      # an older poller (no editor): nothing is wiped
    assert next(i for i in sid.call("GET", "/api/clips")[1]["clips"] if i["blaze_story_id"] == "700000")["editor"] == "VD VIGNESH"

# ------------------------------------------------------------------ the real page against a real server, in a headless DOM
def test_the_editor_picker_and_the_top_search_in_a_headless_browser(tmp_path):
    import os, shutil, subprocess
    from test_server import Srv
    node = shutil.which("node"); root = pathlib.Path(__file__).resolve().parents[1]; js = root / "tools" / "dev" / "check_editor_filter.js"
    if not node: pytest.skip("node is not installed (developer check only)")
    env = dict(os.environ); env["NODE_PATH"] = os.pathsep.join(p for p in [str(root / "tools" / "dev" / "node_modules"), env.get("NODE_PATH", "")] if p)
    if subprocess.run([node, "-e", "require('jsdom')"], env=env, capture_output=True).returncode: pytest.skip("jsdom is not installed: cd tools/dev && npm install jsdom")
    s = Srv(tmp_path, "story_id"); assert s.login()[0] == 200
    st = [{"blaze_story_id": str(i), "slug": "S%d" % i, "slug_id": str(900 + i), "position": i, "story_title": t, "editor": e} for i, t, e in ((1, "story one", "VD VIGNESH"), (2, "story two", "VD VIGNESH"), (3, "story three", None), (4, "story four", "VD KARTHIK"))]
    assert s.svc("POST", "/svc/rundowns/sync", {"blaze_rundown_id": "10", "rundown_name": "Bulletin", "stories": st})[0] == 200
    r = subprocess.run([node, str(js), str(s.port), "admin@x.io", "adminpass1"], env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "ALL CHECKS PASSED" in r.stdout, r.stdout[-2500:] + r.stderr[-800:]


def test_feed_assigned_to_cell_shows_the_editor():
    """v10.9.5: the Ready feed's Assigned to cell carries the editor name (slug comment) under the assigned user."""
    from pathlib import Path
    page = (Path(__file__).resolve().parent.parent / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    assert 'td("mut",it.assigned_to||(it.editor?"":"-"))' in page and '"Editor: "+it.editor' in page


def test_feed_has_an_editor_picker():
    """v10.9.6: the Ready feed has its own All editors picker that sends `editor` to /api/feed."""
    from pathlib import Path
    page = (Path(__file__).resolve().parent.parent / "autoid_lite" / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="fedit"' in page and 'qs.set("editor",feed.fedit)' in page and 'userOpts($("#fedit"),feed.editors' in page
