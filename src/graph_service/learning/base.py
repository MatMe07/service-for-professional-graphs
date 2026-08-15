from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "ref",
    "source",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def normalize_resource_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Некорректный URL учебного материала: {value}")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [(key, item) for key, item in query if key.lower() not in TRACKING_PARAMETERS]
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", urllib.parse.urlencode(filtered), "")
    )


def check_resource_url(url: str, timeout: float = 10.0) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "ProfessionalGraphService/0.7 (learning-link-check)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {
                "checked_at": checked_at,
                "status_code": response.status,
                "final_url": response.url,
                "available": 200 <= response.status < 400,
            }
    except urllib.error.HTTPError as exc:
        return {
            "checked_at": checked_at,
            "status_code": exc.code,
            "final_url": exc.url,
            "available": False,
        }
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "checked_at": checked_at,
            "status_code": None,
            "final_url": url,
            "available": None,
            "error": str(exc),
        }
