"""Feature-flag registry for experimental planner behavior."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


_TRUE_VALUES = {"1", "true", "yes", "y", "on", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "n", "off", "disabled"}


@dataclass(frozen=True)
class PlannerFeatureFlags:
    """Opt-in switches for experimental planner behavior.

    Defaults must remain conservative. Production enables experiments only via
    explicit configuration or constructor injection in tests/tools.
    """

    experimental_relaxed_session_spacing: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {key: bool(value) for key, value in asdict(self).items()}

    def non_default_flags(self) -> dict[str, bool]:
        defaults = PlannerFeatureFlags().to_dict()
        return {
            key: value
            for key, value in self.to_dict().items()
            if defaults.get(key) != value
        }


def parse_planner_feature_flags(raw: str | Mapping[str, Any] | PlannerFeatureFlags | None) -> PlannerFeatureFlags:
    """Parse planner flags from config strings or explicit mappings.

    String syntax is comma-separated and intentionally simple:
    ``flag_name=true,other_flag=false``. A bare flag name means ``true``.
    Unknown flags or invalid booleans raise ``ValueError`` so bad production
    overrides fail fast instead of silently changing planner behavior.
    """

    if raw is None or raw == "":
        return PlannerFeatureFlags()
    if isinstance(raw, PlannerFeatureFlags):
        return raw
    if isinstance(raw, str):
        return _parse_flag_string(raw)
    return _parse_flag_mapping(raw)


def _parse_flag_string(raw: str) -> PlannerFeatureFlags:
    values: dict[str, bool] = {}
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            values[key.strip()] = _parse_bool(key.strip(), value)
        else:
            values[token] = True
    return _parse_flag_mapping(values)


def _parse_flag_mapping(raw: Mapping[str, Any]) -> PlannerFeatureFlags:
    allowed = PlannerFeatureFlags().to_dict()
    values = dict(allowed)
    for key, value in raw.items():
        normalized_key = str(key).strip()
        if normalized_key not in allowed:
            raise ValueError(f"Unknown planner feature flag: {normalized_key}")
        values[normalized_key] = _coerce_bool(normalized_key, value)
    return PlannerFeatureFlags(**values)


def _parse_bool(key: str, raw: str) -> bool:
    return _coerce_bool(key, raw.strip())


def _coerce_bool(key: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ValueError(f"Invalid boolean value for planner feature flag {key}: {value!r}")
