from __future__ import annotations

import time
from typing import Any

import requests


USER_AGENT = "ProfessionalGraphs/0.9 (learning-resource-collector)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ParserError(RuntimeError):
    pass


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


class LearningProvider:
    name: str = "unknown"

    def __init__(
        self,
        timeout: float = 15.0,
        retries: int = 2,
        interval: float = 0.5,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = float(timeout)
        self.retries = max(1, int(retries))
        self.interval = max(0.0, float(interval))
        self.session = session if session is not None else requests.Session()

    @property
    def configured(self) -> bool:
        return True

    def search(self, node_name: str, limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get(self, url: str, params: dict[str, Any] | None = None) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            if attempt:
                time.sleep(self.interval)
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    headers={"User-Agent": USER_AGENT},
                )
                if response.status_code not in RETRY_STATUSES:
                    return response
                last_error = ParserError(f"HTTP {response.status_code}")
            except requests.RequestException as exc:
                last_error = exc
        raise ParserError(f"Не удалось получить {url}: {last_error}")
