"""Compatibility alias: the code now lives in autoid_lite/blaze/ledger.py. `import blaze_ledger` still gives that very module (same object), so nothing that used it changes."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from autoid_lite.blaze import ledger as _real
sys.modules[__name__] = _real
