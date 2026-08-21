from __future__ import annotations

from typing import Any

import requests

from .base import LearningProvider, ParserError
from .habr import HabrProvider
from .stepik import StepikProvider
from .youtube import YouTubeProvider


PROVIDER_CLASSES: dict[str, type[LearningProvider]] = {
    "stepik": StepikProvider,
    "habr": HabrProvider,
    "youtube": YouTubeProvider,
}


def build_parsers(
    names: list[str] | tuple[str, ...],
    youtube_api_key_env: str = "YOUTUBE_API_KEY",
    session: requests.Session | None = None,
) -> list[LearningProvider]:
    providers: list[LearningProvider] = []
    for name in names:
        provider_class = PROVIDER_CLASSES.get(str(name).strip())
        if provider_class is None:
            raise ParserError(f"Неизвестный учебный провайдер: {name}")
        if provider_class is YouTubeProvider:
            providers.append(provider_class(api_key_env=youtube_api_key_env, session=session))
        else:
            providers.append(provider_class(session=session))
    return providers


__all__ = [
    "HabrProvider",
    "LearningProvider",
    "ParserError",
    "StepikProvider",
    "YouTubeProvider",
    "build_parsers",
]
