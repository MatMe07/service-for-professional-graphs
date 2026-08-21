from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag

from ..config import load_node_definitions
from ..models import CollectionResult, Vacancy
from ..parsing.text import clean_html
from .base import Collector
from .file import _deduplicate
from .hh_public import EXPERIENCE_IDS, _find_job_postings

_SEARCH_URL = "https://hh.ru/search/vacancy"
VACANCY_LINK_RE = re.compile(r"^(?:https?://(?:www\.)?hh\.ru)?(/vacancy/\d+)")

RUSSIAN_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def _clean_text(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"[\u00a0\u2009]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


_BULLET_RE = re.compile(r"(?m)^[ \t\u00a0]*(?:[•◦▪▫●○]|[-*–—] +)")


def _strip_bullets(value: str) -> str:
    """Убирает маркеры списков вида «• », «- » в начале строк."""
    if not value:
        return value
    return _BULLET_RE.sub("", value)


def _clean_vacancy_url(url: str) -> str:
    """Сводит ссылку на вакансию к каноническому виду https://hh.ru/vacancy/<id>."""
    if not url:
        return url
    match = VACANCY_LINK_RE.search(url)
    if match:
        return "https://hh.ru" + match.group(1)
    return url


def _job_postings_from_soup(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Извлекает JobPosting dict'ы из JSON-LD скриптов страницы."""
    postings: list[dict[str, Any]] = []
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.string
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        except TypeError:
            continue
        postings.extend(_find_job_postings(data))
    return postings


class HHDescriptionExtractor:
    """Извлекает "Требования" и "Будет плюсом" из HTML описания вакансии."""

    _EMOJI_RE = re.compile(
        "[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u203c-\u2139]"
    )
    _CONNECTIVE_TAILS = {
        "но необязательно",
        "если вы",
        "если у вас есть",
        "приветствуется",
        "бонус",
        "бонусом",
        "преимущество",
        "инициатива",
    }
    REQUIREMENT_RE = re.compile(
        r"(?:"
        r"требования\s+к\s+(?:кандидату|опыту)|"
        r"наши\s+требования|"
        r"(?:ключевые|обязательные|основные|квалификационные|технические|базовые)\s+требован\w+|"
        r"требован\w+|"
        r"наши\s+ожидания\s+(?:к\s+кандидату)?|"
        r"(?:что\s+)?мы\s+(?:от\s+(?:вас|тебя)\s+)?(?:ожида[её]м|жд[её]м(?:иск)?)(?:\s+от\s+(?:кандидат\w+|вас|тебя))?(?:[,:]?\s*что\s+(?:вы|ты))?\b|"
        r"(?:что\s+)?жд[её]м\s+от\s+(?:кандидат\w+|вас|тебя)\b|"
        r"(?:что\s+)?ожида[её]м\s+от\s+(?:кандидат\w+|вас|тебя)|"
        r"что\s+мы\s+(?:ищем|ожидаем)|"
        r"кого\s+мы\s+ищем\b|"
        r"(?:чем|что)\s+(?:для\s+нас\s+)?важно\b|(?:нам|для\s+нас)\s+важно\b|"
        r"(?:именно\s+)?такого\s+кандидат\w+\s+мы\s+ищем\b|"
        r"(?:знание|навыки|умения|background)\s+котор\w+\s+нам\s+(?:важн\w|нужн\w)|"
        r"(?:наш\s+)?\s*идеальный\s+кандидат\b|"
        r"добро\s+пожаловать\s+.*?\s+если\s+(?:есть|у\s+вас\s+есть)|"
        r"необходимые\s+навыки|требуемые\s+навыки|"
        r"навыки\s+(?:и\s+)?опыт\s+кандидата|опыт\s+работы|кандидат\s+должен|"
        r"requirements|qualifications|"
        r"we(?:'re|\s+are)?\s+looking\s+for|what\s+we\s+(?:expect|need)|"
        r"key\s+requirements|must\s+have|skills\s*(?:&|\band\b|\+)?\s*experience"
        r")",
        re.IGNORECASE,
    )
    PLUS_RE = re.compile(
        r"(?:"
        r"буд[еу][тм]?\s+(?:большим|явным|также\s+)?\s*плюсом\b(?:\s*[,:]?\s*(?:если|но))?|"
        r"буд[еу][тм]?\s+преимуществом\b|"
        r"что\s+будет\s+плюсом\b|"
        r"желательно|приятно\s+иметь|приветствуется|дополнительные\s+навыки|бонусом|"
        r"nice\s+to\s+have|\bpreferred\b|good\s+to\s+have|would\s+be\s+a\s+plus"
        r")",
        re.IGNORECASE,
    )
    STOP_RE = re.compile(
        r"(?:"
        r"требования\s+к\s+(?:кандидату|опыту)|"
        r"(?:ключевые|обязательные|основные|квалификационные|технические|базовые)\s+требован\w+|"
        r"требован\w+|"
        r"наши\s+ожидания\s+(?:к\s+кандидату)?|"
        r"(?:что\s+)?мы\s+(?:от\s+(?:вас|тебя)\s+)?(?:ожида[её]м|жд[её]м(?:иск)?)(?:\s+от\s+(?:кандидат\w+|вас|тебя))?(?:[,:]?\s*что\s+(?:вы|ты))?\b|"
        r"(?:что\s+)?жд[её]м\s+от\s+(?:кандидат\w+|вас|тебя)\b|"
        r"(?:что\s+)?ожида[её]м\s+от\s+(?:кандидат\w+|вас|тебя)|"
        r"что\s+мы\s+(?:ищем|ожидаем)|"
        r"(?:чем|что)\s+(?:для\s+нас\s+)?важно\b|(?:нам|для\s+нас)\s+важно\b|"
        r"буд[еу][тм]?\s+(?:большим|явным|также\s+)?\s*плюсом\b(?:\s*[,:]?\s*(?:если|но))?|"
        r"буд[еу][тм]?\s+преимуществом\b|"
        r"желательно|приветствуется|бонусом|"
        r"обязанност\w+|твои\s+задачи|чем\s+предстоит\s+заниматься|"
        r"что\s+нужно\s+делать|что\s+ты\s+будешь\s+делать|задач\w+|"
        r"условия(?:\s+работы)?|(?:что\s+)?мы\s+предлагаем|(?:что\s+)?мы\s+готовы\s+предложить|"
        r"о\s+проекте|о\s+компании|о\s+нас|кто\s+мы|"
        r"что\s+вам\s+может\s+быть\s+интересно|"
        r"requirements|qualifications|we(?:'re|\s+are)?\s+looking\s+for|"
        r"what\s+we\s+(?:expect|need)|must\s+have|nice\s+to\s+have|preferred|"
        r"responsibilities|duties|benefits|about\s+(?:us|the\s+company)"
        r")",
        re.IGNORECASE,
    )

    _HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "p")

    def extract(self, description_html: str | None) -> dict[str, str]:
        """Возвращает {"requirements": str, "plus": str} из HTML описания."""
        if not description_html:
            return {"requirements": "", "plus": ""}
        soup = BeautifulSoup(description_html, "html.parser")
        requirements = self._collect_section(soup, self.REQUIREMENT_RE)
        plus = self._collect_section(soup, self.PLUS_RE)
        if not requirements:
            requirements = self._fallback_lists(soup)
        requirements, plus_items = self._split_inline_plus(requirements, plus)
        requirements = self._split_multi_bullets(requirements)
        plus_items = self._split_multi_bullets(plus_items)
        plus = [p for p in (self._strip_plus_prefix(x) for x in plus_items) if p]
        return {
            "requirements": self._join_items(requirements),
            "plus": self._join_items(plus),
        }

    def _collect_section(
        self, soup: BeautifulSoup, heading_re: re.Pattern[str]
    ) -> list[str]:
        headings: list[Tag] = []
        for node in soup.find_all(self._HEADING_TAGS, recursive=True):
            if not self._is_section_heading(node, heading_re):
                continue
            if any(node in heading.descendants for heading in headings):
                continue
            headings.append(node)
        if not headings:
            return []
        items: list[str] = []
        for index, heading in enumerate(headings):
            tail = self._heading_tail(heading, heading_re)
            if tail:
                items.append(tail)
            next_heading = headings[index + 1] if index + 1 < len(headings) else None
            for following in heading.find_all_next():
                if following in heading.descendants:
                    # вложенный strong/b внутри самого заголовка — не отдельная секция
                    continue
                if next_heading is not None and following is next_heading:
                    break
                if not isinstance(following, Tag):
                    continue
                text = self._node_text(following)
                if not text:
                    continue
                if self._looks_like_heading(text, following.name):
                    break
                if (
                    self.PLUS_RE.match(self._clean_prefix(text))
                    and following.name != "li"
                ):
                    # секция/абзац плюсов, попавший в список требований (напр. "Будет плюсом ...")
                    break
                if (
                    text.startswith(("•", "◦", "▪", "‣", "●"))
                    and self._marker_split(text) <= 1
                ):
                    # одиночный маркер-буллет вне <li> (внутри <p>)
                    items.append(text)
                elif following.name in {"p", "li"}:
                    items.append(text)
        return items

    def _heading_tail(self, heading: Tag, heading_re: re.Pattern[str]) -> str:
        """Хвост текста заголовка после маркера (заголовок и текст в одной строке)."""
        texts = [heading.get_text(" ", strip=True)]
        parent = heading.parent if isinstance(heading.parent, Tag) else None
        if parent is not None and parent.name == "p":
            texts.append(parent.get_text(" ", strip=True))
        for text in texts:
            clean = self._clean_prefix(text)
            match = heading_re.match(clean)
            if match is None:
                continue
            tail = self._rest(clean, match)
            if len(tail) >= 12 and not self._is_connective_tail(tail):
                return tail
        return ""

    def _fallback_lists(self, soup: BeautifulSoup) -> list[str]:
        candidates: list[tuple[list[str], Tag]] = []
        for ul in soup.find_all(["ul", "ol"], recursive=True):
            items = self._list_items(ul)
            if not items:
                continue
            header = self._preceding_header_text(ul)
            if header and self._looks_like_heading(header, "p"):
                continue
            candidates.append((items, ul))
        if not candidates:
            return []
        candidates.sort(key=lambda pair: len(pair[0]), reverse=True)
        return candidates[0][0]

    @staticmethod
    def _preceding_header_text(ul: Tag) -> str:
        node = ul.previous_sibling
        while node is not None:
            if isinstance(node, Tag) and node.get_text(strip=True):
                return node.get_text(" ", strip=True)
            node = node.previous_sibling
        return ""

    @staticmethod
    def _list_items(ul: Tag) -> list[str]:
        lis = ul.find_all("li", recursive=False)
        if not lis:
            lis = [li for li in ul.find_all("li", recursive=True) if not li.find("li")]
        return [
            HHDescriptionExtractor._node_text(li)
            for li in lis
            if HHDescriptionExtractor._node_text(li)
        ]

    @staticmethod
    def _clean_prefix(text: str) -> str:
        value = re.sub(r"\s+", " ", text).strip()
        value = HHDescriptionExtractor._EMOJI_RE.sub("", value)
        value = value.lstrip(" .,;:—–-«\"'()")
        value = value.lstrip()
        return value.strip()

    @staticmethod
    def _rest(text: str, match: re.Match[str]) -> str:
        tail = text[match.end() :]
        tail = HHDescriptionExtractor._EMOJI_RE.sub("", tail)
        tail = tail.lstrip(" .,;:—–-()«\"'")
        return _strip_bullets(tail.strip())

    @staticmethod
    def _is_connective_tail(tail: str) -> bool:
        stripped = tail.strip().strip("(«\"' [").rstrip(")»\"':;,").strip()
        lowered = stripped.lower()
        if lowered in HHDescriptionExtractor._CONNECTIVE_TAILS:
            return True
        if len(stripped.split()) <= 2:
            return True
        return (
            re.match(r"^(но|если|и|а|является|это|будет|иначе|но\s+не)\b", lowered)
            is not None
        )

    @staticmethod
    def _is_section_heading(node: Tag, heading_re: re.Pattern[str]) -> bool:
        """Заголовок — это текст, начинающийся с маркера секции (короткий хвост после)."""
        text = node.get_text(" ", strip=True)
        if not text:
            return False
        clean = HHDescriptionExtractor._clean_prefix(text)
        if not clean:
            return False
        match = heading_re.match(clean)
        if match is None:
            return False
        rest = HHDescriptionExtractor._rest(clean, match)
        if len(rest) <= 16:
            return True
        if node.name in {"p", "strong", "b", "em", "i"} and len(text) <= 200:
            # длинный заголовок с контентом, но сразу за ним список — всё равно секция
            following = node.find_next()
            while following is not None and not isinstance(following, Tag):
                following = following.find_next()
            if isinstance(following, Tag) and following.name in {"ul", "ol"}:
                return True
        if node.name in {"h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i"}:
            return len(text) <= 120
        return False

    @staticmethod
    def _looks_like_heading(text: str, node_name: str | None = None) -> bool:
        """Контент — новый заголовок, если текст начинается с маркера и хвост короткий."""
        if len(text) > 120:
            return False
        clean = HHDescriptionExtractor._clean_prefix(text)
        if not clean:
            return False
        if len(clean) > 120:
            return False
        match = HHDescriptionExtractor.STOP_RE.match(clean)
        if match is None:
            return False
        rest = HHDescriptionExtractor._rest(clean, match)
        if node_name in {"p", "strong", "b", "em", "i"} or (node_name or "").startswith(
            "h"
        ):
            return len(rest) <= 45
        return len(rest) <= 16

    @staticmethod
    def _node_text(node: Tag) -> str:
        return _clean_text(node.get_text(" ", strip=True))

    @staticmethod
    def _marker_split(text: str) -> int:
        return len(re.findall(r"[•●◦▪‣]", text))

    @classmethod
    def _split_multi_bullets(cls, items: list[str]) -> list[str]:
        """Разбивает один <li> с несколькими буллетами ● на отдельные пункты."""
        result: list[str] = []
        for item in items:
            marks = re.findall(r"[•●◦▪‣]", item)
            if len(marks) >= 2:
                parts = [
                    p.strip() for p in re.split(r"\s*[•●◦▪‣]\s*", item) if p.strip()
                ]
                if len(parts) >= 2:
                    result.extend(parts)
                    continue
            result.append(item)
        return result

    @staticmethod
    def _split_inline_plus(
        req_items: list[str], plus_items: list[str]
    ) -> tuple[list[str], list[str]]:
        """Пункты 'Будет плюсом ...', попавшие в требования, переносит в плюсы."""
        kept_req: list[str] = []
        kept_plus: list[str] = list(plus_items)
        for item in req_items:
            clean = HHDescriptionExtractor._clean_prefix(item)
            match = HHDescriptionExtractor.PLUS_RE.match(clean)
            if match is not None:
                rest = clean[match.end() :].lstrip(" :,;—-()")
                if rest:
                    kept_plus.append(rest.strip())
            else:
                kept_req.append(item)
        return kept_req, kept_plus

    @classmethod
    def _strip_plus_prefix(cls, item: str) -> str:
        clean = cls._clean_prefix(item)
        match = cls.PLUS_RE.match(clean)
        if match is None:
            return item
        rest = clean[match.end() :].lstrip(" :,;—-()")
        return rest.strip() if rest else ""

    @staticmethod
    def _join_items(items: list[str]) -> str:
        seen: list[str] = []
        for item in items:
            if not item:
                continue
            item = _strip_bullets(item)
            if not item:
                continue
            if HHDescriptionExtractor._looks_like_heading(item):
                continue
            if item not in seen:
                seen.append(item)
        return "\n".join(seen)


class HHRequestsCollector(Collector):
    """Сбор вакансий HH через requests + BeautifulSoup."""

    def __init__(self, source_config: dict[str, Any]):
        self.queries = [
            str(q) for q in source_config.get("queries", []) if str(q).strip()
        ]
        self.areas = [
            str(a) for a in source_config.get("areas", []) if str(a).strip()
        ] or ["1"]
        self.max_pages = int(source_config.get("max_pages", 1))
        self.per_page = min(max(int(source_config.get("per_page", 20)), 1), 100)
        self.retries = max(int(source_config.get("retries", 2)), 0)
        self.delay = max(float(source_config.get("request_interval_seconds", 3.0)), 0.1)
        self.detail_delay = max(
            float(source_config.get("detail_interval_seconds", 1.0)), 0.0
        )
        self.timeout = float(source_config.get("timeout_seconds", 30))
        self.max_vacancies = int(source_config.get("max_vacancies", 0) or 0)
        # print("-"*20)
        # print(self.max_vacancies)

        self.extractor = HHDescriptionExtractor()
        self.canonical_terms: list[tuple[str, str]] = []
        nodes_path = str(source_config.get("nodes_path", "") or "").strip()
        if nodes_path:
            try:
                _, definitions = load_node_definitions(Path(nodes_path))
                seen: set[str] = set()
                for definition in definitions:
                    for alias in definition.aliases:
                        lower = alias.lower().strip()
                        if not lower or lower in seen:
                            continue
                        seen.add(lower)
                        self.canonical_terms.append((lower, definition.name))
                self.canonical_terms.sort(key=lambda pair: len(pair[0]), reverse=True)
                self._log(
                    f"Загружено канонических терминов: {len(self.canonical_terms)}"
                )
            except Exception as exc:
                self._log(
                    f"Не удалось загрузить canonical_nodes.json ({nodes_path}): {exc}"
                )
        self.session = requests.Session()

        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
        ]
        self.ua_index = 0

        if not self.queries:
            raise ValueError("Нужен хотя бы один search query")

    def get_headers(self) -> dict[str, str]:
        self.ua_index = (self.ua_index + 1) % len(self.user_agents)
        return {
            "User-Agent": self.user_agents[self.ua_index],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "Referer": "https://hh.ru/",
        }

    def collect(self) -> CollectionResult:
        all_vacancies: list[dict[str, Any]] = []
        search_responses: list[dict[str, Any]] = []
        captcha_detected = False

        # Лимит на один запрос
        per_query_limit = self.max_vacancies if self.max_vacancies > 0 else None

        for query_index, query in enumerate(self.queries, start=1):
            query_vacancies: list[dict[str, Any]] = []

            for area in self.areas:
                for page in range(self.max_pages):
                    if page > 0 or query_index > 1:
                        self._sleep(self.delay + random.uniform(0, 2))
                    self._log(f"Запрос: '{query}' | area={area} | page={page}")
                    query_id = f"hh_requests:{query}:area:{area}"

                    try:
                        vacancy_links = self._get_vacancy_links(query, area, page)

                        if vacancy_links is None:
                            captcha_detected = True
                            search_responses.append(
                                self._search_response(
                                    query,
                                    area,
                                    page,
                                    query_id,
                                    status="blocked",
                                    links_found=None,
                                )
                            )
                            break

                        search_responses.append(
                            self._search_response(
                                query,
                                area,
                                page,
                                query_id,
                                links_found=len(vacancy_links),
                            )
                        )

                        if not vacancy_links:
                            self._log(f"Ссылок не найдено на странице {page}")
                            break

                        self._log(f"Найдено {len(vacancy_links)} ссылок")

                        for idx, link in enumerate(vacancy_links):
                            # Проверяем лимит ДЛЯ ТЕКУЩЕГО ЗАПРОСА
                            if (
                                per_query_limit
                                and len(query_vacancies) >= per_query_limit
                            ):
                                self._log(
                                    f"Достигнут лимит {per_query_limit} для запроса '{query}'"
                                )
                                break

                            if idx > 0:
                                self._sleep(self.detail_delay + random.uniform(0, 1))
                            self._log(
                                f"Загрузка вакансии {idx + 1}/{len(vacancy_links)}: {link}"
                            )
                            vacancy_data = self._fetch_vacancy_page(link, query_id)
                            if vacancy_data:
                                query_vacancies.append(vacancy_data)

                        self._log(
                            f"Для запроса '{query}' собрано: {len(query_vacancies)} вакансий"
                        )

                        # Если достигли лимита для этого запроса — переходим к следующему запросу
                        if per_query_limit and len(query_vacancies) >= per_query_limit:
                            self._log(f"Переход к следующему запросу")
                            break

                        if len(vacancy_links) < self.per_page:
                            break

                    except RuntimeError as exc:
                        self._log(f"Ошибка: {exc}")
                        search_responses.append(
                            self._search_response(
                                query,
                                area,
                                page,
                                query_id,
                                status="error",
                                error=str(exc),
                            )
                        )
                        break

                if captcha_detected:
                    break

                # Если для этого запроса достигнут лимит — переходим к следующему
                if per_query_limit and len(query_vacancies) >= per_query_limit:
                    continue

            # Добавляем вакансии этого запроса в общий список
            all_vacancies.extend(query_vacancies)

            if captcha_detected:
                break

        self._log(f"Всего собрано вакансий: {len(all_vacancies)}")
        self._log(f"Всего запросов обработано: {len(self.queries)}")

        vacancies: list[Vacancy] = []
        for item in all_vacancies:
            try:
                vacancies.append(self._to_vacancy(item))
            except Exception as exc:
                self._log(f"Ошибка преобразования вакансии: {exc}")
                continue

        unique, duplicates = _deduplicate(vacancies)
        return CollectionResult(
            vacancies=unique,
            search_responses=search_responses,
            duplicate_sightings=duplicates,
        )

    def _get_vacancy_links(self, query: str, area: str, page: int) -> list[str] | None:
        """Загружает страницу поиска и возвращает ссылки на вакансии.

        None означает CAPTCHA/блокировку, пустой список — страница без результата.
        Принимаются только ссылки https://hh.ru/vacancy/<id> (реклама adsrv/sovetnik отсекается).
        """
        params = {
            "text": query,
            "area": area,
            "page": page,
            "items_on_page": self.per_page,
            "ored_clusters": "true",
        }
        try:
            response = self._get_page(_SEARCH_URL, params=params)
        except RuntimeError as exc:
            self._log(f"Страница поиска недоступна: {exc}")
            return None
        if response is None:
            return []
        html = response.text
        if self._is_captcha(html):
            return None

        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for elem in soup.find_all("a", {"data-qa": "serp-item__title"}):
            href = elem.get("href")
            if href and VACANCY_LINK_RE.match(href):
                links.append(self._absolute_link(href))

        if not links:
            for elem in soup.find_all("a", class_=re.compile(r"vacancy-name-wrapper")):
                href = elem.get("href")
                if href and VACANCY_LINK_RE.match(href):
                    links.append(self._absolute_link(href))
        return links

    def _fetch_vacancy_page(self, url: str, query_id: str) -> dict[str, Any] | None:
        """Загружает страницу вакансии и парсит данные."""
        try:
            response = self._get_page(url)
        except RuntimeError as exc:
            self._log(f"Ошибка загрузки {url}: {exc}")
            return None
        if response is None:
            return None
        html = response.text
        if self._is_captcha(html):
            self._log(f"CAPTCHA на странице вакансии {url}")
            return None

        soup = BeautifulSoup(html, "html.parser")
        final_url = _clean_vacancy_url(getattr(response, "url", "") or url)
        data = self._parse_vacancy_data(soup, final_url)
        if data is None:
            return None
        data["query_ids"] = [query_id]
        return data

    def _get_page(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        retries: int | None = None,
    ) -> requests.Response | None:
        """GET с ретраями и backoff. None — 404, RuntimeError — устойчивый сбой."""
        retries = self.retries if retries is None else retries
        attempt = 0
        while True:
            try:
                response = self.session.get(
                    url, params=params, headers=self.get_headers(), timeout=self.timeout
                )
            except requests.RequestException as exc:
                if attempt >= retries:
                    raise RuntimeError(f"Ошибка запроса: {exc}") from exc
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue

            code = response.status_code
            if code == 200:
                return response
            if code == 404:
                return None
            if code in {403, 429}:
                if attempt >= retries:
                    raise RuntimeError(f"HTTP {code} — HH ограничил доступ")
                self._sleep(self._backoff(attempt, base=8))
                attempt += 1
                continue
            if code in {500, 502, 503, 504}:
                if attempt >= retries:
                    raise RuntimeError(f"HTTP {code}")
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue
            if attempt >= retries:
                raise RuntimeError(f"HTTP {code}")
            self._log(f"HTTP {code}, пробуем еще раз...")
            self._sleep(self._backoff(attempt))
            attempt += 1

    def _parse_vacancy_data(
        self, soup: BeautifulSoup, url: str
    ) -> dict[str, Any] | None:
        """Парсит данные вакансии: JSON-LD JobPosting + fallback на data-qa."""
        postings = _job_postings_from_soup(soup)
        posting = postings[0] if postings else None

        data: dict[str, Any] = {
            "id": self._extract_vacancy_id(url),
            "link": url,
            "title": "",
            "company": "",
            "salary": "",
            "salary_from": None,
            "salary_to": None,
            "salary_currency": "",
            "salary_gross": None,
            "city": "",
            "experience": "",
            "experience_id": "",
            "description": "",
            "requirements": "",
            "plus": "",
            "key_skills": [],
            "published_at": "",
            "query_ids": [],
        }

        if not data["id"] and posting:
            identifier = posting.get("identifier")
            if isinstance(identifier, dict):
                data["id"] = str(identifier.get("value", ""))
            elif identifier is not None:
                data["id"] = str(identifier)

        # 1. Название
        if posting and posting.get("title"):
            data["title"] = _clean_text(str(posting["title"]))
        else:
            title_elem = soup.find("h1", {"data-qa": "vacancy-title"}) or soup.find(
                "h1"
            )
            if title_elem:
                data["title"] = _clean_text(title_elem.get_text(" ", strip=True))

        # 2. Компания
        organization = (posting or {}).get("hiringOrganization")
        if organization:
            data["company"] = _clean_text(
                str(
                    organization.get("name", "")
                    if isinstance(organization, dict)
                    else organization
                )
            )
        else:
            comp_elem = soup.find(
                "a", {"data-qa": "vacancy-company-name"}
            ) or soup.find("span", {"data-qa": "vacancy-company-name"})
            if comp_elem:
                data["company"] = _clean_text(comp_elem.get_text(" ", strip=True))

        # 3. Зарплата: JSON-LD baseSalary, затем разметка страницы
        posting_salary = self._salary_from_posting(posting) if posting else None
        if posting_salary:
            data["salary"] = posting_salary["text"]
            data["salary_from"] = posting_salary["from"]
            data["salary_to"] = posting_salary["to"]
            data["salary_currency"] = posting_salary["currency"]
            data["salary_gross"] = posting_salary["gross"]
        else:
            salary_elem = soup.find("span", {"data-qa": "vacancy-salary"}) or soup.find(
                "span",
                class_=re.compile(
                    r"magritte-text___pbpft.*magritte-text_typography-label-1-regular"
                ),
            )
            if salary_elem:
                salary_text = _clean_text(salary_elem.get_text(" ", strip=True))
                if re.search(r"\d", salary_text):
                    data["salary"] = salary_text
                    salary = parse_salary(salary_text)
                    if salary:
                        data["salary_from"] = salary["from"]
                        data["salary_to"] = salary["to"]
                        data["salary_currency"] = salary["currency"]
                        data["salary_gross"] = salary["gross"]

        # 4. Город
        location = (posting or {}).get("jobLocation")
        if isinstance(location, dict):
            address = location.get("address")
            if isinstance(address, dict) and address.get("addressLocality"):
                data["city"] = _clean_text(str(address["addressLocality"]))
        if not data["city"]:
            city_elem = soup.find(
                "div", {"data-qa": "vacancy-address-with-map"}
            ) or soup.find("span", {"data-qa": "vacancy-address"})
            if city_elem:
                data["city"] = _clean_text(city_elem.get_text(" ", strip=True))

        # 5. Опыт
        exp_elem = soup.find("span", {"data-qa": "vacancy-experience"})
        if exp_elem:
            experience_text = _clean_text(exp_elem.get_text(" ", strip=True))
            data["experience"] = experience_text
            data["experience_id"] = EXPERIENCE_IDS.get(
                experience_text.lower().replace("–", "-").replace("—", "-"), ""
            )

        # 6. Описание + требования: структурированный JSON-LD description, затем data-qa
        posting_description = (posting or {}).get("description")
        desc_html = ""
        if posting_description and "<" in str(posting_description):
            desc_html = str(posting_description)
        else:
            desc_elem = soup.find("div", {"data-qa": "vacancy-description"})
            if desc_elem is not None:
                desc_html = desc_elem.decode_contents()
        if not desc_html:
            return None
        data["description"] = _strip_bullets(clean_html(desc_html))
        sections = self.extractor.extract(desc_html)
        data["requirements"] = sections["requirements"]
        data["plus"] = sections["plus"]

        # 7. Ключевые навыки
        key_skills: list[str] = []
        for elem in soup.find_all("li", {"data-qa": "skills-element"}):
            skill = _clean_text(elem.get_text(" ", strip=True))
            if skill:
                key_skills.append(skill)
        if not key_skills:
            skills_elem = soup.find("div", {"data-qa": "vacancy-key-skills"})
            if skills_elem is None:
                skills_elem = soup
            for elem in skills_elem.find_all("span", {"data-qa": "bloko-tag__text"}):
                skill = _clean_text(elem.get_text(" ", strip=True))
                if skill:
                    key_skills.append(skill)
        data["key_skills"] = self._enrich_key_skills(key_skills, data["description"])

        # 8. Дата публикации
        data["published_at"] = self._extract_published_at(soup, posting)

        return data

    @staticmethod
    def _salary_from_posting(posting: dict[str, Any]) -> dict[str, Any] | None:
        """Извлекает зарплату из JSON-LD baseSalary (схема JobPosting/MonetaryAmount)."""
        raw = posting.get("baseSalary")
        if not isinstance(raw, dict):
            return None
        currency = str(raw.get("currency") or "")
        value = raw.get("value")
        lo = hi = None
        if isinstance(value, dict):
            lo = value.get("minValue")
            hi = value.get("maxValue")
            if lo is None:
                lo = value.get("value")
            if hi is None:
                hi = value.get("value")
        else:
            lo = hi = value

        def _to_number(item: object) -> float | None:
            if item is None:
                return None
            try:
                return float(str(item).replace(" ", "").replace("\u00a0", ""))
            except TypeError:
                return None
            except ValueError:
                return None

        lo, hi = _to_number(lo), _to_number(hi)
        if lo is None and hi is None:
            return None
        if lo is None:
            lo = hi
        if hi is None:
            hi = lo
        if lo == hi:
            text = f"{lo:g} {currency}" if currency else f"{lo:g}"
        else:
            text = (
                f"от {lo:g} до {hi:g} {currency}"
                if currency
                else f"от {lo:g} до {hi:g}"
            )
        return {"from": lo, "to": hi, "currency": currency, "gross": None, "text": text}

    @staticmethod
    def _term_in_text(text: str, term: str) -> bool:
        pattern = r"(?<![а-яa-z0-9])" + re.escape(term) + r"(?![а-яa-z0-9])"
        return re.search(pattern, text) is not None

    def _enrich_key_skills(self, key_skills: list[str], description: str) -> list[str]:
        """Добавляет в key_skills канонические навыки из описания (без дублей)."""
        if not self.canonical_terms or not description:
            return key_skills
        present = {skill.lower() for skill in key_skills}
        text = description.lower()
        for lower, name in self.canonical_terms:
            if lower in present or name.lower() in present:
                continue
            if self._term_in_text(text, lower):
                present.add(lower)
                present.add(name.lower())
                key_skills.append(name)
        return key_skills

    def _extract_published_at(
        self, soup: BeautifulSoup, posting: dict[str, Any] | None = None
    ) -> str:
        if posting and posting.get("datePosted"):
            return str(posting["datePosted"])
        text_node = soup.find(string=re.compile(r"Вакансия опубликована"))
        if text_node:
            match = re.search(r"(\d{1,2})\s+([а-яё]{3,})\s+(\d{4})", text_node)
            if match:
                return self._to_iso_date(match.group(0))
        meta = soup.find(
            "meta", {"property": "og:article:published_time"}
        ) or soup.find("meta", {"property": "article:published_time"})
        if meta and meta.get("content"):
            return str(meta["content"])
        return ""

    def _to_iso_date(self, value: str) -> str:
        match = re.search(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", value.strip())
        if not match:
            return ""
        day = int(match.group(1))
        month = RUSSIAN_MONTHS.get(match.group(2).lower(), 1)
        year = int(match.group(3))
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return ""

    def _extract_vacancy_id(self, url: str) -> str:
        match = re.search(r"/vacancy/(\d+)", url)
        return match.group(1) if match else ""

    def _is_captcha(self, html: str) -> bool:
        html_lower = html.lower()
        # Явные признаки реального контента
        if "vacancy-serp__vacancy" in html or "serp-item__title" in html:
            return False
        if (
            "vacancy-description" in html
            or "vacancy-title" in html
            or "title-container" in html
        ):
            return False
        captcha_indicators = [
            "captcha",
            "капча",
            "проверка, что вы не робот",
            "проверьте, что вы не робот",
            "access denied",
            "доступ запрещен",
            "unusual traffic",
            "re-captcha",
            "verify you are human",
            "подтвердите, что вы не робот",
        ]
        for indicator in captcha_indicators:
            if indicator in html_lower:
                self._log(f"Найден признак капчи: {indicator}")
                return True
        if len(html) < 500:
            self._log(f"HTML слишком короткий ({len(html)} символов)")
            return True
        return False

    def _to_vacancy(self, item: dict[str, Any]) -> Vacancy:
        description_parts: list[str] = []
        if item.get("description"):
            description_parts.append(item["description"])
        if item.get("key_skills"):
            description_parts.append(
                "Ключевые навыки:\n" + "\n".join(item["key_skills"])
            )

        return Vacancy(
            vacancy_id=str(item.get("id", "")),
            name=str(item.get("title", "")),
            description="\n".join(part for part in description_parts if part),
            employer=str(item.get("company", "")),
            area=str(item.get("city", "")),
            published_at=str(item.get("published_at", "")),
            alternate_url=str(item.get("link", "")),
            source="hh_requests",
            status="active",
            query_ids=tuple(
                sorted(
                    {
                        str(value)
                        for value in item.get("query_ids", [])
                        if str(value).strip()
                    }
                )
            ),
            experience_id=str(item.get("experience_id", "")),
            salary_from=item.get("salary_from"),
            salary_to=item.get("salary_to"),
            salary_currency=str(item.get("salary_currency", "")),
            salary_gross=item.get("salary_gross"),
            raw=item,
        )

    @staticmethod
    def _absolute_link(href: str) -> str:
        return f"https://hh.ru{href}" if href.startswith("/") else href

    @staticmethod
    def _search_response(
        query: str,
        area: str,
        page: int,
        query_id: str,
        links_found: int | None = None,
        status: str = "ok",
        error: str = "",
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "query_id": query_id,
            "query": query,
            "area": area,
            "page": page,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if links_found is not None:
            response["links_found"] = links_found
        if error:
            response["error"] = error
        return response

    @staticmethod
    def _backoff(attempt: int, base: float = 5.0) -> float:
        return base * (2**attempt) + random.uniform(0, 2)

    def _sleep(self, seconds: float) -> None:
        self._log(f"Пауза {seconds:.1f} сек...")
        time.sleep(seconds)

    @staticmethod
    def _log(message: str) -> None:
        print(f"[HH-Requests] {message}")

    def _limit_reached(self, all_vacancies: list[dict[str, Any]]) -> bool:
        return bool(self.max_vacancies and len(all_vacancies) >= self.max_vacancies)


def parse_salary(value: str) -> dict[str, Any] | None:
    """Преобразует текстовую зарплату HH в структуру как в hh_public."""
    if not value:
        return None
    numbers = [
        float(item.replace(" ", "").replace("\u00a0", ""))
        for item in re.findall(r"\d[\d\s\u00a0]*", value)
    ]
    if not numbers:
        return None
    lowered = value.lower()
    currency = "RUR" if "₽" in value or "руб" in lowered else ""
    if len(numbers) > 1:
        salary_from = numbers[0]
        salary_to = numbers[-1]
    elif "от" in lowered:
        salary_from = numbers[0]
        salary_to = None
    elif "до" in lowered:
        salary_from = None
        salary_to = numbers[0]
    else:
        salary_from = numbers[0]
        salary_to = numbers[0]
    gross = None
    if "до вычета" in lowered:
        gross = True
    elif "на руки" in lowered:
        gross = False
    return {"from": salary_from, "to": salary_to, "currency": currency, "gross": gross}
