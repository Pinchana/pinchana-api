import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pinchana_core.models import ScrapeRequest
from pinchana_core.storage import MediaStorage
from pinchana_shorts import main as shorts
from yt_dlp.utils import DownloadError


class ShortsScrapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_age_verification_does_not_retry_or_rotate_vpn(self):
        request = ScrapeRequest(url="https://www.youtube.com/shorts/abcdefghijk")
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(shorts, "storage", MediaStorage(base_path=directory)),
            patch.object(shorts, "ManagedYoutubeDL") as downloader,
            patch.object(shorts, "trigger_rotation", new_callable=AsyncMock) as rotate,
            patch.object(shorts.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            extract = downloader.return_value.__enter__.return_value.extract_info
            extract.side_effect = DownloadError(
                "ERROR: [youtube] abcdefghijk: Sign in to confirm your age"
            )
            with self.assertRaises(HTTPException) as failure:
                await shorts.process_scrape_request(request)

        self.assertEqual(failure.exception.status_code, 403)
        self.assertIn("age-verified account", failure.exception.detail)
        extract.assert_called_once()
        rotate.assert_not_awaited()
        sleep.assert_not_awaited()

    def test_bot_check_still_counts_as_rate_limited(self):
        self.assertTrue(shorts._is_rate_limited(
            DownloadError("ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot")
        ))
