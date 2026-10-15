"""Pure configuration merge (SPEC.md section 10.1)."""

from __future__ import annotations

from typing import Any


def merge(base: Any, update: Any) -> Any:
    """Merge `update` onto `base`; the update wins, inputs are not mutated.

    Objects merge recursively. Scalars, arrays, null, and type mismatches
    replace the base value entirely. Fields only in the update are added,
    fields only in the base are kept. An update cannot delete a base field.
    """
    if isinstance(base, dict) and isinstance(update, dict):
        merged = dict(base)
        for key, value in update.items():
            if key in merged:
                merged[key] = merge(merged[key], value)
            else:
                merged[key] = _copy(value)
        return merged
    return _copy(update)


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value