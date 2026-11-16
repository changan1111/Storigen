"""MOS gateway: full-rundown messages become ONE registry call, and registry calls are delivered strictly in order. No database needed."""
import json, pathlib, sys, urllib.error
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / "autoid_lite"))
import gateway

HDR = "<mosID>M</mosID><ncsID>N</ncsID><messageID>7</messageID>"
def body(xml): return gateway.parse_mos("<mos>%s%s</mos>" % (HDR, xml))[1]

def test_replace_is_one_snapshot_call_with_every_story():
    acts = gateway.actions_for(body("<roReplace><roID>R1</roID><roSlug>Eve</roSlug><story><storyID>A</storyID><storySlug>a</storySlug></story><story><storyID>B</storyID></story></roReplace>"))
    assert acts == [("/svc/rundowns/sync", {"blaze_rundown_id": "R1", "rundown_name": "Eve", "stories": [{"blaze_story_id": "A", "slug": "a"}, {"blaze_story_id": "B", "slug": ""}]})]

def test_empty_replace_is_still_a_snapshot_but_without_roid_it_is_ignored():
    assert gateway.actions_for(body("<roReplace><roID>R1</roID></roReplace>"))[0][1]["stories"] == []
    assert gateway.actions_for(body("<roReplace><story><storyID>A</storyID></story></roReplace>")) == []     # malformed: must never become a destructive call

def test_story_move_changes_no_association_and_is_acked():
    xml = "<mos>%s<roStoryMove><roID>R1</roID><storyID>A</storyID><storyID>B</storyID></roStoryMove></mos>" % HDR
    assert gateway.actions_for(gateway.parse_mos(xml)[1]) == []
    assert "<roStatus>OK</roStatus>" in gateway.handle.__globals__["reply"](gateway.parse_mos(xml)[0], gateway.ro_ack("R1"))

@pytest.fixture
def q(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "SPOOL", str(tmp_path / "spool.jsonl")); monkeypatch.setattr(gateway, "DEAD", str(tmp_path / "dead.jsonl"))
    sent, state = [], {"up": False, "code": None}
    def fake_call(path, payload=None, method="POST"):
        if state["code"]: raise urllib.error.HTTPError("u", state["code"], "x", {}, None)
        if not state["up"]: raise ConnectionError("registry down")
        sent.append((path, payload))
    monkeypatch.setattr(gateway, "call", fake_call); return sent, state

def test_calls_queue_behind_older_ones_so_a_stale_snapshot_cannot_overtake(q):
    sent, st = q
    gateway.deliver("/svc/rundowns/sync", {"n": 1})        # registry down: snapshot is spooled
    st["up"] = True
    gateway.deliver("/svc/stories", {"n": 2})              # registry is back, but this must NOT jump ahead of the snapshot
    assert sent == []
    gateway.replay_spool()
    assert [p for p, _ in sent] == ["/svc/rundowns/sync", "/svc/stories"]
    gateway.deliver("/svc/stories", {"n": 3}); assert sent[-1][1] == {"n": 3}      # queue empty again: direct delivery
    assert not pathlib.Path(gateway.SPOOL).exists()

def test_replay_stops_at_the_first_failure_and_keeps_order(q):
    sent, st = q
    gateway.deliver("/a", {}); gateway.deliver("/b", {}); gateway.replay_spool()   # still down
    assert sent == [] and [json.loads(l)[0] for l in open(gateway.SPOOL)] == ["/a", "/b"]
    st["up"] = True; gateway.replay_spool(); assert [p for p, _ in sent] == ["/a", "/b"]

def test_registry_refusal_is_dead_lettered_immediately(q):
    sent, st = q; st["code"] = 422
    gateway.deliver("/svc/attach/confirm", {"display_id": "x"})
    assert not pathlib.Path(gateway.SPOOL).exists() and json.loads(open(gateway.DEAD).read())["why"] == "HTTP 422"

def test_a_call_the_registry_keeps_failing_cannot_block_the_queue_forever(q, monkeypatch):
    sent, st = q; monkeypatch.setattr(gateway, "MAX_REPLAY_TRIES", 3)
    st["code"] = 500; gateway.deliver("/poison", {}); st["code"] = None; st["up"] = True; gateway.deliver("/after", {})
    st["code"] = 500; st["up"] = False
    for _ in range(3): gateway.replay_spool()
    assert "/poison" in open(gateway.DEAD).read()
    st["code"] = None; st["up"] = True; gateway.replay_spool()
    assert [p for p, _ in sent] == ["/after"]

def test_old_two_field_spool_lines_still_replay(q):
    sent, st = q; st["up"] = True
    open(gateway.SPOOL, "w").write(json.dumps(["/svc/stories", {"a": 1}]) + "\n")
    gateway.replay_spool(); assert sent == [("/svc/stories", {"a": 1})]
