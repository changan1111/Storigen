"""ONLY_RUNDOWNS: IDs only for chosen rundowns; others are still acknowledged and nothing is recorded."""
import pathlib, sys
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / "autoid_lite"))
import gateway

HDR = "<mosID>M</mosID><ncsID>N</ncsID><messageID>7</messageID>"
SENT = []
def run(xml):
    """What handle() would send to the registry, and its reply."""
    SENT.clear(); reply = gateway.handle("<mos>%s%s</mos>" % (HDR, xml))
    return list(SENT), reply

@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "DATA", str(tmp_path)); monkeypatch.setattr(gateway, "NAMES_FILE", str(tmp_path / "names.json"))
    monkeypatch.setattr(gateway, "deliver", lambda p, d: SENT.append((p, d))); gateway._NAMES.clear(); gateway._IGNORED.clear()
    return monkeypatch

def full(ro, name): return "<roCreate><roID>%s</roID><roSlug>%s</roSlug><story><storyID>S1</storyID><storySlug>a</storySlug></story></roCreate>" % (ro, name)
def ins(ro): return "<roStoryInsert><roID>%s</roID><story><storyID>S2</storyID><storySlug>b</storySlug></story></roStoryInsert>" % ro

def test_no_filter_means_every_rundown(cfg):
    cfg.setattr(gateway, "ONLY", [])
    assert len(run(full("R1", "ANY"))[0]) == 1 and len(run(ins("R9"))[0]) == 1

def test_match_by_name_and_per_story_messages_use_the_learned_name(cfg):
    cfg.setattr(gateway, "ONLY", ["9 pm bulletin"])
    assert len(run(full("R1", "03.11 9 PM Bulletin"))[0]) == 1          # name matches, any letter case
    assert len(run(ins("R1"))[0]) == 1                                  # roStoryInsert has only roID: the name learned above is used
    assert run(full("R2", "Morning Show"))[0] == [] and run(ins("R2"))[0] == []

def test_match_by_exact_roid_even_before_the_name_is_known(cfg):
    cfg.setattr(gateway, "ONLY", ["R77"])
    assert len(run(ins("R77"))[0]) == 1 and run(ins("R78"))[0] == []

def test_ignored_rundown_is_still_acknowledged_and_nothing_is_recorded(cfg):
    cfg.setattr(gateway, "ONLY", ["R77"]); sent, reply = run(full("R1", "Other"))
    assert sent == [] and "<roStatus>OK</roStatus>" in reply

def test_unknown_name_is_not_guessed(cfg):
    cfg.setattr(gateway, "ONLY", ["Bulletin"]); assert run(ins("R5"))[0] == []      # name never seen: ignored until a full rundown arrives
    assert len(run(full("R5", "Bulletin 2"))[0]) == 1 and len(run(ins("R5"))[0]) == 1

def test_names_survive_a_restart(cfg):
    cfg.setattr(gateway, "ONLY", ["Bulletin"]); run(full("R1", "Bulletin"))
    gateway._NAMES.clear(); gateway.load_names(); assert len(run(ins("R1"))[0]) == 1

def test_deletes_are_filtered_too(cfg):
    cfg.setattr(gateway, "ONLY", ["R1"])
    assert run("<roDelete><roID>R2</roID></roDelete>")[0] == [] and len(run("<roDelete><roID>R1</roID></roDelete>")[0]) == 1
