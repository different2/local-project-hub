"""Allow the packaged app to start with `python -m hub`.

Briefcase derives the app's entry point from the app name and runs it as a
module (`MainModule = hub` in the macOS bundle's Info.plist), so the package
must be executable. Without this the packaged app exits immediately with:

    No module named hub.__main__; 'hub' is a package and cannot be directly executed

`./run.sh` and `python3 main.py` both still work unchanged — this only adds
the packaged-app entry path.
"""

from __future__ import annotations

import sys
from pathlib import Path

# When run as `python -m hub` from inside the app bundle, the repo root is not
# on sys.path, so `import main` would fail. main.py lives beside this package.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import main  # noqa: E402  (path set up above)

if __name__ == "__main__":
    raise SystemExit(main.main())
