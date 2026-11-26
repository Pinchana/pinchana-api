"""Threads (Meta) scraper plugin for Pinchana."""

from .main import plugin, router

scrape = plugin.scrape
inspect = plugin.inspect

__all__ = ["scrape", "inspect", "router"]
