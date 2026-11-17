from io import BytesIO

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.networking import Response
from yt_dlp.networking.exceptions import HTTPError

from pinchana_core.ytdlp import ManagedYoutubeDL


def test_downloader_closes_responses_even_when_the_error_is_retained(monkeypatch):
    success = Response(BytesIO(b"ok"), "https://example.com/video", {})
    denied = Response(BytesIO(b"denied"), "https://example.com/video", {}, status=403)

    def urlopen(self, request):
        if request == "denied":
            raise HTTPError(denied)
        return success

    monkeypatch.setattr(YoutubeDL, "urlopen", urlopen)
    with ManagedYoutubeDL({"quiet": True}) as downloader:
        assert downloader.urlopen("ok") is success
        with pytest.raises(HTTPError) as error:
            downloader.urlopen("denied")
        assert error.value.response.read(1) == b"d"
        assert not success.closed and not denied.closed

    assert success.closed and error.value.response.closed
