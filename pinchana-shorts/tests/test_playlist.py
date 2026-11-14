import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pinchana_core.models import ScrapeRequest
from pinchana_core.storage import MediaStorage
from pinchana_shorts import main as shorts
from pinchana_shorts.main import process_playlist_item


class YouTubePlaylistItemTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_normal_scraper_with_canonical_single_video_url(self):
        async def singleflight(identifier, operation):
            return await operation()
        for url in ["https://www.youtube.com/watch?v=abcdefghijk&list=PLtest", "https://youtu.be/abcdefghijk"]:
            with patch("pinchana_shorts.main.storage.singleflight", side_effect=singleflight), patch(
                "pinchana_shorts.main._scrape_once", AsyncMock(return_value="result")
            ) as scrape:
                self.assertEqual(await process_playlist_item(ScrapeRequest(url=url)), "result")
                scrape.assert_awaited_once_with("https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk")

    async def test_rejects_remote_hosts_and_invalid_video_ids(self):
        for url in ["https://youtube.com.evil.example/watch?v=abcdefghijk", "https://youtube.com/watch?v=bad",
                    "http://youtube.com/watch?v=abcdefghijk"]:
            with self.assertRaises(HTTPException) as failure:
                await process_playlist_item(ScrapeRequest(url=url))
            self.assertEqual(failure.exception.status_code, 400)

    async def test_cached_short_backfills_duration_without_downloading(self):
        identifier = "abcdefghijk"
        url = f"https://www.youtube.com/shorts/{identifier}"
        with tempfile.TemporaryDirectory() as folder:
            storage = MediaStorage(base_path=folder)
            storage.prepare_post_dir(identifier)
            video = storage.video_path(identifier)
            video.write_bytes(b"video fixture")
            storage.save_metadata(identifier, {
                "shortcode": identifier, "caption": "Example", "author": "Author",
                "media_type": "video", "thumbnail_url": "",
                "video_url": f"/media/shorts/{identifier}/video.mp4",
            })
            with (
                patch.object(shorts, "storage", storage),
                patch.object(shorts, "probe_video", return_value=({}, 12)) as probe,
                patch.object(shorts, "_download_short") as download,
            ):
                self.assertEqual((await shorts._scrape_once(url, identifier)).duration, 12)
                self.assertEqual((await shorts._scrape_once(url, identifier)).duration, 12)
            self.assertEqual(storage.load_metadata(identifier)["duration"], 12)
            self.assertTrue(video.exists())
            probe.assert_called_once_with(Path(video))
            download.assert_not_called()
