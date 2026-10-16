"""Pure configuration merge (SPEC.md section 10.1, SPEC_.md correction 5).

Two precedence modes share one recursive walk:

- `prefer="base"` (the default): the base decides every conflict. Objects merge
  recursively; scalars, arrays, null and type mismatches keep the base value.
  Fields only in the update are added, fields only in the base are kept.
- `prefer="update"`: the historical behaviour, where the update replaces the
  base on any conflict.

Inputs are never mutated and an update cannot delete a base field in either
mode.
"""

from __future__ import annotations

from typing import Any

BASE_FIRST = "base"
UPDATE_FIRST = "update"
PREFERENCES = (BASE_FIRST, UPDATE_FIRST)


def merge(base: Any, update: Any, *, prefer: str = BASE_FIRST) -> Any:
    """Merge `update` onto `base`; inputs are not mutated.

    `prefer` selects who wins a conflict. With the default `"base"` the base
    value survives every non-object conflict; `"update"` restores the original
    rule where the update replaces the base.
    """
    if prefer not in PREFERENCES:
        raise ValueError(f"prefer must be one of {PREFERENCES}, got {prefer!r}")
    return _merge(base, update, prefer)


def _merge(base: Any, update: Any, prefer: str) -> Any:
    if isinstance(base, dict) and isinstance(update, dict):
        merged = dict(base)
        for key, value in update.items():
            if key in merged:
                merged[key] = _merge(merged[key], value, prefer)
            else:
                merged[key] = _copy(value)
        return merged
    if isinstance(base, dict) != isinstance(update, dict):
        # A type mismatch is a conflict like any other: the winner is copied.
        return _copy(base if prefer == BASE_FIRST else update)
    if isinstance(base, list) or isinstance(update, list) or base != update:
        if prefer == BASE_FIRST:
            return _copy(base)
        return _copy(update)
    return _copy(base)


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value