"""Vacancy collectors."""

from .file import FileCollector
from .hh import HHCollector
from .hh_public import HHPublicPageCollector, HHPublicPageError
from .trudvsem import TrudvsemCollector, TrudvsemCollectorError

__all__ = [
    "FileCollector",
    "HHCollector",
    "HHPublicPageCollector",
    "HHPublicPageError",
    "TrudvsemCollector",
    "TrudvsemCollectorError",
]
