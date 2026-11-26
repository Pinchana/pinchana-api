"""Pinchana TikTok scraper plugin."""

from .main import plugin, router

scrape = plugin.scrape

__all__ = ["scrape", "router"]
