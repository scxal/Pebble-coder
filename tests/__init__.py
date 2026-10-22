import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_HOME = Path(os.environ.get("PEBBLE_HOME") or tempfile.mkdtemp(prefix="pbl-test-"))
os.environ["PEBBLE_HOME"] = str(_HOME)

if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pbl_home

pbl_home.bootstrap()
