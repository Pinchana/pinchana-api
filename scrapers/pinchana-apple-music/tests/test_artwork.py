import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

from pinchana_core.models import ScrapeRequest
from pinchana_core.storage import MediaStorage
from pinchana_apple_music import main
from pinchana_apple_music.artwork import spotify_artwork
from pinchana_apple_music.socialcrawl import SocialCrawlResolver
from test_tracks import PAYLOAD, SONG

META = {"id": "am-123", "title": "Example", "artist": "Artist", "duration": 180,
        "cover_url": None, "album": None}
TRACK = {"name": "Example", "artists": [{"name": "Artist"}], "duration_ms": 180000,
         "album": {"name": "Album", "images": [{"url": "https://example.com/cover.jpg"}]}}


class ArtworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, SPOTIFY_CLIENT_ID="test-id", SPOTIFY_CLIENT_SECRET="test-secret")
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_socialcrawl_cover_has_priority(self):
        payload = copy.deepcopy(PAYLOAD)
        payload["data"]["post"]["content"]["thumbnail_url"] = "https://example.com/apple.jpg"
        meta = SocialCrawlResolver._metadata(payload, "123")
        handler = AsyncMock()
        result = await spotify_artwork(meta, transport=httpx.MockTransport(handler))
        self.assertEqual(result["cover_url"], "https://example.com/apple.jpg")
        handler.assert_not_called()

    async def test_spotify_matches_title_artist_and_duration(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.host == "accounts.spotify.com":
                self.assertEqual(request.content, b"grant_type=client_credentials")
                return httpx.Response(200, json={"access_token": "test-token"})
            self.assertEqual(request.headers["Authorization"], "Bearer test-token")
            items = [{**TRACK, "name": "Other"}, {**TRACK, "artists": [{"name": "Other"}]},
                     {**TRACK, "duration_ms": 210000}, TRACK]
            return httpx.Response(200, json={"tracks": {"items": items}})
        result = await spotify_artwork(META, transport=httpx.MockTransport(handler))
        self.assertEqual(result["cover_url"], "https://example.com/cover.jpg")
        self.assertEqual(result["album"], "Album")
        self.assertIsNone(META["cover_url"])
        self.assertEqual(len(requests), 2)

    async def test_missing_credentials_and_upstream_failures_are_optional(self):
        handler = AsyncMock()
        with patch.dict(os.environ, SPOTIFY_CLIENT_SECRET=""):
            self.assertEqual(await spotify_artwork(META, transport=httpx.MockTransport(handler)), META)
        handler.assert_not_called()
        for status in (401, 429, 503):
            with self.subTest(status=status):
                self.assertEqual(await spotify_artwork(META, transport=httpx.MockTransport(
                    lambda request: httpx.Response(status))), META)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires ffmpeg")
    async def test_cover_embedded_in_mp3_and_exposed_in_response(self):
        with tempfile.TemporaryDirectory() as folder:
            storage = MediaStorage(folder)
            async def raw_audio(_self, _url, post_dir):
                raw = post_dir / "raw.wav"
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=0.1", str(raw)], check=True)
                return raw
            async def cover(_self, url, dest):
                Image.new("RGB", (320, 320), "red").save(dest)
                return True
            meta = {**META, "cover_url": "https://example.com/apple.jpg"}
            with patch.object(main, "storage", storage), \
                 patch.object(main.resolver, "resolve", AsyncMock(return_value=meta)), \
                 patch.object(main, "search_ytmusic", return_value="youtube-id"), \
                 patch.object(main.AppleMusicDownloader, "_ytdlp_download", raw_audio), \
                 patch.object(main.AppleMusicDownloader, "_download_cover", cover):
                result = await main.process_scrape_request(ScrapeRequest(url=SONG))
            self.assertEqual(result.cover_url, "/media/apple_music/am-123/cover.jpg")
            self.assertEqual(result.thumbnail_url, result.cover_url)
            output = subprocess.check_output(["ffprobe", "-v", "quiet", "-show_streams", "-of", "json", str(storage.audio_path("am-123"))])
            self.assertTrue(any(s.get("disposition", {}).get("attached_pic") == 1 for s in json.loads(output)["streams"]))
            await storage.close()
