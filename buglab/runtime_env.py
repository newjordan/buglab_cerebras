from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_TEMP_LOCK = threading.Lock()


@contextmanager
def temporary_process_tempdir(temp_dir: Path) -> Iterator[None]:
    """Point process temp vars at ``temp_dir`` and restore the previous values.

    Playwright reads ``TMP``/``TEMP``/``TMPDIR`` from the process environment.
    The lock keeps overlapping hunts from restoring each other's values.
    """

    temp_dir.mkdir(parents=True, exist_ok=True)
    keys = ("TMP", "TEMP", "TMPDIR")
    with _TEMP_LOCK:
        previous = {key: os.environ.get(key) for key in keys}
        try:
            for key in keys:
                os.environ[key] = str(temp_dir)
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
