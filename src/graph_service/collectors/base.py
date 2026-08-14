from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import CollectionResult


class Collector(ABC):
    @abstractmethod
    def collect(self) -> CollectionResult:
        """Collect normalized vacancy records."""
