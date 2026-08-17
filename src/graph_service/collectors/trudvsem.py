from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import CollectionResult, Vacancy
from .base import Collector
from .file import _deduplicate, _vacancy_from_payload


class TrudvsemCollectorError(RuntimeError):
    pass


class TrudvsemCollector(Collector):
    """Automatic collector for the official public API of «Работа России»."""

    def __init__(self, source_config: dict[str, Any]) -> None:
        self.base_url = str(source_config.get("base_url", "https://opendata.trudvsem.ru/api/v1/vacancies")).rstrip("/")
        self.queries = [str(value).strip() for value in source_config.get("queries", []) if str(value).strip()]
        self.region_codes = [str(value).strip() for value in source_config.get("region_codes", []) if str(value).strip()] or [""]
        self.period_days = int(source_config.get("period_days", 30))
        self.per_page = int(source_config.get("per_page", 100))
        self.max_pages = int(source_config.get("max_pages", 2))
        self.timeout = float(source_config.get("timeout_seconds", 30))
        self.retries = int(source_config.get("retries", 3))
        self.interval = float(source_config.get("request_interval_seconds", 0.3))
        self.user_agent = str(source_config.get("user_agent", "ProfessionalGraphs/0.9 (mlprofessionalgraphs@gmail.com)"))
        if not self.queries:
            raise TrudvsemCollectorError("Для автоматического поиска нужен хотя бы один source.queries.")
        if not 1 <= self.period_days <= 3650:
            raise TrudvsemCollectorError("period_days должен быть от 1 до 3650.")
        if not 1 <= self.per_page <= 100:
            raise TrudvsemCollectorError("per_page должен быть от 1 до 100.")
        if not 1 <= self.max_pages <= 100:
            raise TrudvsemCollectorError("max_pages должен быть от 1 до 100.")
        if not 0 <= self.interval <= 30:
            raise TrudvsemCollectorError("request_interval_seconds должен быть от 0 до 30.")

    def collect(self) -> CollectionResult:
        vacancies: list[Vacancy] = []
        search_responses: list[dict[str, Any]] = []
        modified_from = (datetime.now(timezone.utc) - timedelta(days=self.period_days)).isoformat(timespec="seconds")
        request_number = 0
        for query_index, query in enumerate(self.queries, start=1):
            for region_code in self.region_codes:
                path = f"/region/{urllib.parse.quote(region_code, safe='')}" if region_code else ""
                query_id = f"trudvsem:q{query_index:03d}:region:{region_code or 'all'}"
                for page in range(self.max_pages):
                    if request_number:
                        time.sleep(self.interval)
                    request_number += 1
                    params = {
                        "text": query,
                        "modifiedFrom": modified_from,
                        "limit": self.per_page,
                        "offset": page * self.per_page,
                    }
                    response = self._get_json(path, params)
                    results = response.get("results", {})
                    wrappers = results.get("vacancies", []) if isinstance(results, dict) else []
                    if not isinstance(wrappers, list):
                        raise TrudvsemCollectorError("API «Работа России» вернул неожиданный формат списка вакансий.")
                    search_responses.append(
                        {
                            "query_id": query_id,
                            "query": query,
                            "region_code": region_code or None,
                            "page": page,
                            "received_at": datetime.now(timezone.utc).isoformat(),
                            "response": response,
                            "source_attribution": "Работа России — https://trudvsem.ru",
                        }
                    )
                    for wrapper in wrappers:
                        raw = wrapper.get("vacancy") if isinstance(wrapper, dict) else None
                        if isinstance(raw, dict):
                            vacancies.append(_normalize_vacancy(raw, query_id))
                    meta = response.get("meta", {})
                    total = _as_int(meta.get("total")) if isinstance(meta, dict) else None
                    if len(wrappers) < self.per_page or (total is not None and (page + 1) * self.per_page >= total):
                        break
        unique, duplicates = _deduplicate(vacancies)
        return CollectionResult(vacancies=unique, search_responses=search_responses, duplicate_sightings=duplicates)

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        for attempt in range(self.retries):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict) or str(payload.get("status")) != "200":
                    raise TrudvsemCollectorError(f"API «Работа России» вернул ошибку: {payload}")
                return payload
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code not in {429, 500, 502, 503, 504} or attempt == self.retries - 1:
                    raise TrudvsemCollectorError(f"Ошибка API «Работа России» HTTP {exc.code}: {body}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt == self.retries - 1:
                    raise TrudvsemCollectorError(f"Не удалось получить вакансии из «Работы России»: {exc}") from exc
            time.sleep(2**attempt)
        raise TrudvsemCollectorError("Не удалось получить вакансии из «Работы России».")


def _normalize_vacancy(raw: dict[str, Any], query_id: str) -> Vacancy:
    requirement = raw.get("requirement") if isinstance(raw.get("requirement"), dict) else {}
    experience_years = _as_int(requirement.get("experience"))
    payload = {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("job-name") or raw.get("vacancy_name") or ""),
        "description": str(raw.get("qualification") or ""),
        "responsibilities": str(raw.get("duty") or ""),
        "requirements": str(raw.get("requirements") or ""),
        "employer": raw.get("company") if isinstance(raw.get("company"), dict) else {"name": ""},
        "area": raw.get("region") if isinstance(raw.get("region"), dict) else {"name": ""},
        "published_at": str(raw.get("creation-date") or raw.get("date_modify") or ""),
        "alternate_url": str(raw.get("vac_url") or ""),
        "status": "active",
        "query_ids": [query_id],
        "experience": {"id": _experience_id(experience_years), "name": f"{experience_years} лет" if experience_years is not None else ""},
        "salary": {"from": raw.get("salary_min"), "to": raw.get("salary_max"), "currency": "RUR", "gross": None},
        "key_skills": raw.get("skills", []),
    }
    vacancy = _vacancy_from_payload(payload, source="trudvsem", default_query_id=query_id)
    return replace(vacancy, raw=raw)


def _experience_id(years: int | None) -> str:
    if years is None:
        return ""
    if years <= 0:
        return "noExperience"
    if years <= 2:
        return "between1And3"
    if years <= 5:
        return "between3And6"
    return "moreThan6"


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
