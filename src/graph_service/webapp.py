from __future__ import annotations

import json
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .config import ConfigError
from .pipeline import PipelineError, run_pipeline
from .professions import build_profession_config, load_profession_catalog, resolve_profession
from .storage import write_json
from .validation import validate_run_directory


MAX_BODY_SIZE = 1_000_000


class _JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, label: str, runner: Any) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "stage": "В очереди",
            "message": f"Готовим запуск: {label}.",
        }
        with self._lock:
            self._prune_locked()
            self._jobs[job_id] = job

        def update(event: dict[str, Any]) -> None:
            with self._lock:
                current = self._jobs.get(job_id)
                if current is None:
                    return
                next_progress = max(
                    int(current.get("progress", 0)),
                    max(0, min(int(event.get("progress", 0)), 100)),
                )
                current.update(event)
                current["progress"] = next_progress
                current["status"] = "running"

        def work() -> None:
            update(
                {
                    "progress": 1,
                    "stage": "Запуск",
                    "message": f"Запускаем: {label}.",
                }
            )
            try:
                report = runner(update)
            except Exception as exc:  # pragma: no cover - tested through public API
                with self._lock:
                    current = self._jobs[job_id]
                    current.update(
                        {
                            "status": "error",
                            "stage": "Ошибка",
                            "message": str(exc),
                        }
                    )
                return
            report_failed = report.get("status") == "failed"
            with self._lock:
                current = self._jobs[job_id]
                current.update(
                    {
                        "status": "completed",
                        "progress": 100,
                        "stage": "Готово с замечаниями" if report_failed else "Готово",
                        "message": (
                            "Отчёт построен, но проверка нашла ошибки в его структуре."
                            if report_failed
                            else "Вакансии обработаны, отчёт готов."
                        ),
                        "result": report,
                    }
                )

        threading.Thread(target=work, daemon=True, name=f"vacancy-job-{job_id[:8]}").start()
        return self.get(job_id) or job

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def _prune_locked(self) -> None:
        if len(self._jobs) < 50:
            return
        removable = [
            job_id
            for job_id, job in self._jobs.items()
            if job.get("status") in {"completed", "error"}
        ]
        for job_id in removable[: max(1, len(self._jobs) - 49)]:
            self._jobs.pop(job_id, None)


def serve_local_app(project_root: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    root = project_root.resolve()
    handler = make_handler(root)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Professional Graphs: http://{host}:{server.server_port}")
    print("Для остановки нажмите Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def make_handler(project_root: Path) -> type[BaseHTTPRequestHandler]:
    root = project_root.resolve()
    runs_root = root / "data" / "runs"
    catalog_path = root / "dictionaries" / "professions.json"
    jobs = _JobRegistry()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ProfessionalGraphs/0.9"

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/":
                self._send_bytes(HTTPStatus.OK, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/favicon.ico":
                self._send_bytes(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
                return
            if path == "/api/status":
                self._send_json(HTTPStatus.OK, _status(root, runs_root))
                return
            if path == "/api/professions":
                catalog = load_profession_catalog(catalog_path)
                self._send_json(
                    HTTPStatus.OK,
                    {"version": catalog.get("version"), "items": catalog["professions"]},
                )
                return
            if path == "/api/runs":
                self._send_json(HTTPStatus.OK, {"items": _list_runs(runs_root)})
                return
            if path.startswith("/api/jobs/"):
                job_id = path.removeprefix("/api/jobs/")
                job = jobs.get(job_id)
                if job is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"status": "error", "message": "Задание не найдено."})
                else:
                    self._send_json(HTTPStatus.OK, job)
                return
            if path.startswith("/runs/"):
                self._serve_run_file(path.removeprefix("/runs/"), runs_root)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"status": "error", "message": "Маршрут не найден."})

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = self._read_json()
                path = urlsplit(self.path).path
                if path == "/api/run/hh-html":
                    self._run_hh_html(payload)
                    return
                if path == "/api/run/public-search":
                    self._run_public_search(payload)
                    return
                if path == "/api/run/validate":
                    self._validate_run(payload)
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"status": "error", "message": "Маршрут не найден."})
            except (ConfigError, PipelineError, ValueError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"status": "error", "message": str(exc)})
            except Exception as exc:  # pragma: no cover - last-resort local UI boundary
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"status": "error", "message": f"Внутренняя ошибка: {type(exc).__name__}"},
                )

        def _run_hh_html(self, payload: dict[str, Any]) -> None:
            requested = str(payload.get("profession", "")).strip()
            period_days = int(payload.get("period_days", 30))
            max_pages = int(payload.get("max_pages", 3))
            max_vacancies = int(payload.get("max_vacancies", 50))
            area = str(payload.get("area", "1")).strip()
            if not 1 <= period_days <= 3650:
                raise ValueError("Период должен быть от 1 до 3650 дней.")
            if not 1 <= max_pages <= 10:
                raise ValueError("Можно выбрать от 1 до 10 страниц HH.")
            if not 1 <= max_vacancies <= 500:
                raise ValueError("Лимит должен быть от 1 до 500 вакансий.")
            if not area.isdigit():
                raise ValueError("Код региона HH должен быть числом.")
            catalog = load_profession_catalog(catalog_path)
            profession, _, _ = resolve_profession(catalog, requested)
            config_path = root / "data" / "configs" / f"{profession['slug']}_hh_requests.json"
            generated = build_profession_config(catalog, profession["slug"], config_path, root)
            generated["source"] = {
                "type": "hh_requests",
                "queries": profession["queries"],
                "relevance_terms": list(
                    dict.fromkeys(
                        [
                            profession["name"],
                            *profession.get("aliases", []),
                            *profession["queries"],
                        ]
                    )
                ),
                "min_title_match_ratio": 0.75,
                "areas": [area],
                "period_days": period_days,
                "per_page": 20,
                "max_pages": max_pages,
                "max_vacancies": max_vacancies,
                "timeout_seconds": 30,
                "retries": 2,
                "request_interval_seconds": 3.0,
                "detail_interval_seconds": 1.0,
                "nodes_path": str(
                    (root / "dictionaries" / "canonical_nodes.json").resolve()
                ),
            }
            write_json(config_path, generated)
            job = jobs.start(
                "сбор вакансий с HH.ru",
                lambda progress: run_pipeline(
                    config_path,
                    runs_root,
                    progress_callback=progress,
                ),
            )
            self._send_json(HTTPStatus.ACCEPTED, job)

        def _run_public_search(self, payload: dict[str, Any]) -> None:
            requested = str(payload.get("profession", "")).strip()
            period_days = int(payload.get("period_days", 30))
            max_pages = int(payload.get("max_pages", 2))
            if not 1 <= period_days <= 3650:
                raise ValueError("Период должен быть от 1 до 3650 дней.")
            if not 1 <= max_pages <= 10:
                raise ValueError("На странице можно выбрать от 1 до 10 страниц.")
            catalog = load_profession_catalog(catalog_path)
            profession, _, _ = resolve_profession(catalog, requested)
            config_path = root / "data" / "configs" / f"{profession['slug']}_public_search.json"
            generated = build_profession_config(catalog, profession["slug"], config_path, root)
            generated["source"] = {
                "type": "trudvsem",
                "queries": profession["queries"],
                "region_codes": [],
                "period_days": period_days,
                "per_page": 100,
                "max_pages": max_pages,
                "retries": 3,
                "timeout_seconds": 30,
                "request_interval_seconds": 0.3,
                "user_agent": "ProfessionalGraphs/0.9 (mlprofessionalgraphs@gmail.com)",
                "include_inactive": False,
            }
            write_json(config_path, generated)
            job = jobs.start(
                "сбор вакансий с портала «Работа России»",
                lambda progress: run_pipeline(
                    config_path,
                    runs_root,
                    progress_callback=progress,
                ),
            )
            self._send_json(HTTPStatus.ACCEPTED, job)

        def _validate_run(self, payload: dict[str, Any]) -> None:
            requested = str(payload.get("run_directory", "")).strip()
            if requested:
                run_path = Path(requested).resolve()
                if not run_path.is_relative_to(runs_root.resolve()):
                    raise ValueError("Проверять можно только папки внутри data/runs.")
            else:
                run_path = _latest_run_path(runs_root)
                if run_path is None:
                    raise ValueError("В data/runs пока нет запусков.")
            self._send_json(HTTPStatus.OK, validate_run_directory(run_path))

        def _serve_run_file(self, relative: str, root_path: Path) -> None:
            target = (root_path / unquote(relative)).resolve()
            allowed_files = {"review_report.html", "validation_report.json"}
            if not target.is_relative_to(root_path.resolve()) or target.name not in allowed_files or not target.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"status": "error", "message": "Файл не найден."})
                return
            content_type = "text/html; charset=utf-8" if target.suffix == ".html" else "application/json; charset=utf-8"
            self._send_bytes(HTTPStatus.OK, target.read_bytes(), content_type)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_BODY_SIZE:
                raise ValueError("Слишком большой запрос.")
            if length == 0:
                return {}
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Тело запроса должно быть JSON-объектом.")
            return value

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            self._send_bytes(status, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8")

        def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            print(f"WEB {self.address_string()} {format % args}")

    return Handler


def _status(root: Path, runs_root: Path) -> dict[str, Any]:
    return {
        "status": "ok",
        "project_root": str(root),
        "hh_html_ready": True,
        "public_search_ready": True,
        "runs": len(_list_runs(runs_root)),
        "storage": "json_files",
    }


def _list_runs(runs_root: Path) -> list[dict[str, Any]]:
    if not runs_root.is_dir():
        return []
    result = []
    for directory in sorted((item for item in runs_root.iterdir() if item.is_dir()), reverse=True):
        report_path = directory / "output" / "validation_report.json"
        status = "unknown"
        if report_path.is_file():
            try:
                status = str(json.loads(report_path.read_text(encoding="utf-8")).get("status", "unknown"))
            except (OSError, json.JSONDecodeError):
                status = "invalid_report"
        result.append(
            {
                "run_id": directory.name,
                "status": status,
                "review_url": f"/runs/{directory.name}/review_report.html" if (directory / "review_report.html").is_file() else None,
            }
        )
    return result


def _latest_run_path(runs_root: Path) -> Path | None:
    if not runs_root.is_dir():
        return None
    directories = [item for item in runs_root.iterdir() if item.is_dir()]
    return max(directories, key=lambda item: item.stat().st_mtime_ns) if directories else None


PAGE = r'''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Professional Graphs — сбор вакансий</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      background: #f3f6fb;
      color: #152238;
      --blue: #2357d8;
      --blue-dark: #173d9c;
      --green: #08785c;
      --amber: #9a5a00;
      --border: #dbe3ef;
      --muted: #60708a;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: radial-gradient(circle at top right, #e6eeff 0, transparent 34%), #f3f6fb; }
    main { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 42px 0 64px; }
    h1, h2, h3, p { margin-top: 0; }
    h1 { margin-bottom: 10px; font-size: clamp(32px, 5vw, 52px); letter-spacing: -.035em; }
    h2 { margin-bottom: 8px; font-size: 22px; }
    h3 { margin-bottom: 8px; font-size: 20px; }
    .hero { margin-bottom: 26px; }
    .eyebrow { margin-bottom: 9px; color: var(--blue); font-size: 13px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
    .lead { max-width: 720px; margin-bottom: 18px; color: var(--muted); font-size: 17px; line-height: 1.6; }
    .status { display: flex; gap: 9px; flex-wrap: wrap; }
    .pill { display: inline-flex; align-items: center; gap: 7px; padding: 7px 11px; border: 1px solid #cdd9ee; border-radius: 999px; background: rgba(255,255,255,.8); color: #40516d; font-size: 13px; font-weight: 700; }
    .pill::before { width: 7px; height: 7px; border-radius: 50%; background: #21a179; content: ""; }
    .card { min-width: 0; padding: 22px; border: 1px solid var(--border); border-radius: 18px; background: rgba(255,255,255,.94); box-shadow: 0 12px 32px rgba(42,63,99,.07); }
    .profession { display: grid; grid-template-columns: 1fr minmax(260px, 420px); align-items: center; gap: 24px; margin-bottom: 18px; }
    .profession p, .source-card > p, .result-copy { color: var(--muted); line-height: 1.55; }
    .sources { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-bottom: 18px; }
    .source-card { position: relative; overflow: hidden; }
    .source-card::before { position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--blue); content: ""; }
    .source-card.public::before { background: var(--green); }
    .source-label { display: inline-block; margin-bottom: 14px; padding: 5px 9px; border-radius: 7px; background: #eaf0ff; color: var(--blue-dark); font-size: 12px; font-weight: 800; }
    .public .source-label { background: #e4f5ef; color: #08654f; }
    .form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .field.full { grid-column: 1 / -1; }
    label { display: block; margin-bottom: 6px; color: #34435d; font-size: 13px; font-weight: 750; }
    select, input, button { width: 100%; min-height: 44px; border-radius: 10px; font: inherit; }
    select, input { padding: 9px 11px; border: 1px solid #b9c6d9; background: #fff; color: #17233a; }
    select:focus, input:focus { outline: 3px solid rgba(35,87,216,.15); border-color: var(--blue); }
    button { margin-top: 16px; padding: 10px 14px; border: 0; background: var(--blue); color: white; font-weight: 800; cursor: pointer; transition: transform .14s ease, background .14s ease; }
    button:hover:not(:disabled) { transform: translateY(-1px); background: var(--blue-dark); }
    button:disabled { cursor: wait; opacity: .55; }
    .public button { background: var(--green); }
    .secondary { width: auto; min-width: 220px; margin: 0; background: #43536c; }
    .result-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 16px; }
    .result-state { padding: 18px; border: 1px dashed #bdc9da; border-radius: 13px; background: #f8faff; color: #4b5c77; line-height: 1.55; }
    .result-state.busy { border-style: solid; border-color: #b9c9ef; background: #edf3ff; color: #254b9f; }
    .result-state.success { border-style: solid; border-color: #a9d9c9; background: #ecf8f4; color: #17664f; }
    .result-state.warning { border-style: solid; border-color: #e8c57f; background: #fff8e8; color: #7c4a00; }
    .result-state.error { border-style: solid; border-color: #efb7b7; background: #fff0f0; color: #9c2f2f; }
    .progress-panel { margin-bottom: 14px; padding: 16px 18px; border: 1px solid #b9c9ef; border-radius: 13px; background: #edf3ff; }
    .progress-panel[hidden] { display: none; }
    .progress-head { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 10px; color: #254b9f; }
    .progress-stage { font-weight: 800; }
    .progress-percent { font-size: 20px; font-variant-numeric: tabular-nums; }
    .progress-track { height: 14px; overflow: hidden; border-radius: 999px; background: #d8e3fa; box-shadow: inset 0 1px 2px rgba(23,61,156,.12); }
    .progress-fill { width: 0; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #2357d8, #38a4ff); transition: width .35s ease; }
    .progress-message { margin: 10px 0 0; color: #405d95; font-size: 14px; line-height: 1.45; }
    .result-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
    .result-link { display: none; padding: 9px 13px; border-radius: 9px; background: #17233a; color: white; font-weight: 750; text-decoration: none; }
    details { margin-top: 14px; }
    summary { color: #53647e; font-weight: 700; cursor: pointer; }
    pre { max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; padding: 15px; border-radius: 11px; background: #111827; color: #dce8ff; font: 12px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; }
    @media (max-width: 780px) {
      main { width: min(100% - 24px, 1120px); padding-top: 28px; }
      .profession, .sources { grid-template-columns: 1fr; }
      .result-head { align-items: stretch; flex-direction: column; }
      .secondary { width: 100%; }
    }
    @media (max-width: 480px) { .form-grid { grid-template-columns: 1fr; } .field.full { grid-column: auto; } }
    @media (prefers-reduced-motion: reduce) { .progress-fill { transition: none; } }
  </style>
</head>
<body>
  <main>
    <header class="hero">
      <p class="eyebrow">Локальный сервис</p>
      <h1>Professional Graphs</h1>
      <p class="lead">Соберите реальные вакансии из одного из двух источников. Сервис выделит навыки, определит грейды и построит профессиональные графы Junior, Middle и Senior.</p>
      <div class="status" id="status" aria-label="Состояние сервиса"></div>
    </header>

    <section class="card profession">
      <div>
        <h2>1. Выберите профессию</h2>
        <p>Одна профессия применяется к поисковым фразам, фильтрации вакансий и итоговым графам.</p>
      </div>
      <div>
        <label for="profession">Профессия</label>
        <select id="profession" aria-label="Профессия"></select>
      </div>
    </section>

    <div class="sources">
      <section class="card source-card hh">
        <span class="source-label">requests + BeautifulSoup</span>
        <h2>2A. Вакансии HH.ru</h2>
        <p>Автоматически разбирает публичную HTML-выдачу и структурированные данные JobPosting. API-ключ не нужен; при CAPTCHA сбор корректно остановится.</p>
        <div class="form-grid">
          <div class="field">
            <label for="hh-period">Период, дней</label>
            <input id="hh-period" type="number" min="1" max="3650" value="30">
          </div>
          <div class="field">
            <label for="hh-pages">Страниц × 20 ссылок</label>
            <input id="hh-pages" type="number" min="1" max="10" value="3">
          </div>
          <div class="field">
            <label for="hh-limit">Лимит вакансий</label>
            <input id="hh-limit" type="number" min="1" max="500" value="50">
          </div>
          <div class="field">
            <label for="hh-area">Регион HH</label>
            <select id="hh-area">
              <option value="1">Москва</option>
              <option value="2">Санкт-Петербург</option>
              <option value="113">Россия</option>
            </select>
          </div>
        </div>
        <button class="run-button" onclick="runHHHtml()">Собрать вакансии с HH.ru</button>
      </section>

      <section class="card source-card public">
        <span class="source-label">Открытый государственный API</span>
        <h2>2B. Вакансии «Работа России»</h2>
        <p>Получает вакансии через открытый API портала «Работа России». Источник не требует регистрации и подходит как стабильный запасной вариант.</p>
        <div class="form-grid">
          <div class="field">
            <label for="public-period">Период, дней</label>
            <input id="public-period" type="number" min="1" max="3650" value="30">
          </div>
          <div class="field">
            <label for="public-pages">Страниц × 100 вакансий</label>
            <input id="public-pages" type="number" min="1" max="10" value="2">
          </div>
        </div>
        <button class="run-button" onclick="runPublicSearch()">Собрать с «Работы России»</button>
      </section>
    </div>

    <section class="card result">
      <div class="result-head">
        <div>
          <h2>3. Результат</h2>
          <p class="result-copy">Здесь появится статус сбора и ссылка на читаемый отчёт последнего запуска.</p>
        </div>
        <button class="secondary run-button" onclick="validateRun()">Проверить последний запуск</button>
      </div>
      <div id="progress-panel" class="progress-panel" hidden>
        <div class="progress-head">
          <span id="progress-stage" class="progress-stage">Подготовка</span>
          <strong id="progress-percent" class="progress-percent">0%</strong>
        </div>
        <div id="progress-track" class="progress-track" role="progressbar" aria-label="Прогресс обработки" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
          <div id="progress-fill" class="progress-fill"></div>
        </div>
        <p id="progress-message" class="progress-message">Создаём задание…</p>
      </div>
      <div id="result-state" class="result-state" aria-live="polite">Выберите источник и запустите сбор вакансий.</div>
      <div class="result-actions">
        <a id="report-link" class="result-link" target="_blank" rel="noopener">Открыть отчёт</a>
      </div>
      <details id="technical-details">
        <summary>Технические данные</summary>
        <pre id="output">Состояние загружается...</pre>
      </details>
    </section>
  </main>

  <script>
    const output = document.getElementById('output');
    const resultState = document.getElementById('result-state');
    const reportLink = document.getElementById('report-link');
    const progressPanel = document.getElementById('progress-panel');
    const progressTrack = document.getElementById('progress-track');
    const progressFill = document.getElementById('progress-fill');
    const progressPercent = document.getElementById('progress-percent');
    const progressStage = document.getElementById('progress-stage');
    const progressMessage = document.getElementById('progress-message');
    const buttons = () => document.querySelectorAll('.run-button');
    const chosen = () => document.getElementById('profession').value;

    function setBusy(busy, message = '') {
      buttons().forEach(button => button.disabled = busy);
      if (busy) {
        resultState.className = 'result-state busy';
        resultState.textContent = message || 'Сбор запущен. Это может занять несколько минут…';
        reportLink.style.display = 'none';
      }
    }

    function showProgress(data) {
      const progress = Math.max(0, Math.min(Number(data.progress || 0), 100));
      progressPanel.hidden = false;
      progressFill.style.width = `${progress}%`;
      progressPercent.textContent = `${Math.round(progress)}%`;
      progressStage.textContent = data.stage || 'Обработка';
      progressMessage.textContent = data.message || 'Выполняем операцию…';
      progressTrack.setAttribute('aria-valuenow', String(Math.round(progress)));
    }

    function errorMessage(data) {
      if (data.message) return data.message;
      const graphError = Object.values(data.graph_issues || {}).flat().find(issue => issue.severity === 'error');
      const productError = (data.product_issues || []).find(issue => issue.severity === 'error');
      return (graphError || productError || {}).message || 'Операция завершилась с ошибкой.';
    }

    function renderResult(data, completionMessage = '') {
      const runDirectory = data.run_directory || data.run_dir;
      const validationWarning = data.status === 'failed' && Boolean(runDirectory);
      const ok = data.status !== 'error' && !validationWarning;
      resultState.className = `result-state ${validationWarning ? 'warning' : (ok ? 'success' : 'error')}`;
      if (validationWarning) {
        const collected = data.vacancies_collected
          ? ` по ${data.vacancies_collected} вакансиям`
          : '';
        resultState.textContent = completionMessage || `Отчёт построен${collected}, но проверка нашла замечания. Его можно открыть и изучить.`;
      } else {
        resultState.textContent = ok
          ? (completionMessage || `Операция завершена успешно${data.vacancies_collected ? `: обработано вакансий — ${data.vacancies_collected}.` : '.'}`)
          : errorMessage(data);
      }
      output.textContent = JSON.stringify(data, null, 2);
      if (runDirectory) {
        const runId = runDirectory.replaceAll('\\', '/').split('/').filter(Boolean).pop();
        reportLink.href = `/runs/${encodeURIComponent(runId)}/review_report.html`;
        reportLink.style.display = 'inline-flex';
      } else {
        reportLink.style.display = 'none';
      }
    }

    const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

    async function pollJob(jobId) {
      while (true) {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
        const job = await response.json();
        if (!response.ok) throw new Error(job.message || `HTTP ${response.status}`);
        showProgress(job);
        output.textContent = JSON.stringify(job, null, 2);
        if (job.status === 'error') throw new Error(job.message || 'Сбор завершился с ошибкой.');
        if (job.status === 'completed') {
          renderResult(job.result || {status:'error', message:'Сервер не вернул результат.'}, job.message);
          return job.result;
        }
        await wait(700);
      }
    }

    async function startJob(path, body, message) {
      setBusy(true, message);
      showProgress({progress:0, stage:'Подготовка', message:'Создаём задание…'});
      try {
        const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        const job = await response.json();
        if (!response.ok) throw new Error(job.message || `HTTP ${response.status}`);
        if (!job.job_id) throw new Error('Сервер не вернул идентификатор задания.');
        showProgress(job);
        return await pollJob(job.job_id);
      } catch (error) {
        const data = {status:'error', message:String(error.message || error)};
        renderResult(data);
        return data;
      } finally {
        setBusy(false);
      }
    }

    async function post(path, body, message) {
      setBusy(true, message);
      progressPanel.hidden = true;
      try {
        const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || `HTTP ${response.status}`);
        renderResult(data);
        return data;
      } catch (error) {
        const data = {status:'error', message:String(error.message || error)};
        renderResult(data);
        return data;
      } finally {
        setBusy(false);
      }
    }

    async function load() {
      const [statusResponse, professionsResponse] = await Promise.all([
        fetch('/api/status'), fetch('/api/professions')
      ]);
      const status = await statusResponse.json();
      const professions = await professionsResponse.json();
      const statusRoot = document.getElementById('status');
      [`HH HTML-парсер готов`, `«Работа России» готова`, `Запусков: ${status.runs}`].forEach(text => {
        const pill = document.createElement('span');
        pill.className = 'pill';
        pill.textContent = text;
        statusRoot.appendChild(pill);
      });
      const select = document.getElementById('profession');
      professions.items.forEach(profession => {
        const option = document.createElement('option');
        option.value = profession.slug;
        option.textContent = profession.name;
        select.appendChild(option);
      });
      output.textContent = JSON.stringify(status, null, 2);
    }

    const runHHHtml = () => startJob('/api/run/hh-html', {
      profession: chosen(),
      period_days: Number(document.getElementById('hh-period').value),
      max_pages: Number(document.getElementById('hh-pages').value),
      max_vacancies: Number(document.getElementById('hh-limit').value),
      area: document.getElementById('hh-area').value
    }, 'Собираем и фильтруем вакансии HH.ru…');

    const runPublicSearch = () => startJob('/api/run/public-search', {
      profession: chosen(),
      period_days: Number(document.getElementById('public-period').value),
      max_pages: Number(document.getElementById('public-pages').value)
    }, 'Получаем вакансии с портала «Работа России»…');

    const validateRun = () => post('/api/run/validate', {}, 'Проверяем файлы последнего запуска…');
    load().catch(error => renderResult({status:'error', message:String(error)}));
  </script>
</body>
</html>'''
