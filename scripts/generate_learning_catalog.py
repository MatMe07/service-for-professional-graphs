from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graph_service.config import ConfigError, load_node_definitions
from graph_service.learning.aggregator import LearningAggregator
from graph_service.learning.base import check_resource_url, normalize_resource_url
from graph_service.storage import write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate-learning-catalog",
        description="Собрать каталог учебных материалов для всех нод словаря графа.",
    )
    parser.add_argument(
        "--nodes",
        default="dictionaries/canonical_nodes.json",
        help="Файл словаря нод графа.",
    )
    parser.add_argument(
        "--catalog",
        default="dictionaries/learning_resources.json",
        help="Текущий каталог материалов; официальная документация из него сохраняется.",
    )
    parser.add_argument("--output", help="Куда сохранить результат; по умолчанию совпадает с --catalog.")
    parser.add_argument("--providers", default="stepik,habr,youtube", help="Провайдеры автосбора через запятую.")
    parser.add_argument("--max-per-node", type=int, default=4, help="Максимум собранных материалов на ноду.")
    parser.add_argument(
        "--quotas",
        default="stepik=2,habr=1,youtube=1",
        help="Квоты провайдеров на ноду в виде provider=count через запятую.",
    )
    parser.add_argument("--youtube-api-key-env", default="YOUTUBE_API_KEY")
    parser.add_argument("--no-collect", action="store_true", help="Не запускать автосбор, только пересобрать файл.")
    parser.add_argument(
        "--check-links",
        action="store_true",
        help="Проверить доступность ссылок и исключить недоступные материалы.",
    )
    return parser


def _resolve(path_value: str) -> Path:
    candidate = Path(path_value)
    return candidate if candidate.is_absolute() else (ROOT / candidate).resolve()


def _parse_quotas(value: str) -> dict[str, int]:
    quotas: dict[str, int] = {}
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, raw_count = part.partition("=")
        quotas[name.strip()] = max(0, int(raw_count.strip()))
    return quotas


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    nodes_path = _resolve(args.nodes)
    catalog_path = _resolve(args.catalog)
    output_path = _resolve(args.output) if args.output else catalog_path

    try:
        _, nodes = load_node_definitions(nodes_path)
    except ConfigError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    node_names = sorted({node.name for node in nodes})
    known_nodes = set(node_names)

    preserved: list[dict[str, Any]] = []
    existing_version: str | None = None
    if catalog_path.is_file():
        try:
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Ошибка: не удалось прочитать каталог {catalog_path}: {exc}", file=sys.stderr)
            return 2
        existing_version = data.get("version") if isinstance(data, dict) else None
        for item in data.get("resources", []) if isinstance(data, dict) else []:
            if isinstance(item, dict) and str(item.get("node", "")).strip() in known_nodes:
                preserved.append(item)

    collected: dict[str, list[dict[str, Any]]] = {}
    collection_errors: list[dict[str, str]] = []
    if not args.no_collect:
        providers = [name.strip() for name in args.providers.split(",") if name.strip()]
        aggregator = LearningAggregator(
            providers=providers,
            max_per_node=args.max_per_node,
            quotas=_parse_quotas(args.quotas),
            youtube_api_key_env=args.youtube_api_key_env,
        )
        collected = aggregator.collect_all(node_names)
        collection_errors = [
            {"node": node, **error}
            for node in sorted(collected)
            for error in aggregator.last_errors.get(node, [])
        ]
    aggregated_resources = [item for node in sorted(collected) for item in collected[node]]

    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    invalid_urls = 0
    for item in [*preserved, *aggregated_resources]:
        node = str(item.get("node", "")).strip()
        try:
            url = normalize_resource_url(str(item.get("url", "")))
        except ValueError:
            invalid_urls += 1
            continue
        key = (node, url)
        if key in seen or node not in known_nodes:
            continue
        seen.add(key)
        merged.append({**item, "url": url})

    removed_unavailable = 0
    if args.check_links:
        checked: list[dict[str, Any]] = []
        for item in merged:
            availability = check_resource_url(item["url"])
            if availability.get("available") is False:
                removed_unavailable += 1
                continue
            checked.append(item)
        merged = checked

    catalog: dict[str, Any] = {
        "version": existing_version or "auto",
        "resources": merged,
    }
    write_json(output_path, catalog)

    without_materials = [name for name in node_names if not any(item[0] == name for item in seen)]
    provider_counts: dict[str, int] = {}
    for item in merged:
        provider_counts[str(item.get("provider", "unknown"))] = provider_counts.get(str(item.get("provider", "unknown")), 0) + 1
    summary = {
        "nodes_total": len(node_names),
        "nodes_with_materials": len(node_names) - len(without_materials),
        "nodes_without_materials": len(without_materials),
        "resources_total": len(merged),
        "preserved_from_catalog": len(preserved),
        "collected_by_parsers": len(aggregated_resources),
        "invalid_urls_skipped": invalid_urls,
        "unavailable_links_removed": removed_unavailable,
        "links_checked": args.check_links,
        "providers": provider_counts,
        "collection_errors": collection_errors,
        "output": str(output_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
