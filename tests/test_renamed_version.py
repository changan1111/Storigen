"""VERSION_SUFFIX=on: a story renamed in Blaze AFTER its clip was attached keeps the old clip name; a _V01 file under the NEW title is still taken (the plain new name is not)."""
import datetime as dt
from test_server import Srv

def test_v01_under_the_new_title_is_taken_but_the_plain_new_name_is_not(tmp_path, monkeypatch):
    monkeypatch.setenv("ID_FORMAT", "name"); monkeypatch.setenv("VERSION_SUFFIX", "on")
    s = Srv(tmp_path, "placeholder"); assert s.login()[0] == 200
    r = s.call("POST", "/api/manual", {"rundown": "14:00 Bulletin", "story": "Chandra Karthi"})[1]
    with s.app.db.tx() as cur:
        cur.x("UPDATE clip_ids SET state='ATTACHED' WHERE id=?", (r["id"],)); cur.x("UPDATE stories SET slug='Chandra Karthi Breath' WHERE id=?", (r["story_id"],))
    d = dt.date.today().strftime("%d%m%y")
    assert s.svc("GET", "/svc/match?name=%s_CHANDRA_KARTHI_BREATH" % d)[0] == 404
    c, b = s.svc("GET", "/svc/match?name=%s_CHANDRA_KARTHI_BREATH_V01" % d); assert c == 200 and b["name_id"].endswith("_BREATH_V01")
    assert s.svc("GET", "/svc/match?name=%s_CHANDRA_KARTHI_BREATH_V05" % d)[0] == 404, "only the next number is accepted"
    assert s.svc("GET", "/svc/match?name=%s_NOT_A_STORY_V01" % d)[0] == 404, "a typo is still refused"
