from __future__ import annotations

import json
import uuid
from typing import Mapping, Sequence

from pete_e.application.coach_voice import CoachVoiceService, LEGACY_REWRITE_SYSTEM_PROMPT, SYSTEM_PROMPT


class _FakeClient:
    def __init__(self, response: str | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.messages: Sequence[Mapping[str, str]] | None = None
        self.model = "qwen2.5:1.5b"

    def chat(self, messages: Sequence[Mapping[str, str]]) -> str:
        self.messages = messages
        if self.exc is not None:
            raise self.exc
        return self.response or ""


def test_llm_disabled_returns_original_message_unchanged() -> None:
    client = _FakeClient(response="rewritten")
    service = CoachVoiceService(enabled=False, client=client)

    assert service.rewrite("original draft") == "original draft"
    assert client.messages is None


def test_compose_disabled_returns_fallback_and_records_payload() -> None:
    records: list[dict] = []
    client = _FakeClient(response="structured message")
    service = CoachVoiceService(enabled=False, client=client, payload_recorder=lambda **row: records.append(row))

    request = {"message_type": "daily_summary", "intent": "morning check-in"}

    assert service.compose(request, fallback_message="fallback message") == "fallback message"
    assert client.messages is None
    assert records[0]["status"] == "disabled"
    assert records[0]["request_payload"]["message_type"] == "daily_summary"
    assert records[0]["fallback_text"] == "fallback message"


def test_compose_enabled_fake_client_success_uses_structured_prompt(monkeypatch) -> None:
    logs: list[str] = []
    records: list[dict] = []
    monkeypatch.setattr("pete_e.application.coach_voice.log_utils.info", logs.append)
    client = _FakeClient(response="Ric, 180g protein is banked. Keep today's work tidy.")
    service = CoachVoiceService(enabled=True, client=client, payload_recorder=lambda **row: records.append(row))

    request = {
        "message_type": "daily_summary",
        "intent": "morning check-in",
        "must_include_facts": [
            {
                "id": "protein",
                "text": "180g protein",
                "required": True,
                "required_terms": ["180"],
            }
        ],
        "style": {"max_words": 40},
    }

    assert service.compose(request, fallback_message="fallback message") == (
        "Ric, 180g protein is banked. Keep today's work tidy."
    )
    assert client.messages is not None
    assert client.messages[0]["role"] == "system"
    assert client.messages[0]["content"] == SYSTEM_PROMPT
    assert "Structured context JSON" in client.messages[1]["content"]
    assert "180g protein" in client.messages[1]["content"]
    assert len(logs) == 1
    assert logs[0].startswith("Pete voice compose succeeded model=qwen2.5:1.5b duration_ms=")
    assert "fallback message" not in logs[0]
    assert records[0]["status"] == "succeeded"
    assert records[0]["final_text"] == "Ric, 180g protein is banked. Keep today's work tidy."


def test_compose_accepts_uuid_values_in_structured_payload() -> None:
    records: list[dict] = []
    request_id = uuid.uuid4()
    client = _FakeClient(response="Ric, readiness is clear enough to keep today's message simple.")
    service = CoachVoiceService(enabled=True, client=client, payload_recorder=lambda **row: records.append(row))

    result = service.compose(
        {
            "message_type": "preview_message",
            "intent": "operator preview",
            "recent_context": {"request_id": request_id},
        },
        fallback_message="fallback message",
    )

    assert result == "Ric, readiness is clear enough to keep today's message simple."
    assert client.messages is not None
    assert str(request_id) not in client.messages[1]["content"]
    assert records[0]["request_payload"]["recent_context"]["request_id"] == str(request_id)
    assert records[0]["status"] == "succeeded"


def test_compose_uses_compact_prompt_payload_but_persists_full_request() -> None:
    records: list[dict] = []
    client = _FakeClient(response="Ric, recovery is steady enough to keep the message tight.")
    service = CoachVoiceService(enabled=True, client=client, payload_recorder=lambda **row: records.append(row))
    duplicate_workouts = {
        "running": [
            {
                "workout_date": "2026-06-09",
                "internal_blob": "duplicate coach_state workout detail that should not be prompted",
            }
        ]
    }

    result = service.compose(
        {
            "message_type": "daily_summary",
            "intent": "morning check-in",
            "coach_state": {
                "date": "2026-06-09",
                "summary": {"readiness_state": "steady"},
                "derived": {"run_load_7d_km": 12.0},
                "recent_workouts": duplicate_workouts,
                "plan_context": {"large_duplicate": "not needed from coach_state"},
                "nutrition": {"large_duplicate": "not needed from coach_state"},
            },
            "recent_context": {
                "recent_workouts": {"running": [{"workout_date": "2026-06-09", "distance_km": 5.0}]}
            },
        },
        fallback_message="fallback message",
    )

    assert result == "Ric, recovery is steady enough to keep the message tight."
    assert records[0]["request_payload"]["coach_state"]["recent_workouts"] == duplicate_workouts
    assert client.messages is not None
    prompt_json = client.messages[1]["content"].split("Structured context JSON:\n", 1)[1]
    prompt_payload = json.loads(prompt_json)
    assert "recent_workouts" not in prompt_payload["coach_state"]
    assert "plan_context" not in prompt_payload["coach_state"]
    assert "nutrition" not in prompt_payload["coach_state"]
    assert prompt_payload["coach_state"]["summary"]["readiness_state"] == "steady"
    assert prompt_payload["recent_context"]["recent_workouts"]["running"][0]["distance_km"] == 5.0


def test_compose_strips_internal_ids_from_prompt_payload() -> None:
    records: list[dict] = []
    workout_id = "3b3c6ca6-9e07-4cae-b4e1-c86e82476e46"
    client = _FakeClient(response="Ric, yesterday's run was a big aerobic load, so keep today controlled.")
    service = CoachVoiceService(enabled=True, client=client, payload_recorder=lambda **row: records.append(row))

    result = service.compose(
        {
            "message_type": "daily_summary",
            "intent": "morning check-in",
            "recent_context": {
                "recent_workouts": {
                    "running": [
                        {
                            "workout_id": workout_id,
                            "exercise_id": 530,
                            "distance_km": 10.089,
                        }
                    ]
                }
            },
        },
        fallback_message="fallback message",
    )

    assert result == "Ric, yesterday's run was a big aerobic load, so keep today controlled."
    assert records[0]["request_payload"]["recent_context"]["recent_workouts"]["running"][0]["workout_id"] == workout_id
    assert client.messages is not None
    prompt_json = client.messages[1]["content"].split("Structured context JSON:\n", 1)[1]
    prompt_payload = json.loads(prompt_json)
    prompted_workout = prompt_payload["recent_context"]["recent_workouts"]["running"][0]
    assert "workout_id" not in prompted_workout
    assert "exercise_id" not in prompted_workout
    assert prompted_workout["distance_km"] == 10.089
    assert workout_id not in client.messages[1]["content"]


def test_compose_validation_failure_returns_fallback(monkeypatch) -> None:
    warnings: list[str] = []
    records: list[dict] = []
    monkeypatch.setattr("pete_e.application.coach_voice.log_utils.warn", warnings.append)
    service = CoachVoiceService(
        enabled=True,
        client=_FakeClient(response="Ric, keep it tidy today."),
        payload_recorder=lambda **row: records.append(row),
    )

    request = {
        "message_type": "daily_summary",
        "intent": "morning check-in",
        "must_include_facts": [
            {"id": "protein", "text": "180g protein", "required": True, "required_terms": ["180"]}
        ],
    }

    assert service.compose(request, fallback_message="fallback message") == "fallback message"
    assert records[0]["status"] == "failed"
    assert "omitted required fact protein" in records[0]["error"]
    assert warnings[0].startswith("Pete voice compose failed; using deterministic fallback:")


def test_compose_rejects_report_style_output_with_raw_ids(monkeypatch) -> None:
    warnings: list[str] = []
    records: list[dict] = []
    monkeypatch.setattr("pete_e.application.coach_voice.log_utils.warn", warnings.append)
    service = CoachVoiceService(
        enabled=True,
        client=_FakeClient(
            response=(
                "### Current Workout Summary\n\n"
                "- **Workout ID:** `3b3c6ca6-9e07-4cae-b4e1-c86e82476e46`\n"
                "- **Distance:** 10.089 km"
            )
        ),
        payload_recorder=lambda **row: records.append(row),
    )

    assert service.compose({"message_type": "daily_summary", "intent": "morning check-in"}, fallback_message="fallback") == "fallback"
    assert records[0]["status"] == "failed"
    assert "raw UUID" in records[0]["error"] or "markdown report headings" in records[0]["error"]
    assert warnings[0].startswith("Pete voice compose failed; using deterministic fallback:")


def test_legacy_rewrite_success_still_available(monkeypatch) -> None:
    logs: list[str] = []
    monkeypatch.setattr("pete_e.application.coach_voice.log_utils.info", logs.append)
    client = _FakeClient(response="rewritten message")
    service = CoachVoiceService(enabled=True, client=client)

    assert service.rewrite("original draft") == "rewritten message"
    assert client.messages is not None
    assert client.messages[0]["role"] == "system"
    assert client.messages[0]["content"] == LEGACY_REWRITE_SYSTEM_PROMPT
    assert "original draft" in client.messages[1]["content"]
    assert logs[0].startswith("Pete voice rewrite succeeded model=qwen2.5:1.5b duration_ms=")


def test_llm_enabled_fake_client_failure_returns_original_message(monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr("pete_e.application.coach_voice.log_utils.warn", warnings.append)
    service = CoachVoiceService(enabled=True, client=_FakeClient(exc=RuntimeError("boom")))

    assert service.rewrite("original draft") == "original draft"
    assert warnings == ["Pete voice rewrite failed; using original message: boom"]
    assert "original draft" not in warnings[0]


def test_llm_enabled_empty_client_response_returns_original_message(monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr("pete_e.application.coach_voice.log_utils.warn", warnings.append)
    service = CoachVoiceService(enabled=True, client=_FakeClient(response="   "))

    assert service.rewrite("original draft") == "original draft"
    assert warnings
