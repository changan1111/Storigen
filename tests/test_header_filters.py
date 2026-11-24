"""v10.20.0: the Editor and Created-by header drop-downs (several names, 'unassigned'), and sorting by the number of clips."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import urllib.parse
Q = lambda **k: "?" + urllib.parse.urlencode(k)
from test_blaze_poll import bp, env, live_env, ready_clip, posts, clips, slug       # noqa: F401  (fixtures)
from test_story_scripts import rows, row, spy, sent
from test_ready_feed import story_set, media_found, feed, sql                              # noqa: F401
from test_server import sid                                                                # noqa: F401

def with_comment(sl, text): return dict(sl, comment=text)

def test_unassigned_and_named_editors_can_be_ticked_together(env):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [with_comment(slug(724921, "AUTO ID 05", 14), "VD VIGNESH"), with_comment(slug(724905, "AUTO ID 03", 13), "VD KARTHIK"), slug(724900, "AUTO ID 01", 12)]; p.cycle()
    ids = lambda q: sorted(x["blaze_story_id"] for x in s.call("GET", "/api/clips" + q)[1]["clips"])
    assert ids(Q(editor="__none__")) == ["724900"]                                  # only the story with no editor name
    assert ids(Q(editor="__none__,VD VIGNESH")) == ["724900", "724921"]            # unassigned plus a named editor
    assert ids(Q(editor="VD VIGNESH")) == ["724921"]                                # the old behaviour is unchanged

def test_created_by_takes_several_names_and_ignores_assigned_to(env):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [slug(724921, "AUTO ID 05", 14), slug(724905, "AUTO ID 03", 13), slug(724900, "AUTO ID 01", 12)]
    f.story_extra["724921"] = {"createdBy": 363, "assignedTo": 358}; f.story_extra["724905"] = {"createdBy": 358, "assignedTo": 333}; p.cycle()
    ids = lambda q: sorted(x["blaze_story_id"] for x in s.call("GET", "/api/clips" + q)[1]["clips"])
    assert ids(Q(created="venkat")) == ["724921"] and ids(Q(created="VENKAT")) == ["724921"]
    assert ids(Q(created="venkat,ramachandran")) == ["724905", "724921"]
    assert ids(Q(created="abarna")) == []                                           # abarna is only assigned a story, never the creator
    assert ids(Q(user="abarna")) == ["724905"]                                      # the older user filter (created OR assigned) still works

def test_the_clips_sort_is_accepted(env):
    s, f, p = env; assert s.login()[0] == 200
    f.slugs = [slug(724921, "AUTO ID 05", 14), slug(724905, "AUTO ID 03", 13)]; p.cycle()
    for d in ("asc", "desc"):
        r = s.call("GET", "/api/clips" + Q(sort="clips", dir=d, per_page=50)); assert r[0] == 200 and len(r[1]["clips"]) == 2
    assert s.call("GET", "/api/clips" + Q(sort="bogus", per_page=50))[0] == 400
