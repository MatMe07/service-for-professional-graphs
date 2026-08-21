from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .ai import AIError, suggest_dictionary_candidates
from .collectors import HHCollector
from .collectors.hh import HHCollectorError
from .config import ConfigError, load_config, load_node_definitions
from .extraction import ProfessionalPhraseExtractor
from .pipeline import PipelineError, run_pipeline
from .professions import build_profession_config, load_profession_catalog, resolve_profession
from .storage import write_json
from .validation import validate_run_directory
from .webapp import serve_local_app


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
    probe = subparsers.add_parser("hh-probe", help="Безопасно проверить минимальный реальный сбор HH.")
    probe.add_argument("--config", required=True, help="Путь к конфигурации с source.type=hh.")
    probe.add_argument("--output", default="data/hh_probe.json", help="Куда сохранить результат проверки.")
    probe.add_argument("--limit", type=int, default=5, help="Не больше 20 вакансий; по умолчанию 5.")
    public_hh = subparsers.add_parser("hh-public", help="Собрать прямые публичные страницы вакансий HH без токена.")
    public_hh.add_argument("--profession", required=True, help="Название или slug профессии из каталога.")
    public_hh.add_argument("--url", action="append", required=True, help="Прямая ссылка https://hh.ru/vacancy/<id>; можно повторять.")
    public_hh.add_argument("--catalog", default="dictionaries/professions.json", help="Каталог профессий.")
    public_hh.add_argument("--runs-root", default="data/runs", help="Каталог запусков.")
    public_search = subparsers.add_parser("public-search", help="Автоматически собрать вакансии без ключа через API «Работа России».")
    public_search.add_argument("--profession", required=True, help="Название или slug профессии из каталога.")
    public_search.add_argument("--period-days", type=int, default=30, help="Период изменений, по умолчанию 30 дней.")
    public_search.add_argument("--max-pages", type=int, default=2, help="Не больше 100 вакансий на страницу.")
    public_search.add_argument("--region-code", action="append", default=[], help="Необязательный код региона «Работы России».")
    public_search.add_argument("--catalog", default="dictionaries/professions.json", help="Каталог профессий.")
    public_search.add_argument("--runs-root", default="data/runs", help="Каталог запусков.")
    check_run = subparsers.add_parser("check-run", help="Проверить целостность готовой папки запуска.")
    check_run.add_argument("--run-dir", required=True, help="Путь к data/runs/<run_id>.")
    professions = subparsers.add_parser("list-professions", help="Показать стартовый каталог IT-профессий.")
    professions.add_argument("--catalog", default="dictionaries/professions.json", help="Путь к каталогу профессий.")
    professions.add_argument("--limit", type=int, default=15, help="Сколько профессий вывести.")
    init_config = subparsers.add_parser("init-config", help="Создать HH-конфигурацию для профессии из каталога.")
    init_config.add_argument("--catalog", default="dictionaries/professions.json", help="Путь к каталогу профессий.")
    init_config.add_argument("--profession", required=True, help="Slug профессии из list-professions.")
    init_config.add_argument("--output", required=True, help="Путь нового profession_config.json.")
    init_config.add_argument("--force", action="store_true", help="Разрешить перезапись существующего файла.")
    serve = subparsers.add_parser("serve", help="Запустить локальную веб-страницу управления.")
    serve.add_argument("--project-root", default=".", help="Корень проекта.")
    serve.add_argument("--host", default="127.0.0.1", help="По умолчанию доступ только с этого компьютера.")
    serve.add_argument("--port", type=int, default=8765, help="Порт локального сервера.")
    serve.add_argument("--allow-network", action="store_true", help="Явно разрешить привязку не к localhost.")
    
    hh_requests = subparsers.add_parser("hh-requests", help="Сбор HH через requests + BeautifulSoup (может дать CAPTCHA).")
    hh_requests.add_argument("--profession", required=True, help="Название или slug профессии из каталога.")
    hh_requests.add_argument("--catalog", default="dictionaries/professions.json", help="Каталог профессий.")
    hh_requests.add_argument("--runs-root", default="data/runs", help="Каталог запусков.")
    hh_requests.add_argument("--max-pages", type=int, default=3, help="Максимум страниц для парсинга.")
    hh_requests.add_argument("--area", default="1", help="Код региона (1 — Москва, 2 — СПб, и т.д.)")
    hh_requests.add_argument("--max-vacancies", type=int, default=0, help="Максимум вакансий для сбора (0 = без лимита)")
    
    ai_suggest = subparsers.add_parser("ai-suggest", help="Предложить новые ноды по unclassified.json без автодобавления.")
    ai_suggest.add_argument("--config", required=True, help="Конфигурация с разделом ai.")
    ai_suggest.add_argument("--run-dir", required=True, help="Папка запуска с unclassified.json.")
    ai_suggest.add_argument("--output", help="Куда сохранить AI-кандидатов; по умолчанию внутри запуска.")
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
                hh_collector = HHCollector(config.source)
                hh_contact_ready = hh_collector.live_contact_ready
            else:
                hh_contact_ready = None
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
                    "hh_live_contact_ready": hh_contact_ready,
                    **phrase_versions,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "hh-probe":
        try:
            if not 1 <= args.limit <= 20:
                raise ConfigError("--limit должен быть от 1 до 20.")
            config = load_config(Path(args.config))
            if config.source.get("type") != "hh":
                raise ConfigError("Для hh-probe нужен source.type=hh.")
            probe_source = {
                **config.source,
                "queries": list(config.source.get("queries", []))[:1],
                "areas": list(config.source.get("areas", []))[:1],
                "max_pages": 1,
                "per_page": args.limit,
                "retries": min(int(config.source.get("retries", 3)), 2),
            }
            collector = HHCollector(probe_source)
            collector.validate_live_contact()
            result = collector.collect()
            output_path = Path(args.output).resolve()
            write_json(
                output_path,
                {
                    "status": "ok",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "settings": {
                        "query": probe_source["queries"][0],
                        "area": probe_source["areas"][0] if probe_source["areas"] else None,
                        "limit": args.limit,
                        "token_used": bool(os.getenv(collector.token_env, "").strip()),
                    },
                    "search_responses": result.search_responses,
                    "vacancies": [
                        {"normalized": vacancy.to_dict(), "raw": vacancy.raw}
                        for vacancy in result.vacancies
                    ],
                },
            )
        except (ConfigError, HHCollectorError, ValueError) as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "status": "ok",
                    "vacancies": len(result.vacancies),
                    "search_responses": len(result.search_responses),
                    "output": str(output_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "hh-public":
        try:
            catalog_path = Path(args.catalog).resolve()
            catalog = load_profession_catalog(catalog_path)
            profession, _, _ = resolve_profession(catalog, args.profession)
            project_root = catalog_path.parent.parent
            config_path = project_root / "data" / "configs" / f"{profession['slug']}_hh_public.json"
            generated = build_profession_config(catalog, profession["slug"], config_path, project_root)
            generated["source"] = {
                "type": "hh_public_pages",
                "urls": list(dict.fromkeys(args.url)),
                "contact_email": "mlprofessionalgraphs@gmail.com",
                "contact_email_env": "HH_CONTACT_EMAIL",
                "timeout_seconds": 30,
                "retries": 2,
                "request_interval_seconds": 1.0,
            }
            write_json(config_path, generated)
            report = run_pipeline(config_path, Path(args.runs_root))
        except (ConfigError, PipelineError, ValueError) as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] != "failed" else 1
    if args.command == "public-search":
        try:
            catalog_path = Path(args.catalog).resolve()
            catalog = load_profession_catalog(catalog_path)
            profession, _, _ = resolve_profession(catalog, args.profession)
            project_root = catalog_path.parent.parent
            config_path = project_root / "data" / "configs" / f"{profession['slug']}_public_search.json"
            generated = build_profession_config(catalog, profession["slug"], config_path, project_root)
            generated["source"] = {
                "type": "trudvsem",
                "queries": profession["queries"],
                "region_codes": list(dict.fromkeys(args.region_code)),
                "period_days": args.period_days,
                "per_page": 100,
                "max_pages": args.max_pages,
                "retries": 3,
                "timeout_seconds": 30,
                "request_interval_seconds": 0.3,
                "user_agent": "ProfessionalGraphs/0.9 (mlprofessionalgraphs@gmail.com)",
                "include_inactive": False,
            }
            write_json(config_path, generated)
            report = run_pipeline(config_path, Path(args.runs_root))
        except (ConfigError, PipelineError, ValueError) as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] != "failed" else 1
    if args.command == "check-run":
        result = validate_run_directory(Path(args.run_dir))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ok" else 1
    if args.command == "list-professions":
        try:
            if args.limit < 1:
                raise ConfigError("--limit должен быть положительным числом.")
            catalog = load_profession_catalog(args.catalog)
        except ConfigError as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "version": catalog.get("version"),
                    "total": len(catalog["professions"]),
                    "items": catalog["professions"][: args.limit],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "init-config":
        try:
            catalog_path = Path(args.catalog).resolve()
            output_path = Path(args.output).resolve()
            if output_path.exists() and not args.force:
                raise ConfigError(f"Файл уже существует: {output_path}. Используйте --force для перезаписи.")
            catalog = load_profession_catalog(catalog_path)
            project_root = catalog_path.parent.parent
            generated = build_profession_config(catalog, args.profession, output_path, project_root)
            write_json(output_path, generated)
        except ConfigError as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"status": "ok", "output": str(output_path)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "serve":
        if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.allow_network:
            print("Ошибка: внешний адрес требует явного флага --allow-network.", file=sys.stderr)
            return 2
        if not 0 <= args.port <= 65535:
            print("Ошибка: порт должен быть от 0 до 65535.", file=sys.stderr)
            return 2
        serve_local_app(Path(args.project_root), host=args.host, port=args.port)
        return 0
    if args.command == "ai-suggest":
        try:
            config = load_config(Path(args.config))
            run_dir = Path(args.run_dir).resolve()
            unclassified_path = run_dir / "unclassified.json"
            output_path = Path(args.output).resolve() if args.output else run_dir / "ai_candidates.json"
            result = suggest_dictionary_candidates(config.ai, unclassified_path, output_path)
        except (ConfigError, AIError) as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({**result, "output": str(output_path)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "hh-requests":
        try:
            catalog_path = Path(args.catalog).resolve()
            catalog = load_profession_catalog(catalog_path)
            profession, _, _ = resolve_profession(catalog, args.profession)
            project_root = catalog_path.parent.parent
            
            config_path = project_root / "data" / "configs" / f"{profession['slug']}_hh_requests.json"
            generated = build_profession_config(catalog, profession["slug"], config_path, project_root)
            
            generated["source"] = {
                "type": "hh_requests",
                "queries": profession["queries"],
                "areas": [args.area],
                "max_pages": args.max_pages,
                "per_page": 20,
                "retries": 2,
                "timeout_seconds": 30,
                "request_interval_seconds": 3.0,
                "max_vacancies": args.max_vacancies,
                "nodes_path": str((project_root / "dictionaries" / "canonical_nodes.json").resolve()),
            }
            
            write_json(config_path, generated)
            report = run_pipeline(
                config_path=config_path,
                runs_root=Path(args.runs_root),
                vacancies_path=None,
            )
            
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["status"] != "failed" else 1
            
        except Exception as exc:
            print(f"Ошибка: {exc}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 2
    parser.error("Неизвестная команда")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
