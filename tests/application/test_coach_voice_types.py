"""Pure coverage for framework-free coach voice request values."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pete_e.application.coach_voice_types import (
    CoachVoiceFact,
    CoachVoiceRequest,
    DEFAULT_MUST_NOT_INVENT,
    SCHEMA_VERSION,
    json_safe,
)


def test_fact_optional_fields_and_request_payload_are_exact() -> None:
    minimal = CoachVoiceFact(id="minimal", text="text")
    complete = CoachVoiceFact(
        id="complete",
        text="required text",
        source="metrics",
        required=True,
        confidence="observed",
        required_terms=("12",),
    )
    request = CoachVoiceRequest(
        message_type="test",
        intent="exercise types",
        audience={"day": date(2024, 9, 2)},
        must_include_facts=(minimal, complete, {"id": "mapping"}, {}),
        must_not_invent=(),
    )

    assert minimal.as_dict() == {"id": "minimal", "text": "text", "required": False}
    assert complete.as_dict() == {
        "id": "complete",
        "text": "required text",
        "required": True,
        "source": "metrics",
        "confidence": "observed",
        "required_terms": ["12"],
    }
    payload = request.to_payload()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["audience"] == {"day": "2024-09-02"}
    assert payload["must_include_facts"] == [
        minimal.as_dict(),
        complete.as_dict(),
        {"id": "mapping"},
        {},
    ]
    assert payload["must_not_invent"] == list(DEFAULT_MUST_NOT_INVENT)


def test_json_safe_covers_supported_recursive_and_fallback_values() -> None:
    identifier = UUID("3b3c6ca6-9e07-4cae-b4e1-c86e82476e46")

    assert json_safe(None) is None
    assert json_safe("text") == "text"
    assert json_safe(Decimal("12.5")) == 12.5
    assert json_safe(identifier) == str(identifier)
    assert json_safe(datetime(2024, 9, 2, 7, 30)) == "2024-09-02T07:30:00"
    assert json_safe((date(2024, 9, 2), {1, 2})) in (
        ["2024-09-02", [1, 2]],
        ["2024-09-02", [2, 1]],
    )
    assert json_safe(object()).startswith("<object object at")
