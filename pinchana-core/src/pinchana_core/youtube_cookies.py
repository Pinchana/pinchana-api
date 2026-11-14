"""Operator cookie source shared by the YouTube video scrapers."""

import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path


logger = logging.getLogger(__name__)


def resolve_cookie_source() -> Path | None:
    cookie_file_env = os.getenv("YTDLP_COOKIE_FILE", "").strip()
    if cookie_file_env:
        path = Path(cookie_file_env)
        if path.is_file():
            return path
        logger.warning("Cookie file not found: %s", path)
        return None

    cookies_dir = Path(os.getenv("YTDLP_COOKIES_DIR", "/run/pinchana-cookies"))
    if not cookies_dir.exists() or not cookies_dir.is_dir():
        return None

    for name in ("youtube.com_cookies.txt", "cookies.txt"):
        candidate = cookies_dir / name
        if candidate.is_file():
            return candidate

    candidates = sorted(p for p in cookies_dir.glob("*.txt") if p.is_file())
    return candidates[0] if candidates else None


@contextmanager
def runtime_cookiefile():
    """Give each downloader a writable copy of the shared Netscape file."""
    source = resolve_cookie_source()
    if source is None:
        yield None
        return

    tmp_dir = Path(os.getenv("YTDLP_COOKIE_TMP_DIR", "/tmp"))
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ytcookies-", dir=tmp_dir) as folder:
        cookiefile = Path(folder) / "cookies.txt"
        shutil.copyfile(source, cookiefile)
        cookiefile.chmod(0o600)
        yield cookiefile
