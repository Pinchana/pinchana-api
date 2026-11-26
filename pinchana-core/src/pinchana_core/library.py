"""Result and error types for callers using the scrapers directly."""

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict

from .models import ScrapeResponse


class ScrapeError(Exception):
    """A scraper failure with the same status and detail as the API."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        message = detail.get("message", detail) if isinstance(detail, dict) else detail
        super().__init__(str(message))


class ScrapeResult(ScrapeResponse):
    """Scraped metadata, platform-specific fields, and the local cache directory."""

    model_config = ConfigDict(extra="allow")
    cache_dir: Path

    def media_path(self, url: str | None) -> Path | None:
        """Resolve a returned media URL to an existing file inside the cache."""
        if not url:
            return None
        try:
            parsed = urlsplit(url)
        except ValueError:
            return None
        parts = unquote(parsed.path).split("/")
        if parsed.scheme or parsed.netloc or parts[:2] != ["", "media"] or len(parts) < 5:
            return None
        if any(part in {"", ".", ".."} or "\\" in part or "\0" in part for part in parts[2:]):
            return None
        root = self.cache_dir.resolve()
        path = root.joinpath(*parts[3:]).resolve()
        return path if path.is_relative_to(root) and path.is_file() else None


class PlaylistResult(BaseModel):
    """A playlist or album title and its ordered track URLs."""

    title: str
    urls: list[str]
