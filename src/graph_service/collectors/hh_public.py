from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

from ..models import CollectionResult, Vacancy
from .base import Collector
from .file import _deduplicate, _vacancy_from_payload


HH_PUBLIC_HOSTS = {"hh.ru", "www.hh.ru"}
VACANCY_PATH_RE = re.compile(r"^/vacancy/(?P<id>\d+)/?$")
EXPERIENCE_IDS = {
    "нет опыта": "noExperience",
    "1-3 года": "between1And3",
    "3-6 лет": "between3And6",
    "более 6 лет": "moreThan6",
}


class HHPublicPageError(ValueError):
    """Public HH page could not be read without bypassing access restrictions."""


class _VacancyPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_json_ld = False
        self._json_buffer: list[str] = []
        self.job_postings: list[dict[str, Any]] = []
        self.captures: list[dict[str, Any]] = []
        self.values: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        for capture in self.captures:
            if capture["tag"] == tag:
                capture["same_tag_depth"] += 1
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self._in_json_ld = True
            self._json_buffer = []
        qa = attributes.get("data-qa")
        if qa in {"vacancy-title", "vacancy-experience", "vacancy-salary", "vacancy-company-name"}:
            self.captures.append({"qa": qa, "tag": tag, "same_tag_depth": 0, "parts": []})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_buffer.append(data)
        for capture in self.captures:
            capture["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            try:
                parsed = json.loads("".join(self._json_buffer))
            except json.JSONDecodeError:
                parsed = None
            self.job_postings.extend(_find_job_postings(parsed))
        still_open: list[dict[str, Any]] = []
        for capture in self.captures:
            if capture["tag"] == tag and int(capture["same_tag_depth"]) == 0:
                value = " ".join("".join(capture["parts"]).split())
                if value:
                    self.values.setdefault(str(capture["qa"]), []).append(value)
            else:
                if capture["tag"] == tag:
                    capture["same_tag_depth"] -= 1
                still_open.append(capture)
        self.captures = still_open


class HHPublicPageCollector(Collector):
    """Import explicitly supplied public HH vacancy pages without OAuth.

    The collector never searches HH pages, follows advertising redirects or bypasses
    CAPTCHA. A person supplies direct ``https://hh.ru/vacancy/<id>`` links.
    """

    def __init__(self, source_config: dict[str, Any]) -> None:
        supplied = source_config.get("urls", [])
        if isinstance(supplied, str):
            supplied = supplied.splitlines()
        if not isinstance(supplied, list):
            raise HHPublicPageError("source.urls должен быть списком прямых ссылок на вакансии HH.")
        self.urls = list(dict.fromkeys(normalize_public_vacancy_url(str(value)) for value in supplied if str(value).strip()))
        if not self.urls:
            raise HHPublicPageError("Добавьте хотя бы одну прямую ссылку вида https://hh.ru/vacancy/123456.")
        if len(self.urls) > 100:
            raise HHPublicPageError("За один ручной запуск разрешено не более 100 публичных ссылок.")
        self.timeout = float(source_config.get("timeout_seconds", 30))
        self.retries = int(source_config.get("retries", 2))
        self.interval = float(source_config.get("request_interval_seconds", 1.0))
        contact = str(source_config.get("contact_email", "mlprofessionalgraphs@gmail.com")).strip()
        contact = os.getenv(str(source_config.get("contact_email_env", "HH_CONTACT_EMAIL")), contact).strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact):
            raise HHPublicPageError("Для публичных страниц укажите корректный source.contact_email.")
        self.user_agent = f"Mozilla/5.0 (compatible; ProfessionalGraphs/0.9; +mailto:{contact})"

    def collect(self) -> CollectionResult:
        vacancies: list[Vacancy] = []
        import_items: list[dict[str, Any]] = []
        for index, url in enumerate(self.urls):
            if index:
                time.sleep(self.interval)
            vacancy, metadata = self.fetch_detail(url)
            vacancies.append(vacancy)
            import_items.append(metadata)
        unique, duplicates = _deduplicate(vacancies)
        return CollectionResult(
            vacancies=unique,
            duplicate_sightings=duplicates,
            search_responses=[
                {
                    "query_id": "hh_public_manual_urls",
                    "query": None,
                    "area": None,
                    "page": 0,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "response": {
                        "mode": "manual_public_vacancy_urls",
                        "automatic_search": False,
                        "items": import_items,
                    },
                }
            ],
        )

    def fetch_detail(self, url: str) -> tuple[Vacancy, dict[str, Any]]:
        vacancy_id = public_vacancy_id(url)
        raw_html, final_url = self._get_html(url)
        parser = _VacancyPageParser()
        parser.feed(raw_html)
        if not parser.job_postings:
            raise HHPublicPageError(
                f"На странице {url} не найдено открытое описание JobPosting. Возможно, вакансия закрыта или HH показал проверку доступа."
            )
        posting = parser.job_postings[0]
        payload = _payload_from_public_page(vacancy_id, url, final_url, raw_html, posting, parser.values)
        vacancy = _vacancy_from_payload(payload, source="hh_public", default_query_id="hh_public_manual_urls")
        return vacancy, {
            "vacancy_id": vacancy.vacancy_id,
            "url": url,
            "final_url": final_url,
            "published_at": vacancy.published_at,
        }

    def _get_html(self, url: str) -> tuple[str, str]:
        for attempt in range(self.retries):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    final_url = normalize_public_vacancy_url(response.geturl())
                    content_type = response.headers.get_content_type()
                    if content_type != "text/html":
                        raise HHPublicPageError(f"HH вернул {content_type or 'неизвестный формат'} вместо HTML: {url}")
                    return response.read().decode("utf-8"), final_url
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 403, 429}:
                    raise HHPublicPageError(
                        f"HH ограничил просмотр публичной страницы ({exc.code}). Сбор остановлен; CAPTCHA и ограничения не обходятся."
                    ) from exc
                if exc.code == 404:
                    raise HHPublicPageError(f"Публичная вакансия не найдена или закрыта: {url}") from exc
                if exc.code not in {500, 502, 503, 504} or attempt == self.retries - 1:
                    raise HHPublicPageError(f"Ошибка HH при просмотре страницы: HTTP {exc.code}.") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == self.retries - 1:
                    raise HHPublicPageError(f"Не удалось открыть публичную страницу HH: {exc}") from exc
            time.sleep(2**attempt)
        raise HHPublicPageError("Не удалось прочитать публичную страницу HH.")


def normalize_public_vacancy_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in HH_PUBLIC_HOSTS or parsed.username or parsed.password:
        raise HHPublicPageError("Разрешены только прямые HTTPS-ссылки на hh.ru.")
    match = VACANCY_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise HHPublicPageError("Ссылка должна иметь вид https://hh.ru/vacancy/123456 без рекламного перехода.")
    return f"https://hh.ru/vacancy/{match.group('id')}"


def public_vacancy_id(url: str) -> str:
    match = VACANCY_PATH_RE.fullmatch(urllib.parse.urlsplit(url).path)
    if match is None:
        raise HHPublicPageError("Не удалось определить ID публичной вакансии HH.")
    return match.group("id")


def _find_job_postings(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        result = [value] if value.get("@type") == "JobPosting" else []
        for child in value.values():
            result.extend(_find_job_postings(child))
        return result
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for child in value:
            result.extend(_find_job_postings(child))
        return result
    return []


def _payload_from_public_page(
    vacancy_id: str,
    requested_url: str,
    final_url: str,
    raw_html: str,
    posting: dict[str, Any],
    qa_values: dict[str, list[str]],
) -> dict[str, Any]:
    identifier = posting.get("identifier") if isinstance(posting.get("identifier"), dict) else {}
    identifier_value = str(identifier.get("value") or vacancy_id)
    if identifier_value != vacancy_id:
        raise HHPublicPageError("ID в публичной странице не совпадает с ID ссылки.")
    organization = posting.get("hiringOrganization") if isinstance(posting.get("hiringOrganization"), dict) else {}
    location = posting.get("jobLocation") if isinstance(posting.get("jobLocation"), dict) else {}
    address = location.get("address") if isinstance(location.get("address"), dict) else {}
    experience_text = _first_value(qa_values, "vacancy-experience")
    salary_text = _first_value(qa_values, "vacancy-salary")
    salary = _parse_salary(salary_text)
    return {
        "id": vacancy_id,
        "name": str(posting.get("title") or _first_value(qa_values, "vacancy-title")),
        "description": str(posting.get("description") or ""),
        "employer": {"name": str(organization.get("name") or _first_value(qa_values, "vacancy-company-name"))},
        "area": {"name": str(address.get("addressLocality") or address.get("addressRegion") or "")},
        "published_at": str(posting.get("datePosted") or ""),
        "alternate_url": requested_url,
        "status": "active",
        "experience": {"id": _experience_id(experience_text), "name": experience_text},
        "salary": salary,
        "public_page": {
            "requested_url": requested_url,
            "final_url": final_url,
            "valid_through": posting.get("validThrough"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "automatic_search": False,
            "json_ld": posting,
            "html": raw_html,
        },
    }


def _first_value(values: dict[str, list[str]], key: str) -> str:
    return values.get(key, [""])[0]


def _experience_id(value: str) -> str:
    normalized = value.lower().replace("–", "-").replace("—", "-").strip()
    return EXPERIENCE_IDS.get(normalized, "")


def _parse_salary(value: str) -> dict[str, Any] | None:
    if not value:
        return None
    numbers = [float(item.replace(" ", "").replace("\u00a0", "")) for item in re.findall(r"\d[\d\s\u00a0]*", value)]
    currency = "RUR" if "₽" in value or "руб" in value.lower() else ""
    if not numbers:
        return None
    lowered = value.lower()
    salary_from = numbers[0] if len(numbers) > 1 or "от" in lowered else None
    salary_to = numbers[-1] if len(numbers) > 1 or "до" in lowered else None
    return {"from": salary_from, "to": salary_to, "currency": currency, "gross": None, "text": value}
