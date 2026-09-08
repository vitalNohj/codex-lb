from __future__ import annotations

import asyncio
import fcntl
from contextlib import asynccontextmanager

from app.core.config.settings import get_settings


@asynccontextmanager
async def exclusion_write_lock():
    directory = get_settings().data_dir
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "claude-exclusions.lock").open("a") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
