"""Release outstanding HTTP responses at the end of a yt-dlp operation."""

import logging
from weakref import WeakSet

from yt_dlp import YoutubeDL
from yt_dlp.networking.exceptions import HTTPError

logger = logging.getLogger(__name__)


class ManagedYoutubeDL(YoutubeDL):
    def __init__(self, *args, **kwargs):
        self._open_responses = WeakSet()
        super().__init__(*args, **kwargs)

    def urlopen(self, request):
        try:
            response = super().urlopen(request)
        except HTTPError as error:
            # Extractors can inspect error bodies. Release them at teardown,
            # even if an exception traceback still references the response.
            self._open_responses.add(error.response)
            raise
        self._open_responses.add(response)
        return response

    def close(self):
        try:
            for response in self._open_responses:
                if not response.closed:
                    try:
                        response.close()
                    except Exception:
                        logger.warning("Could not close a yt-dlp HTTP response", exc_info=True)
        finally:
            self._open_responses.clear()
            super().close()
