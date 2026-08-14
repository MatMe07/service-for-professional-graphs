from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import re
from typing import Any
from dataclasses import replace
from datetime import datetime, timezone

from ..models import CollectionResult
from .base import Collector
from .file import _deduplicate, _vacancy_from_payload


class HHCollectorError(RuntimeError):
    pass


class HHNotFoundError(HHCollectorError):
    pass


class HHCollector(Collector):
    """Minimal HH.ru collector using public API endpoints.

    Authentication is optional for public vacancy data. If HH_API_TOKEN is set,
    it is sent as a Bearer token. CAPTCHA and access errors are never bypassed.
    """

    def __init__(self, source_config: dict[str, Any]) -> None:
        self.host = str(source_config.get("host", "hh.ru"))
        self.queries = [str(value) for value in source_config.get("queries", []) if str(value).strip()]
        self.areas = [str(value) for value in source_config.get("areas", []) if str(value).strip()] or [""]
        self.period_days = int(source_config.get("period_days", 30))
        self.max_pages = int(source_config.get("max_pages", 1))
        self.per_page = min(int(source_config.get("per_page", 20)), 100)
        self.timeout = float(source_config.get("timeout_seconds", 30))
        self.retries = int(source_config.get("retries", 3))
        self.user_agent = str(source_config.get("user_agent", "ProfessionalGraphService/0.6 (contact@example.com)"))
        self.user_agent_env = str(source_config.get("user_agent_env", "HH_USER_AGENT"))
        environment_user_agent = os.getenv(self.user_agent_env, "").strip()
        if environment_user_agent:
            self.user_agent = environment_user_agent
        self.token_env = str(source_config.get("token_env", "HH_API_TOKEN"))
        if not self.queries:
            raise HHCollectorError("Для HH-сборщика нужен хотя бы один source.queries.")
        if self.max_pages < 1 or self.per_page < 1:
            raise HHCollectorError("max_pages и per_page должны быть положительными.")
        if not 1 <= self.period_days <= 30:
            raise HHCollectorError("period_days для HH должен быть от 1 до 30.")
        if self.max_pages * self.per_page > 2000:
            raise HHCollectorError("Глубина одной поисковой выдачи HH не должна превышать 2000 результатов.")

    @property
    def live_contact_ready(self) -> bool:
        lowered = self.user_agent.lower()
        email_match = re.search(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}", lowered)
        return bool(
            email_match
            and "example.com" not in lowered
            and "replace-with" not in lowered
        )

    def validate_live_contact(self) -> None:
        if not self.live_contact_ready:
            raise HHCollectorError(
                f"Для реального запроса HH укажите контактный HH-User-Agent через {self.user_agent_env}. "
                "Пример: ProfessionalGraphService/0.6 (project-email@domain.ru)."
            )

    def collect(self) -> CollectionResult:
        brief_items: dict[str, dict[str, Any]] = {}
        found_by: dict[str, set[str]] = {}
        search_responses: list[dict[str, Any]] = []
        for query_index, query in enumerate(self.queries, start=1):
            for area in self.areas:
                query_id = f"hh:q{query_index:03d}:area:{area or 'all'}"
                for page in range(self.max_pages):
                    params = {
                        "text": query,
                        "period": self.period_days,
                        "page": page,
                        "per_page": self.per_page,
                    }
                    if area:
                        params["area"] = area
                    response = self._get_json("/vacancies", params)
                    search_responses.append(
                        {
                            "query_id": query_id,
                            "query": query,
                            "area": area or None,
                            "page": page,
                            "received_at": datetime.now(timezone.utc).isoformat(),
                            "response": response,
                        }
                    )
                    for item in response.get("items", []):
                        vacancy_id = str(item["id"])
                        brief_items[vacancy_id] = item
                        found_by.setdefault(vacancy_id, set()).add(query_id)
                    if page >= int(response.get("pages", 1)) - 1:
                        break

        vacancies = []
        for vacancy_id in sorted(brief_items):
            try:
                payload = self._get_json(f"/vacancies/{vacancy_id}", {})
            except HHNotFoundError:
                payload = {
                    **brief_items[vacancy_id],
                    "id": vacancy_id,
                    "description": "",
                    "status": "unavailable",
                    "collection_note": "Detail endpoint returned 404 during collection",
                }
            vacancy = _vacancy_from_payload(payload, source="hh")
            vacancies.append(replace(vacancy, query_ids=tuple(sorted(found_by.get(vacancy_id, set())))))
        unique, duplicates = _deduplicate(vacancies)
        return CollectionResult(
            vacancies=unique,
            search_responses=search_responses,
            duplicate_sightings=duplicates,
        )

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self.validate_live_contact()
        params = {"host": self.host, **params}
        url = f"https://api.hh.ru{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"User-Agent": self.user_agent, "HH-User-Agent": self.user_agent}
        token = os.getenv(self.token_env, "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        for attempt in range(self.retries):
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code in {401, 403}:
                    try:
                        error_types = {
                            str(item.get("type", ""))
                            for item in json.loads(body).get("errors", [])
                            if isinstance(item, dict)
                        }
                    except (json.JSONDecodeError, AttributeError):
                        error_types = set()
                    if any("captcha" in value for value in error_types):
                        message = "HH запросил CAPTCHA; автоматический обход запрещён."
                    elif not token:
                        message = (
                            "Анонимный запрос HH отклонён. Нужен токен приложения в переменной "
                            f"{self.token_env}."
                        )
                    else:
                        message = "HH отклонил авторизованный запрос; проверьте токен и права приложения."
                    raise HHCollectorError(f"{message} Код {exc.code}, ответ: {body}") from exc
                if exc.code == 404:
                    raise HHNotFoundError(f"Объект HH не найден: {url}") from exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt == self.retries - 1:
                    raise HHCollectorError(f"Ошибка HH API {exc.code}: {body}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == self.retries - 1:
                    raise HHCollectorError(f"Не удалось выполнить запрос HH API: {exc}") from exc
            time.sleep(2**attempt)
        raise HHCollectorError("HH API request failed")
