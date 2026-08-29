"""Small content-and-parameter cache for derived image artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def file_state(path: Path | None, root: Path | None = None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    stat = path.stat()
    try:
        display_path = path.resolve().relative_to((root or Path.cwd()).resolve()).as_posix()
    except ValueError:
        display_path = str(path.resolve())
    return {
        "path": display_path,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("entries"), dict):
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    return payload


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    cache["schema_version"] = SCHEMA_VERSION
    cache["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def outputs_match(entry: dict[str, Any], outputs: dict[str, Path], root: Path | None = None) -> bool:
    states = entry.get("outputs")
    if not isinstance(states, dict):
        return False
    for name, path in outputs.items():
        current = file_state(path, root)
        if current is None or states.get(name) != current:
            return False
    return True


def fresh(
    entry: dict[str, Any] | None,
    expected_fingerprint: str,
    outputs: dict[str, Path],
    root: Path | None = None,
) -> bool:
    return bool(
        entry
        and entry.get("fingerprint") == expected_fingerprint
        and outputs_match(entry, outputs, root)
    )


def make_entry(expected_fingerprint: str, outputs: dict[str, Path], root: Path | None = None) -> dict[str, Any]:
    return {
        "fingerprint": expected_fingerprint,
        "outputs": {name: file_state(path, root) for name, path in outputs.items()},
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
