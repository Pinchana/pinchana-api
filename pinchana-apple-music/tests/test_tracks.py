import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from pinchana_core.models import ScrapeRequest
from pinchana_core.storage import MediaStorage
from pinchana_apple_music import main
from pinchana_apple_music.socialcrawl import SocialCrawlResolver, track_id

SONG = "https://music.apple.com/us/song/example/123"
SELECTED = "https://music.apple.com/us/album/example/456?i=123&l=en"
PAYLOAD = {"success": True, "data": {"post": {
    "id": "123", "content": {"text": "Example", "duration_seconds": 180,
                             "media_urls": "https://example.com/preview.m4a"},
    "author": {"display_name": "Artist"},
}}}


class TrackTests(unittest.TestCase):
    def test_track_selection(self):
        for url in (SONG, SELECTED, "https://music.apple.com/song/123"):
            self.assertEqual(track_id(url), "123")

    def test_reject_collections_and_unsafe_urls(self):
        for url in ("https://music.apple.com/us/album/example/456",
                    SELECTED + "&i=789", "https://music.apple.com/us/album/example/456?i=",
                    "https://music.apple.com/us/playlist/example/123",
                    "https://music.apple.com.evil/us/song/example/123",
                    "https://evil.com/?url=" + SONG):
            with self.subTest(url=url), self.assertRaises(HTTPException):
                track_id(url)


class ResolverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.key_patch = patch.dict("os.environ", {"SOCIALCRAWL_API_KEY": "test-only-key"})
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)

    async def test_retry_preserves_uuid_and_header_only_key(self):
        requests = []
        def transport(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(429, headers={"Retry-After": "2"}, json={
                    "success": False, "error": {"type": "RATE_LIMITED", "retryable": True}})
            return httpx.Response(200, json=PAYLOAD)
        resolver = SocialCrawlResolver(httpx.MockTransport(transport))
        with patch("pinchana_apple_music.socialcrawl.asyncio.sleep", new_callable=AsyncMock) as sleep:
            meta = await resolver.resolve(SELECTED)
        self.assertEqual(meta["id"], "am-123")
        self.assertNotIn("preview", str(meta))
        sleep.assert_awaited_once_with(2)
        self.assertEqual(requests[0].headers["Idempotency-Key"], requests[1].headers["Idempotency-Key"])
        import uuid
        uuid.UUID(requests[0].headers["Idempotency-Key"])
        self.assertEqual(requests[0].headers["x-api-key"], "test-only-key")
        self.assertNotIn("test-only-key", str(requests[0].url))
        self.assertEqual(dict(requests[0].url.params), {"id": "123"})
        self.assertEqual(requests[0].extensions["timeout"]["read"], 60)
        await resolver.resolve(SONG)
        self.assertNotEqual(requests[1].headers["Idempotency-Key"], requests[2].headers["Idempotency-Key"])

    async def test_error_types_and_retry_limit(self):
        cases = [("RESOURCE_NOT_FOUND", True, None, 1),
                 ("SERVICE_UNAVAILABLE", True, None, 1),
                 ("SERVICE_UNAVAILABLE", True, "0", 4),
                 ("INSUFFICIENT_CREDITS", False, None, 1),
                 ("UPSTREAM_ERROR", True, None, 4)]
        for kind, retryable, retry_after, count in cases:
            requests = []
            def transport(request):
                requests.append(request)
                return httpx.Response(503, headers={"Retry-After": retry_after} if retry_after else {},
                                      json={"success": False, "error": {
                                          "type": kind, "message": "same message", "retryable": retryable}})
            resolver = SocialCrawlResolver(httpx.MockTransport(transport))
            with self.subTest(kind=kind), patch("pinchana_apple_music.socialcrawl.asyncio.sleep", new_callable=AsyncMock):
                if kind == "RESOURCE_NOT_FOUND":
                    self.assertIsNone(await resolver.resolve(SONG))
                else:
                    with self.assertRaises(HTTPException):
                        await resolver.resolve(SONG)
                self.assertEqual(len(requests), count)
                self.assertEqual(len({r.headers["Idempotency-Key"] for r in requests}), 1)

    async def test_timeout_reuses_key(self):
        requests = []
        def transport(request):
            requests.append(request)
            if len(requests) == 1:
                raise httpx.ReadTimeout("timeout", request=request)
            return httpx.Response(200, json=PAYLOAD)
        with patch("pinchana_apple_music.socialcrawl.asyncio.sleep", new_callable=AsyncMock):
            await SocialCrawlResolver(httpx.MockTransport(transport)).resolve(SONG)
        self.assertEqual(requests[0].headers["Idempotency-Key"], requests[1].headers["Idempotency-Key"])

    async def test_album_rejected_without_network(self):
        handler = AsyncMock()
        with self.assertRaises(HTTPException):
            await SocialCrawlResolver(httpx.MockTransport(handler)).resolve("https://music.apple.com/us/album/example/456")
        handler.assert_not_called()


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_youtube_match_ignores_preview_and_preserves_apple_metadata(self):
        meta = SocialCrawlResolver._metadata(PAYLOAD, "123")
        with tempfile.TemporaryDirectory() as folder, patch.object(main, "storage", MediaStorage(folder)), \
                patch.object(main, "search_ytmusic", return_value="youtube-id") as search:
            target, actual = await main.AppleMusicDownloader(meta).resolve(SONG)
        search.assert_called_once_with("Artist Example official audio")
        self.assertEqual(target, "https://www.youtube.com/watch?v=youtube-id")
        self.assertEqual(actual, meta)

    async def test_cache_and_concurrent_requests_resolve_and_download_once(self):
        with tempfile.TemporaryDirectory() as folder:
            storage = MediaStorage(folder)
            meta = SocialCrawlResolver._metadata(PAYLOAD, "123")
            async def download(_url):
                path = Path(folder) / "am-123" / "am-123.mp3"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"audio")
                await asyncio.sleep(0)
                return path, meta
            with patch.object(main, "storage", storage), \
                    patch.object(main.resolver, "resolve", new_callable=AsyncMock, return_value=meta) as lookup, \
                    patch.object(main.AppleMusicDownloader, "download", new_callable=AsyncMock, side_effect=download) as audio:
                result, other = await asyncio.gather(
                    main.process_scrape_request(ScrapeRequest(url=SONG)),
                    main.process_scrape_request(ScrapeRequest(url=SELECTED)))
                cached = await main.process_scrape_request(ScrapeRequest(url=SONG))
                lookup.assert_awaited_once()
                audio.assert_awaited_once()
                self.assertEqual(result, other)
                self.assertEqual(cached, result)
                self.assertEqual(result.audio_url, "/media/apple_music/am-123/audio.mp3")
            await storage.close()

    async def test_vpn_download_retries_do_not_repeat_socialcrawl(self):
        from pinchana_core.music import RateLimitError
        with tempfile.TemporaryDirectory() as folder:
            storage = MediaStorage(folder)
            meta = SocialCrawlResolver._metadata(PAYLOAD, "123")
            raw = Path(folder) / "raw.m4a"
            raw.write_bytes(b"raw")
            async def convert(_self, _raw, output, **_kwargs):
                output.write_bytes(b"mp3")
            with patch.object(main, "storage", storage), \
                    patch.object(main.resolver, "resolve", new_callable=AsyncMock, return_value=meta) as lookup, \
                    patch.object(main, "search_ytmusic", return_value="youtube-id"), \
                    patch.object(main.AppleMusicDownloader, "_ytdlp_download", new_callable=AsyncMock,
                                 side_effect=[RateLimitError("rate limited"), raw]) as download, \
                    patch.object(main.AppleMusicDownloader, "_rotate_and_sleep", new_callable=AsyncMock), \
                    patch.object(main.AppleMusicDownloader, "_to_mp3", convert):
                await main.process_scrape_request(ScrapeRequest(url=SONG))
            lookup.assert_awaited_once()
            self.assertEqual(download.await_count, 2)
            await storage.close()
