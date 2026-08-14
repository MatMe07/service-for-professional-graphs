from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def stable_json_hash(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def safe_record_name(value: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")[:60] or "record"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{readable}_{digest}"


def make_run_id(profession_slug: str, now: datetime | None = None) -> str:
    instant = now or datetime.now(timezone.utc)
    return f"{instant.strftime('%Y%m%dT%H%M%S%fZ')}_{profession_slug}"


class RunStorage:
    def __init__(self, runs_root: Path, run_id: str) -> None:
        self.root = runs_root / run_id
        self.input_dir = self.root / "input"
        self.raw_dir = self.root / "raw" / "vacancies"
        self.raw_search_dir = self.root / "raw" / "search"
        self.normalized_dir = self.root / "normalized"
        self.output_dir = self.root / "output"

    def prepare(self) -> None:
        if self.root.exists() and any(self.root.iterdir()):
            raise ValueError(f"Каталог запуска уже существует и не пуст: {self.root}")
        for path in (self.input_dir, self.raw_dir, self.raw_search_dir, self.normalized_dir, self.output_dir):
            path.mkdir(parents=True, exist_ok=True)

    def save_raw_vacancy(
        self,
        vacancy_id: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        path = self.raw_dir / f"{safe_record_name(vacancy_id)}.json"
        write_json(
            path,
            {
                "sha256": stable_json_hash(payload),
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {},
                "payload": payload,
            },
        )
        return path

    def save_search_response(self, index: int, payload: dict[str, Any]) -> Path:
        query_id = safe_record_name(str(payload.get("query_id", "query")))
        page = int(payload.get("page", 0))
        path = self.raw_search_dir / f"{index:04d}_{query_id}_page_{page:03d}.json"
        record = {"sha256": stable_json_hash(payload.get("response", payload)), **payload}
        write_json(path, record)
        return path


class VacancyHistory:
    """Append-only vacancy versions shared by multiple runs."""

    def __init__(self, history_root: Path) -> None:
        self.root = history_root / "vacancies"

    def record(self, source: str, vacancy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        identity = hashlib.sha256(f"{source}:{vacancy_id}".encode("utf-8")).hexdigest()[:20]
        item_root = self.root / source / identity
        index_path = item_root / "index.json"
        payload_hash = stable_json_hash(payload)
        version_path = item_root / "versions" / f"{payload_hash}.json"
        now = datetime.now(timezone.utc).isoformat()

        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
        else:
            index = {
                "source": source,
                "vacancy_id": vacancy_id,
                "first_seen_at": now,
                "latest_hash": None,
                "versions": [],
            }

        previous_hash = index.get("latest_hash")
        if previous_hash == payload_hash:
            status = "unchanged"
        else:
            status = "new" if previous_hash is None else "changed"
            if not version_path.exists():
                write_json(
                    version_path,
                    {
                        "sha256": payload_hash,
                        "first_seen_at": now,
                        "payload": payload,
                    },
                )
            index["versions"].append({"sha256": payload_hash, "first_seen_at": now})
            index["latest_hash"] = payload_hash
        index["last_seen_at"] = now
        write_json(index_path, index)
        return {
            "status": status,
            "sha256": payload_hash,
            "history_index": index_path.relative_to(self.root.parent).as_posix(),
            "version_file": version_path.relative_to(self.root.parent).as_posix(),
        }
