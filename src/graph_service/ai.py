from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .storage import write_json


SUPPORTED_PROVIDERS = ("deepseek", "gemini", "openai", "compatible")


class AIError(RuntimeError):
    """Raised when the optional candidate-suggestion service cannot run safely."""


def ai_status(settings: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(settings.get("enabled", False))
    provider = settings.get("provider")
    key_env = str(settings.get("api_key_env", "PROFESSIONAL_GRAPHS_AI_KEY"))
    key_ready = bool(os.getenv(key_env, "").strip())
    return {
        "enabled": enabled,
        "provider": provider,
        "supported_providers": list(SUPPORTED_PROVIDERS),
        "api_key_env": key_env,
        "api_key_ready": key_ready,
        "ready": enabled and provider in SUPPORTED_PROVIDERS and key_ready,
        "policy": "AI may suggest aliases and candidate nodes, but cannot publish them automatically.",
        "raw_hh_data_transfer": False,
    }


def suggest_dictionary_candidates(
    settings: dict[str, Any],
    unclassified_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Ask an optional LLM for review candidates without publishing dictionary changes."""
    status = ai_status(settings)
    if not status["ready"]:
        raise AIError("AI не готов: включите ai.enabled, укажите provider и задайте ключ в переменной среды.")
    try:
        source = json.loads(unclassified_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AIError(f"Не удалось прочитать кандидатов {unclassified_path}: {exc}") from exc
    items = source.get("items", []) if isinstance(source, dict) else []
    compact_items = [
        {"phrase": str(item.get("phrase", "")), "vacancy_count": int(item.get("vacancy_count", 0))}
        for item in items
        if isinstance(item, dict) and str(item.get("phrase", "")).strip()
    ]
    if not compact_items:
        result = _candidate_result(settings, [], "В исходном отчёте нет неизвестных фраз.")
        write_json(output_path, result)
        return result

    provider = str(settings["provider"])
    endpoint = str(settings.get("base_url") or _default_endpoint(provider)).strip()
    model = str(settings.get("model", "")).strip()
    if not endpoint or not model:
        raise AIError("Для AI нужно указать ai.base_url и ai.model (для известных provider адрес можно не задавать).")
    key = os.environ[str(settings.get("api_key_env", "PROFESSIONAL_GRAPHS_AI_KEY"))].strip()
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты помогаешь составить словарь IT-навыков. Верни только JSON-объект с массивом candidates. "
                    "Каждый элемент: phrase, canonical_name, aliases, suggested_path, confidence, reason. "
                    "Не выдумывай навык, если фраза похожа на шум: тогда canonical_name=null."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"unknown_phrases": compact_items}, ensure_ascii=False),
            },
        ],
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=int(settings.get("timeout_seconds", 45))) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise AIError(f"AI API вернул HTTP {exc.code}. Ключ и адрес не записаны в отчёт.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIError(f"Не удалось получить корректный ответ AI API: {exc}") from exc
    try:
        content = response_data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        candidates = parsed.get("candidates", [])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise AIError("AI API ответил, но формат ответа не похож на ожидаемый JSON.") from exc
    if not isinstance(candidates, list):
        raise AIError("Поле candidates в ответе AI должно быть массивом.")
    result = _candidate_result(settings, candidates, None)
    write_json(output_path, result)
    return result


def _default_endpoint(provider: str) -> str:
    return {
        "deepseek": "https://api.deepseek.com/chat/completions",
        "openai": "https://api.openai.com/v1/chat/completions",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "compatible": "",
    }.get(provider, "")


def _candidate_result(settings: dict[str, Any], candidates: list[Any], note: str | None) -> dict[str, Any]:
    return {
        "status": "manual_review_required",
        "provider": settings.get("provider"),
        "model": settings.get("model"),
        "candidates": candidates,
        "note": note,
        "auto_applied": False,
        "raw_hh_data_sent": False,
        "next_step": "Проверьте кандидатов вручную; этот файл сам не меняет словарь и графы.",
    }
