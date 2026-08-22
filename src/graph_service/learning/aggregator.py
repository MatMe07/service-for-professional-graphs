from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .base import normalize_resource_url
from .parsers import build_parsers
from .providers import validate_provider


DEFAULT_PROVIDERS = ("stepik", "habr", "youtube")
DEFAULT_PROVIDER_QUOTAS = {"stepik": 2, "habr": 1, "youtube": 1}
CATALOG_VERSION_PREFIX = "auto"


class LearningAggregator:
    def __init__(
        self,
        providers: list[str] | tuple[str, ...] | None = None,
        max_per_node: int = 4,
        quotas: dict[str, int] | None = None,
        youtube_api_key_env: str = "YOUTUBE_API_KEY",
    ) -> None:
        self.max_per_node = max(1, int(max_per_node))
        self.provider_names = tuple(str(name).strip() for name in (providers or DEFAULT_PROVIDERS) if str(name).strip())
        merged_quotas: dict[str, int] = {**DEFAULT_PROVIDER_QUOTAS}
        for key, value in (quotas or {}).items():
            merged_quotas[str(key)] = max(0, int(value))
        self.quotas = {name: max(0, merged_quotas.get(name, 1)) for name in self.provider_names}
        self.providers = build_parsers(self.provider_names, youtube_api_key_env=youtube_api_key_env)
        self.last_stats: dict[str, dict[str, Any]] = {}
        self.last_errors: dict[str, list[dict[str, str]]] = {}

    def collect_all(self, node_names: list[str]) -> dict[str, list[dict[str, Any]]]:
        self.last_stats = {}
        self.last_errors = {}
        collected: dict[str, list[dict[str, Any]]] = {}
        for node_name in node_names:
            collected[str(node_name)] = self._collect_node(str(node_name))
        return collected

    def to_catalog(self, collected: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        resources = [item for node in sorted(collected) for item in collected[node]]
        return {
            "version": f"{CATALOG_VERSION_PREFIX}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            "resources": resources,
        }

    def _collect_node(self, node_name: str) -> list[dict[str, Any]]:
        fetched: dict[str, list[dict[str, Any]]] = {}
        errors: list[dict[str, str]] = []
        provider_stats: dict[str, dict[str, Any]] = {}
        for provider in self.providers:
            if not bool(getattr(provider, "configured", True)):
                provider_stats[provider.name] = {"requested": False, "found": 0}
                continue
            provider_stats[provider.name] = {"requested": True, "found": 0}
            try:
                found = provider.search(node_name, self.max_per_node)
            except Exception as exc:
                errors.append({"provider": provider.name, "message": str(exc)})
                continue
            provider_stats[provider.name]["found"] = len(found)
            fetched[provider.name] = found
        kept = self._allocate(node_name, fetched)
        self.last_errors[node_name] = errors
        self.last_stats[node_name] = {"providers": provider_stats, "kept": len(kept), "errors": len(errors)}
        return kept

    def _allocate(
        self,
        node_name: str,
        fetched: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        order = [provider.name for provider in self.providers]
        pointers = {name: 0 for name in order}
        kept: list[dict[str, Any]] = []
        seen: set[str] = set()

        def take(name: str, count: int) -> int:
            added = 0
            source = fetched.get(name, [])
            while pointers[name] < len(source) and added < count:
                resource = self._normalize_item(node_name, source[pointers[name]])
                pointers[name] += 1
                if resource is None or resource["url"] in seen:
                    continue
                seen.add(resource["url"])
                kept.append(resource)
                added += 1
            return added

        remaining = self.max_per_node
        for name in order:
            if remaining <= 0:
                break
            quota = min(self.quotas.get(name, 1), remaining)
            remaining -= take(name, quota)
        while remaining > 0 and any(pointers[name] < len(fetched.get(name, [])) for name in order):
            progressed = False
            for name in order:
                if remaining <= 0:
                    break
                before = remaining
                remaining -= take(name, remaining)
                progressed = progressed or remaining < before
            if not progressed:
                break
        return kept

    def _normalize_item(self, node_name: str, item: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        provider = str(item.get("provider", "")).strip()
        raw_url = str(item.get("url", "")).strip()
        if not provider or not raw_url:
            return None
        try:
            url = normalize_resource_url(raw_url)
            validate_provider(provider, url)
        except ValueError:
            return None
        resource = {
            "node": node_name,
            "title": str(item.get("title") or "").strip() or node_name,
            "url": url,
            "provider": provider,
            "kind": str(item.get("kind", "unknown")),
            "language": str(item.get("language", "unknown")),
            "access": str(item.get("access", "free")),
            "level": str(item.get("level", "unknown")),
            "duration": item.get("duration"),
            "certificate": item.get("certificate"),
        }
        if item.get("channel"):
            resource["channel"] = str(item["channel"])
        return resource
