from __future__ import annotations

from urllib.parse import urlsplit


PROVIDER_DOMAINS = {
    "stepik": {"stepik.org"},
    "habr": {"habr.com"},
    "youtube": {"youtube.com", "www.youtube.com", "youtu.be"},
}

COLLECTOR_PROVIDERS = ("stepik", "habr", "youtube")


def validate_provider(provider: str, url: str) -> None:
    if provider == "official":
        return
    expected = PROVIDER_DOMAINS.get(provider)
    if expected is None:
        raise ValueError(f"Неизвестный обработчик учебного источника: {provider}")
    domain = urlsplit(url).netloc.lower()
    if domain not in expected:
        raise ValueError(f"URL {url} не соответствует обработчику {provider}.")
