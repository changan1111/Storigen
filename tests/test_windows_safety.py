"""Windows-specific safety. These run on any machine by faking the Windows API; they do NOT replace a run on a real Windows PC (docs/WINDOWS_CHECKLIST.md)."""
import ctypes, io, os, pathlib, sys, types
import pytest
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / "autoid_lite")); sys.path.insert(0, str(root))
import watcher

class FakeKernel:
    def __init__(self, alive=True, access_denied=False): self.alive, self.denied, self.closed = alive, access_denied, 0
    def OpenProcess(self, access, inherit, pid): return 0 if (not self.alive or self.denied) else 1234
    def GetLastError(self): return 5 if self.denied else 87
    def GetExitCodeProcess(self, h, ref): ref._obj.value = 259 if self.alive else 0; return 1
    def CloseHandle(self, h): self.closed += 1

def fake_windows(monkeypatch, kernel):
    monkeypatch.setattr(os, "name", "nt"); monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=kernel), raising=False)
    def boom(*a, **k): raise AssertionError("os.kill must never be called on Windows: it would terminate the process")
    monkeypatch.setattr(watcher.os, "kill", boom)

def test_windows_pid_check_never_calls_os_kill(monkeypatch):
    k = FakeKernel(alive=True); fake_windows(monkeypatch, k)
    assert watcher.pid_alive(4321) is True and k.closed == 1

def test_windows_pid_check_reports_a_finished_or_missing_process(monkeypatch):
    fake_windows(monkeypatch, FakeKernel(alive=False)); assert watcher.pid_alive(4321) is False

def test_windows_pid_check_treats_access_denied_as_alive(monkeypatch):
    fake_windows(monkeypatch, FakeKernel(alive=True, access_denied=True)); assert watcher.pid_alive(4321) is True

def test_posix_pid_check_is_unchanged():
    assert watcher.pid_alive(os.getpid()) is True and watcher.pid_alive(2 ** 22 + 12345) is False

def test_blaze_poll_commands_do_not_crash_on_a_console_that_cannot_show_the_title(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bp_win", root / "tools" / "blaze_poll.py"); bp = importlib.util.module_from_spec(spec); spec.loader.exec_module(bp)
    raw = io.BytesIO(); console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict"); monkeypatch.setattr(sys, "stdout", console); monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    monkeypatch.setenv("BLAZE_SESSION_ID", "S"); monkeypatch.setenv("BLAZE_USERNAME", "u"); monkeypatch.setenv("BLAZE_LEDGER", str(tmp_path / "l.db")); monkeypatch.setenv("BLAZE_REPORT_DIR", str(tmp_path / "r"))
    monkeypatch.setattr(bp, "live_status", lambda c: "story: \u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0939\u093f\u0928\u094d\u0926\u0940")      # Telugu and Hindi
    assert bp.main(["live"]) == 0; console.flush(); assert "?" in raw.getvalue().decode("utf-8", "replace") or len(raw.getvalue()) > 0
