import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from pinchana_core.models import ScrapeRequest
from pinchana_deezer.main import playlist_metadata


class DeezerPlaylistTests(unittest.IsolatedAsyncioTestCase):
    async def test_playlist_and_album_include_all_tracks(self):
        for kind in ["playlist", "album"]:
            collection = Mock(title="Collection")
            collection.get_tracks.return_value = iter([Mock(id=123), Mock(id=456)])
            client = Mock()
            getattr(client, f"get_{kind}").return_value = collection
            with patch("pinchana_deezer.main.dz_downloader.dz", client):
                result = await playlist_metadata(ScrapeRequest(url=f"https://www.deezer.com/en/{kind}/1"))
            self.assertEqual(result, {"title": "Collection", "urls": [
                "https://www.deezer.com/track/123", "https://www.deezer.com/track/456",
            ]})

    async def test_listing_stops_at_limit(self):
        collection = Mock(title="Large playlist")
        collection.get_tracks.return_value = (Mock(id=index) for index in range(1000))
        with patch("pinchana_deezer.main.dz_downloader.dz.get_playlist", return_value=collection):
            with self.assertRaises(HTTPException) as failure:
                await playlist_metadata(ScrapeRequest(url="https://deezer.com/playlist/1"))
        self.assertEqual(failure.exception.status_code, 400)
