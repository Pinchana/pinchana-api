"""Read video durations and visual dimensions from media files in the shared scraper cache."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image
from pinchana_core.video_metadata import probe_video

from .schemas import MediaDimensions

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MediaMetadata:
    dimensions: MediaDimensions | None = None
    duration: int | None = None


class MediaDimensionProbe:
    """Probe cached images and videos without fetching arbitrary URLs."""

    def __init__(self, base_path: str | Path, concurrency: int = 4):
        self.base_path = Path(base_path)
        self._limit = asyncio.Semaphore(max(1, concurrency))
        self._cache: OrderedDict[Path, tuple[tuple[int, int], MediaMetadata]] = OrderedDict()
        self._cache_lock = asyncio.Lock()

    def _resolve_media_path(self, url: str) -> Path | None:
        if not isinstance(url, str) or not url.startswith("/media/"):
            return None
        relative = url.split("?", 1)[0].removeprefix("/media/")
        parts = relative.split("/", 2)
        if len(parts) != 3 or not all(parts):
            return None
        _platform, post_id, filename = parts
        if ".." in filename or filename.startswith("/"):
            return None
        resolved = (self.base_path / post_id / filename).resolve()
        try:
            resolved.relative_to(self.base_path.resolve())
        except ValueError:
            return None
        return resolved

    async def metadata_for(self, url: str, media_type: str) -> MediaMetadata:
        if media_type not in {"image", "video"}:
            return MediaMetadata()
        path = self._resolve_media_path(url)
        if path is None:
            return MediaMetadata()
        try:
            stat = path.stat()
        except OSError:
            return MediaMetadata()
        if not path.is_file():
            return MediaMetadata()
        signature = (stat.st_mtime_ns, stat.st_size)
        async with self._cache_lock:
            cached = self._cache.get(path)
            if cached and cached[0] == signature:
                self._cache.move_to_end(path)
                return cached[1]

        async with self._limit:
            if media_type == "image":
                metadata = MediaMetadata(dimensions=self._probe_image(path))
            else:
                metadata = await asyncio.to_thread(self._probe_video, path)
                if metadata is None:
                    return MediaMetadata()

        # Telegram delivery scopes are disposable, and each URL is normally read once.
        if path.is_relative_to(self.base_path.resolve() / ".transient"):
            return metadata

        async with self._cache_lock:
            self._cache[path] = (signature, metadata)
            self._cache.move_to_end(path)
            if len(self._cache) > 4096:
                self._cache.popitem(last=False)
        return metadata

    @staticmethod
    def _probe_image(path: Path) -> MediaDimensions | None:
        try:
            with Image.open(path) as image:
                width, height = image.size
            return MediaDimensions(width=width, height=height)
        except (OSError, ValueError):
            logger.warning("media_dimension_probe_failed type=image path=%s", path)
            return None

    @staticmethod
    def _rotation(stream: dict[str, Any]) -> int:
        tags = stream.get("tags")
        if isinstance(tags, dict):
            try:
                return int(tags.get("rotate", 0))
            except (TypeError, ValueError):
                pass
        side_data = stream.get("side_data_list")
        if isinstance(side_data, list):
            for item in side_data:
                if not isinstance(item, dict) or "rotation" not in item:
                    continue
                try:
                    return int(item["rotation"])
                except (TypeError, ValueError):
                    continue
        return 0

    def _probe_video(self, path: Path) -> MediaMetadata | None:
        result = probe_video(path)
        if result is None:
            logger.warning("media_probe_failed type=video path=%s", path)
            return None
        stream, duration = result
        dimensions = None
        try:
            width = int(stream["width"])
            height = int(stream["height"])
            if abs(self._rotation(stream)) % 180 == 90:
                width, height = height, width
            dimensions = MediaDimensions(width=width, height=height)
        except (KeyError, TypeError, ValueError):
            logger.warning("media_dimension_probe_invalid type=video path=%s", path)
        return MediaMetadata(dimensions=dimensions, duration=duration)
