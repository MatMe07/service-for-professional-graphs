from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .collectors import HHCollector
from .collectors.hh import HHCollectorError
from .config import ConfigError, load_config, load_node_definitions
from .extraction import ProfessionalPhraseExtractor
from .pipeline import PipelineError, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph-service",
        description="Построение профессиональных графов по вакансиям без нейросетей.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Запустить полный файловый конвейер.")
    run.add_argument("--config", required=True, help="Путь к profession_config.json.")
    run.add_argument("--vacancies", help="Необязательный путь к локальному файлу вакансий.")
    run.add_argument("--runs-root", default="data/runs", help="Каталог запусков.")
    run.add_argument("--run-id", help="Фиксированный ID запуска для теста или отладки.")
    check = subparsers.add_parser("check-config", help="Проверить настройки и словарь без запуска сбора.")
    check.add_argument("--config", required=True, help="Путь к profession_config.json.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        try:
            report = run_pipeline(
                config_path=Path(args.config),
                vacancies_path=Path(args.vacancies) if args.vacancies else None,
                runs_root=Path(args.runs_root),
                run_id=args.run_id,
            )
        except (ConfigError, PipelineError, ValueError) as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] != "failed" else 1
    if args.command == "check-config":
        try:
            config = load_config(Path(args.config))
            dictionary_version, nodes = load_node_definitions(config.nodes_path)
            phrase_versions = {}
            if config.phrase_rules_path is not None and config.split_rules_path is not None:
                phrase_extractor = ProfessionalPhraseExtractor.from_files(
                    config.phrase_rules_path,
                    config.split_rules_path,
                )
                phrase_versions = phrase_extractor.versions
            if config.source.get("type") == "hh":
                HHCollector(config.source)
        except (ConfigError, HHCollectorError) as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "status": "ok",
                    "profession": config.profession_name,
                    "source_type": config.source.get("type", "file"),
                    "grades": config.grades,
                    "dictionary_version": dictionary_version,
                    "dictionary_nodes": len(nodes),
                    **phrase_versions,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    parser.error("Неизвестная команда")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
