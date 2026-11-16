"""The watcher must refuse to work when a NAS/Nitro folder is really a plain local folder (unmounted share)."""
import pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / "autoid_lite"))
import watcher

MI = """22 1 8:1 / / rw - ext4 /dev/sda1 rw
40 22 0:40 / /mnt/nas rw - cifs //nas/share rw
41 40 0:41 / /mnt/nas/Exports/local rw - ext4 /dev/sdb1 rw
42 22 0:42 / /mnt/with\\040space rw - nfs4 srv:/x rw
"""

def test_fs_type_uses_longest_matching_mount(tmp_path):
    f = tmp_path / "mountinfo"; f.write_text(MI)
    assert watcher.fs_type("/mnt/nas/Archive", str(f)) == "cifs"
    assert watcher.fs_type("/mnt/nas", str(f)) == "cifs"
    assert watcher.fs_type("/mnt/nas/Exports/local/x", str(f)) == "ext4"      # nested local mount wins
    assert watcher.fs_type("/mnt/with space/a", str(f)) == "nfs4"
    assert watcher.fs_type("/srv/other", str(f)) == "ext4"

def test_fs_type_unknown_when_mountinfo_unreadable(tmp_path):
    assert watcher.fs_type("/x", str(tmp_path / "missing")) is None

def _dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(watcher, "WATCH_MODE", "move")
    for k, n in (("EXPORTS", "e"), ("NITRO", "n"), ("QUAR", "q"), ("ARCH", "a")):
        (tmp_path / n).mkdir(); monkeypatch.setattr(watcher, k, str(tmp_path / n))

def test_local_folders_pause_the_watcher_when_required(tmp_path, monkeypatch):
    _dirs(tmp_path, monkeypatch); monkeypatch.setattr(watcher, "REQUIRE_NET_FS", True); monkeypatch.setattr(watcher, "fs_type", lambda p, *a: "ext4")
    assert "not a network share" in watcher.storage_problem()

def test_network_folders_are_accepted(tmp_path, monkeypatch):
    _dirs(tmp_path, monkeypatch); monkeypatch.setattr(watcher, "REQUIRE_NET_FS", True); monkeypatch.setattr(watcher, "fs_type", lambda p, *a: "cifs")
    assert watcher.storage_problem() is None

def test_demo_mode_allows_local_folders(tmp_path, monkeypatch):
    _dirs(tmp_path, monkeypatch); monkeypatch.setattr(watcher, "REQUIRE_NET_FS", False)
    assert watcher.storage_problem() is None

def test_missing_folder_is_reported(tmp_path, monkeypatch):
    _dirs(tmp_path, monkeypatch); monkeypatch.setattr(watcher, "ARCH", str(tmp_path / "gone"))
    assert "Archive folder" in watcher.storage_problem()
