"""Import individual Pinchana scrapers from a shared namespace."""

from importlib import import_module
from types import ModuleType

__all__ = [
    "apple_music",
    "bluesky",
    "coub",
    "deezer",
    "instagram",
    "shorts",
    "soundcloud",
    "spotify",
    "threads",
    "tiktok",
    "twitter",
    "ytgroups",
    "ytmusic",
]


def __getattr__(name: str) -> ModuleType:
    if name in __all__:
        return import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
