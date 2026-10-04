"""Install basicsr 1.4.2 (needed by gfpgan) with its setup.py fixed for Python 3.13+.

basicsr's setup.py reads its version with exec() + locals(), which stopped
working in Python 3.13, so `pip install basicsr` fails with KeyError
'__version__'. We fetch the official sdist from PyPI, patch that one function
and install it. Run with the venv's python; does nothing if already installed.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = "1.4.2"


def main() -> int:
    if importlib.util.find_spec("basicsr") is not None:
        return 0
    with urllib.request.urlopen(f"https://pypi.org/pypi/basicsr/{VERSION}/json", timeout=60) as r:
        url = next(u["url"] for u in json.load(r)["urls"] if u["packagetype"] == "sdist")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "basicsr.tar.gz"
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive) as t:
            t.extractall(tmp, filter="data")
        setup_py = Path(tmp) / f"basicsr-{VERSION}" / "setup.py"
        src = setup_py.read_text()
        src = src.replace("exec(compile(f.read(), version_file, 'exec'))",
                          "ns = {}; exec(compile(f.read(), version_file, 'exec'), ns)")
        src = src.replace("return locals()['__version__']", "return ns['__version__']")
        setup_py.write_text(src)
        return subprocess.call([sys.executable, "-m", "pip", "install", "-q", "--no-build-isolation",
                                str(setup_py.parent)])


if __name__ == "__main__":
    sys.exit(main())
