from .main import plugin, router

scrape = plugin.scrape
playlist = plugin.playlist

__all__ = ["scrape", "playlist", "router"]
