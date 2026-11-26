"""Plugin registry for runtime scraper discovery."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from .library import PlaylistResult, ScrapeError, ScrapeResult
from .models import ScrapeRequest, ScrapeResponse
from .storage import MediaStorage, cache_context

type Payload = ScrapeResponse | dict[str, Any]
type Operation = Callable[[ScrapeRequest], Awaitable[Payload]]


@dataclass
class ScraperPlugin:
    """Metadata, direct operations, and shared resources for a scraper."""

    name: str
    router: APIRouter
    route_patterns: list[str] = field(default_factory=list)
    scrape_fn: Operation | None = None
    health_fn: Callable[[], Awaitable[dict]] | None = None
    operations: dict[str, Operation] = field(default_factory=dict)
    get_storage: Callable[[], MediaStorage] | None = None
    open_resources: Callable[[], AbstractAsyncContextManager[None]] | None = None
    _runtime_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _runtime: AsyncExitStack | None = field(default=None, init=False, repr=False)
    _users: int = field(default=0, init=False, repr=False)

    def operation(self, name: str) -> Operation | None:
        return self.scrape_fn if name == "scrape" else self.operations.get(name)

    @asynccontextmanager
    async def lifespan(self, _app=None):
        """Share scraper resources across the app and active Python calls."""
        async with self._runtime_lock:
            if self._runtime is None:
                async with AsyncExitStack() as runtime:
                    if self.open_resources is not None:
                        await runtime.enter_async_context(self.open_resources())
                    if self.get_storage is not None:
                        runtime.push_async_callback(self.get_storage().close)
                    self._runtime = runtime.pop_all()
            self._users += 1
        try:
            yield
        finally:
            async with self._runtime_lock:
                self._users -= 1
                runtime = self._runtime
                if self._users == 0 and runtime is not None:
                    self._runtime = None
                    await runtime.aclose()

    async def _request(
        self, operation: str, url: str, cache_dir: str | Path | None,
    ) -> tuple[dict[str, Any], Path]:
        handler = self.operation(operation)
        if handler is None or self.get_storage is None:
            raise ScrapeError(400, f"{operation.capitalize()} is unavailable for {self.name}")

        directory = Path(cache_dir).expanduser().resolve() if cache_dir is not None else None
        with cache_context(directory=directory):
            try:
                request = ScrapeRequest(url=url)
            except ValidationError as exc:
                raise ScrapeError(400, "Expected a valid HTTP or HTTPS URL") from exc
            try:
                async with self.lifespan():
                    result = await handler(request)
                    cache_root = self.get_storage().base_path.resolve()
            except HTTPException as exc:
                raise ScrapeError(exc.status_code, exc.detail) from exc

        payload = result.model_dump() if isinstance(result, ScrapeResponse) else result
        return payload, cache_root

    async def _scrape_result(
        self, operation: str, url: str, cache_dir: str | Path | None,
    ) -> ScrapeResult:
        payload, cache_root = await self._request(operation, url, cache_dir)
        return ScrapeResult(**payload, cache_dir=cache_root)

    async def scrape(self, url: str, *, cache_dir: str | Path | None = None) -> ScrapeResult:
        """Scrape one URL and download its media into the local cache."""
        return await self._scrape_result("scrape", url, cache_dir)

    async def inspect(self, url: str, *, cache_dir: str | Path | None = None) -> ScrapeResult:
        """Read metadata for one URL without downloading its media."""
        return await self._scrape_result("inspect", url, cache_dir)

    async def scrape_playlist_item(
        self, url: str, *, cache_dir: str | Path | None = None,
    ) -> ScrapeResult:
        """Download one YouTube video using the playlist-item operation."""
        return await self._scrape_result("playlist-item", url, cache_dir)

    async def playlist(self, url: str) -> PlaylistResult:
        """Read a playlist or album's ordered track URLs."""
        payload, _ = await self._request("playlist", url, None)
        return PlaylistResult.model_validate(payload)


class PluginRegistry:
    """Central registry where scraper modules register themselves at import time."""

    def __init__(self):
        self._plugins: dict[str, ScraperPlugin] = {}

    def register(self, plugin: ScraperPlugin) -> None:
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> ScraperPlugin | None:
        return self._plugins.get(name)

    def items(self):
        return self._plugins.items()

    def match_url(self, url: str) -> ScraperPlugin | None:
        url_lower = url.lower()
        for plugin in self._plugins.values():
            for pattern in plugin.route_patterns:
                if pattern.lower() in url_lower:
                    return plugin
        return None


# Global singleton — imported by both server and scraper modules.
registry = PluginRegistry()
