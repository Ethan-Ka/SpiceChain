#!/usr/bin/env python3
"""Run SpiceChain straight from the repo, no install needed.

    python3 run.py                         interactive menu
    python3 run.py examples/board.yaml     interactive menu with a board
    python3 run.py run examples/board.yaml
    python3 run.py chain in.wav a.asc b.asc -o out.wav

On first run, if numpy/soundfile/pyyaml aren't importable, this creates a
.venv next to this file, installs requirements.txt into it, and re-runs itself
with that Python.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _deps_ok() -> bool:
    try:
        import numpy, soundfile, yaml  # noqa: F401
        return True
    except ImportError:
        return False


def main() -> int:
    if not _deps_ok():
        if Path(sys.prefix).resolve() == VENV.resolve():   # already inside .venv
            print("SpiceChain: dependencies still missing inside .venv", file=sys.stderr)
            return 1
        if not VENV_PY.exists():
            print("SpiceChain: first run, setting up .venv ...")
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
        subprocess.check_call([str(VENV_PY), "-m", "pip", "install", "-q",
                               "-r", str(ROOT / "requirements.txt")])
        return subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

    sys.path.insert(0, str(ROOT))
    from spicechain.cli import main as cli_main
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
