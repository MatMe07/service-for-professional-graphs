from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .ai import ai_status
from .collectors import HHCollector
from .config import ConfigError, load_config
from .pipeline import PipelineError, run_pipeline
from .professions import build_profession_config, load_profession_catalog, resolve_profession
from .storage import write_json
from .validation import validate_run_directory


MAX_BODY_SIZE = 1_000_000


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

    class Handler(BaseHTTPRequestHandler):
        server_version = "ProfessionalGraphs/0.9"

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/":
                self._send_bytes(HTTPStatus.OK, PAGE.encode("utf-8"), "text/html; charset=utf-8")
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
            if path.startswith("/runs/"):
                self._serve_run_file(path.removeprefix("/runs/"), runs_root)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"status": "error", "message": "Маршрут не найден."})

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = self._read_json()
                path = urlsplit(self.path).path
                if path == "/api/config/create":
                    self._create_config(payload)
                    return
                if path == "/api/run/demo":
                    report = run_pipeline(
                        root / "examples" / "profession_config.json",
                        runs_root,
                        vacancies_path=root / "examples" / "sample_vacancies.json",
                    )
                    self._send_json(HTTPStatus.OK, report)
                    return
                if path == "/api/run/hh":
                    self._run_hh(payload)
                    return
                if path == "/api/run/hh-public":
                    self._run_hh_public(payload)
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

        def _create_config(self, payload: dict[str, Any]) -> None:
            requested = str(payload.get("profession", "")).strip()
            catalog = load_profession_catalog(catalog_path)
            profession, confidence, matched = resolve_profession(catalog, requested)
            output = root / "data" / "configs" / f"{profession['slug']}.json"
            generated = build_profession_config(catalog, profession["slug"], output, root)
            write_json(output, generated)
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "profession": profession,
                    "matched_input": matched,
                    "match_confidence": confidence,
                    "output": str(output),
                },
            )

        def _run_hh(self, payload: dict[str, Any]) -> None:
            requested = str(payload.get("profession", "")).strip()
            catalog = load_profession_catalog(catalog_path)
            profession, _, _ = resolve_profession(catalog, requested)
            config_path = root / "data" / "configs" / f"{profession['slug']}.json"
            generated = build_profession_config(catalog, profession["slug"], config_path, root)
            write_json(config_path, generated)
            report = run_pipeline(config_path, runs_root)
            self._send_json(HTTPStatus.OK, report)

        def _run_hh_public(self, payload: dict[str, Any]) -> None:
            requested = str(payload.get("profession", "")).strip()
            supplied_urls = payload.get("urls", [])
            if isinstance(supplied_urls, str):
                supplied_urls = supplied_urls.splitlines()
            if not isinstance(supplied_urls, list):
                raise ValueError("Ссылки должны быть списком или строками по одной на строку.")
            urls = list(dict.fromkeys(str(value).strip() for value in supplied_urls if str(value).strip()))
            catalog = load_profession_catalog(catalog_path)
            profession, _, _ = resolve_profession(catalog, requested)
            config_path = root / "data" / "configs" / f"{profession['slug']}_hh_public.json"
            generated = build_profession_config(catalog, profession["slug"], config_path, root)
            generated["source"] = {
                "type": "hh_public_pages",
                "urls": urls,
                "contact_email": "mlprofessionalgraphs@gmail.com",
                "contact_email_env": "HH_CONTACT_EMAIL",
                "timeout_seconds": 30,
                "retries": 2,
                "request_interval_seconds": 1.0,
            }
            write_json(config_path, generated)
            report = run_pipeline(config_path, runs_root)
            self._send_json(HTTPStatus.OK, report)

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
            report = run_pipeline(config_path, runs_root)
            self._send_json(HTTPStatus.OK, report)

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
    config = load_config(root / "examples" / "profession_config.json")
    configured_hh_contact = False
    hh_config_path = root / "examples" / "hh_profession_config.json"
    if hh_config_path.is_file():
        configured_hh_contact = HHCollector(load_config(hh_config_path).source).live_contact_ready
    return {
        "status": "ok",
        "project_root": str(root),
        "hh_user_agent_ready": configured_hh_contact or bool(os.getenv("HH_USER_AGENT", "").strip()),
        "hh_token_ready": bool(os.getenv("HH_API_TOKEN", "").strip()),
        "hh_public_pages_ready": True,
        "public_search_ready": True,
        "ai": ai_status(config.ai),
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
  <title>Professional Graphs</title>
  <style>
    :root { color-scheme: light; font-family: Inter, Arial, sans-serif; background: #f4f7fb; color: #172033; }
    body { max-width: 980px; margin: 0 auto; padding: 32px 20px 60px; box-sizing: border-box; }
    h1 { margin-bottom: 6px; } .lead { color: #536078; margin-top: 0; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    section { min-width: 0; background: white; border: 1px solid #dbe3ef; border-radius: 16px; padding: 18px; box-shadow: 0 8px 24px rgba(38,55,86,.06); }
    label { display:block; font-weight: 600; margin-bottom: 7px; }
    select, input, textarea, button { width: 100%; box-sizing: border-box; border-radius: 9px; padding: 10px 12px; font: inherit; }
    select, input, textarea { border: 1px solid #b9c5d8; margin-bottom: 10px; background: white; }
    textarea { min-height: 116px; resize: vertical; }
    button { border: 0; background: #2457d6; color: white; font-weight: 700; cursor: pointer; margin-top: 6px; }
    button:disabled { cursor: not-allowed; opacity: .48; }
    button.secondary { background: #44546f; } button.warn { background: #a34b13; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #111827; color: #d8e5ff; padding: 16px; border-radius: 12px; min-height: 120px; }
    .status { display:flex; gap:10px; flex-wrap:wrap; margin: 14px 0 20px; }
    .pill { background:#e7eefc; border-radius:999px; padding:6px 10px; font-size:14px; }
    @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } body { padding: 22px 14px 40px; } }
  </style>
</head>
<body>
  <h1>Professional Graphs</h1>
  <p class="lead">Локальный запуск проекта. Секреты в браузере не показываются.</p>
  <div class="status" id="status"></div>
  <div class="grid">
    <section>
      <h2>1. Профессия</h2>
      <label for="profession">Выберите профессию</label>
      <select id="profession"></select>
      <button onclick="createConfig()">Создать настройку</button>
    </section>
    <section>
      <h2>2. Демо без HH</h2>
      <p>Проверяет весь путь на локальных примерах ML-инженера.</p>
      <button class="secondary" onclick="runDemo()">Запустить демо</button>
    </section>
    <section>
      <h2>3. Автосбор без ключа</h2>
      <p>Ищет вакансии автоматически через открытый API «Работа России». HH подключится после одобрения ключа.</p>
      <label for="public-period">Период изменений, дней</label>
      <input id="public-period" type="number" min="1" max="3650" value="30">
      <label for="public-pages">Страниц по 100 вакансий на каждый запрос</label>
      <input id="public-pages" type="number" min="1" max="10" value="2">
      <button onclick="runPublicSearch()">Собрать вакансии автоматически</button>
    </section>
    <section>
      <h2>4. Ручные ссылки HH</h2>
      <p>Вставьте прямые публичные ссылки на вакансии, по одной на строку. Поиск на сайте программа не обходит. Для полного графа подберите вакансии Junior, Middle и Senior.</p>
      <label for="hh-public-urls">Ссылки вида https://hh.ru/vacancy/123456</label>
      <textarea id="hh-public-urls" placeholder="https://hh.ru/vacancy/123456"></textarea>
      <button onclick="runHHPublic()">Собрать по публичным ссылкам</button>
    </section>
    <section>
      <h2>5. HH через API</h2>
      <p>Станет доступен после одобрения приложения и сохранения токена.</p>
      <button id="hh-button" class="warn" onclick="runHH()">Собрать выбранную профессию</button>
    </section>
    <section>
      <h2>6. Проверка результата</h2>
      <p>Проверяет последний запуск, JSON, графы, SVG и связанные файлы.</p>
      <button class="secondary" onclick="validateRun()">Проверить последний запуск</button>
    </section>
  </div>
  <h2>Результат действия</h2>
  <pre id="output">Загрузка состояния...</pre>
  <script>
    const output = document.getElementById('output');
    async function api(path, body) {
      output.textContent = 'Выполняется...';
      const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
      const response = await fetch(path, options); const data = await response.json();
      output.textContent = JSON.stringify(data, null, 2); return data;
    }
    async function load() {
      const [status, professions] = await Promise.all([api('/api/status'), fetch('/api/professions').then(r=>r.json())]);
      document.getElementById('status').innerHTML = [
        `HH API-контакт: ${status.hh_user_agent_ready ? 'готов' : 'не задан'}`,
        `HH токен: ${status.hh_token_ready ? 'готов' : 'ожидается'}`,
        `Автосбор без ключа: готов`,
        `Ручной HH: готов`,
        `AI: ${status.ai.ready ? 'готов' : 'выключен'}`,
        `Запусков: ${status.runs}`
      ].map(x=>`<span class="pill">${x}</span>`).join('');
      document.getElementById('hh-button').disabled = !status.hh_token_ready;
      document.getElementById('profession').innerHTML = professions.items.map(p=>`<option value="${p.slug}">${p.name}</option>`).join('');
    }
    const chosen = () => document.getElementById('profession').value;
    const createConfig = () => api('/api/config/create', {profession:chosen()});
    const runDemo = () => api('/api/run/demo', {});
    const runHHPublic = () => api('/api/run/hh-public', {profession:chosen(), urls:document.getElementById('hh-public-urls').value});
    const runPublicSearch = () => api('/api/run/public-search', {profession:chosen(), period_days:Number(document.getElementById('public-period').value), max_pages:Number(document.getElementById('public-pages').value)});
    const runHH = () => api('/api/run/hh', {profession:chosen()});
    const validateRun = () => api('/api/run/validate', {});
    load().catch(error => output.textContent = String(error));
  </script>
</body>
</html>'''
