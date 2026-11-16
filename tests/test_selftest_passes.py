"""`python3 autoid.py selftest` is what the install guide tells every operator to run: it must pass on the shipped code."""
import pathlib, subprocess, sys
root = pathlib.Path(__file__).resolve().parents[1]

def test_selftest_ends_without_errors():
    r = subprocess.run([sys.executable, str(root / "autoid.py"), "selftest"], capture_output=True, text=True, timeout=120, cwd=str(root))
    assert r.returncode == 0 and "SELF-TEST FAILED" not in r.stdout + r.stderr, r.stdout[-1500:] + r.stderr[-500:]
