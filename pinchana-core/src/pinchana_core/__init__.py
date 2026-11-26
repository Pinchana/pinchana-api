"""scraper-core — shared components for the modular scraper platform."""

from .docker_manager import ModuleContainerManager
from .library import PlaylistResult, ScrapeError, ScrapeResult
from .models import MediaItem, TrackItem, ScrapeRequest, ScrapeResponse
from .music import MusicDownloader, MusicDownloadError
from .plugins import PluginRegistry, ScraperPlugin, registry
from .storage import MediaStorage
from .vpn import GluetunController, VpnRotationCooldownError, VpnRotationError

__all__ = [
    "MediaItem",
    "TrackItem",
    "ScrapeRequest",
    "ScrapeResponse",
    "ScrapeResult",
    "ScrapeError",
    "PlaylistResult",
    "MediaStorage",
    "MusicDownloader",
    "MusicDownloadError",
    "GluetunController",
    "VpnRotationCooldownError",
    "VpnRotationError",
    "PluginRegistry",
    "ScraperPlugin",
    "registry",
    "ModuleContainerManager",
]
