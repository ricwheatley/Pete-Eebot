"""Framework-free structured request values for coach voice composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypeAlias, cast
from uuid import UUID


SCHEMA_VERSION = "coach_voice_request.v1"

DEFAULT_MUST_NOT_INVENT = (
    "Do not invent workouts, symptoms, pain, meals, races, injuries, or medical advice.",
    "Do not change prescribed loads, RIR, set reductions, Wger status, dates, or targets.",
    "Do not use wearable calories as exact calorie targets.",
    "Do not include raw IDs, UUIDs, database identifiers, JSON keys, or markdown report headings.",
)

JsonSafe: TypeAlias = (
    None | str | int | float | bool | list["JsonSafe"] | dict[str, "JsonSafe"]
)


@dataclass(frozen=True)
class CoachVoiceFact:
    id: str
    text: str
    source: str | None = None
    required: bool = False
    confidence: str | None = None
    required_terms: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "required": self.required,
        }
        if self.source:
            payload["source"] = self.source
        if self.confidence:
            payload["confidence"] = self.confidence
        if self.required_terms:
            payload["required_terms"] = list(self.required_terms)
        return payload


@dataclass(frozen=True)
class CoachVoiceRequest:
    message_type: str
    intent: str
    audience: Mapping[str, Any] = field(default_factory=dict)
    dates: Mapping[str, Any] = field(default_factory=dict)
    metrics_report: Mapping[str, Any] = field(default_factory=dict)
    coach_state: Mapping[str, Any] = field(default_factory=dict)
    goals: Mapping[str, Any] = field(default_factory=dict)
    recent_context: Mapping[str, Any] = field(default_factory=dict)
    deterministic_decisions: Mapping[str, Any] = field(default_factory=dict)
    constraints_and_warnings: Sequence[str] = field(default_factory=tuple)
    must_include_facts: Sequence[CoachVoiceFact | Mapping[str, Any]] = field(
        default_factory=tuple
    )
    must_not_invent: Sequence[str] = field(
        default_factory=lambda: DEFAULT_MUST_NOT_INVENT
    )
    style: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json_safe(
                {
                    "schema_version": self.schema_version,
                    "message_type": self.message_type,
                    "intent": self.intent,
                    "audience": dict(self.audience or {}),
                    "dates": dict(self.dates or {}),
                    "metrics_report": dict(self.metrics_report or {}),
                    "coach_state": dict(self.coach_state or {}),
                    "goals": dict(self.goals or {}),
                    "recent_context": dict(self.recent_context or {}),
                    "deterministic_decisions": dict(self.deterministic_decisions or {}),
                    "constraints_and_warnings": list(
                        self.constraints_and_warnings or ()
                    ),
                    "must_include_facts": [
                        _fact_to_dict(item) for item in self.must_include_facts
                    ],
                    "must_not_invent": list(
                        self.must_not_invent or DEFAULT_MUST_NOT_INVENT
                    ),
                    "style": dict(self.style or {}),
                }
            ),
        )


def _fact_to_dict(
    item: CoachVoiceFact | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(item, CoachVoiceFact):
        return item.as_dict()
    return dict(item or {})


def json_safe(value: object) -> JsonSafe:
    """Convert structured request values to JSON-compatible recursive values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


__all__ = [
    "CoachVoiceFact",
    "CoachVoiceRequest",
    "DEFAULT_MUST_NOT_INVENT",
    "SCHEMA_VERSION",
    "json_safe",
]
