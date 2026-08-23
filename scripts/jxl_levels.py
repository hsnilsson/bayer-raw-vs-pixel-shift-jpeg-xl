from __future__ import annotations


DEFAULT_LEVELS = ["lossless", "d003", "d005", "d010"]


def is_level(value: str) -> bool:
    if value == "lossless":
        return True
    return len(value) >= 3 and value.startswith("d") and value[1:].isdigit()


def require_level(value: str) -> str:
    if not is_level(value):
        raise ValueError(
            f"invalid JXL level: {value!r}; use 'lossless' or names like d003, d005, d010, d020"
        )
    return value


def distance_for_level(level: str) -> str | None:
    require_level(level)
    if level == "lossless":
        return None
    value = int(level[1:]) / 100
    return f"{value:.2f}"
