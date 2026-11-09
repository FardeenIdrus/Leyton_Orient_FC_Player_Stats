"""The static files' version (TASKS 2.36 S-B): a hash of every file's content under
`web/static/`, used as a path segment (`/static/v/<version>/js/card.js`). Because the version is
a path segment, a module's relative imports (`./common.js`) resolve inside the same version, so
a page can never pair one release's module with another's. Versioned files are served
`immutable` for a year; only the current version is served at all.

The hash is recomputed only when a file's (name, size, mtime) changes -- checked at most once a
second -- so editing a JS or CSS file in development gives a new version without a restart."""
from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
_lock = threading.Lock()
_memo: dict = {"checked": 0.0, "sig": None, "ver": None}


def _files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.startswith("."):
                yield Path(dirpath) / name


def _signature(root: Path) -> tuple:
    out = []
    for p in _files(root):
        st = p.stat()
        out.append((str(p.relative_to(root)), st.st_size, st.st_mtime_ns))
    return tuple(out)


def compute(root: Path) -> str:
    """Hash of every file's path and content under `root` (12 hex characters)."""
    h = hashlib.sha1()
    for p in _files(Path(root)):
        h.update(str(p.relative_to(root)).encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:12]


def current(root: Path = STATIC_DIR) -> str:
    now = time.monotonic()
    with _lock:
        if _memo["ver"] is not None and now - _memo["checked"] < 1.0:
            return _memo["ver"]
        sig = _signature(root)
        if sig != _memo["sig"]:
            _memo.update(sig=sig, ver=compute(root))
        _memo["checked"] = now
        return _memo["ver"]


def url(path: str) -> str:
    """`/static/v/<version>/<path>` for a path under web/static (e.g. "js/card.js")."""
    return f"/static/v/{current()}/{path.lstrip('/')}"
