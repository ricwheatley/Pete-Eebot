"""Optional LLM voice layer for Pete's final coaching messages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import UUID

from pete_e.infrastructure import log_utils

SCHEMA_VERSION = "coach_voice_request.v1"

SYSTEM_PROMPT = (
    "You are Pete-Eebot's final coaching writer. Write one user-facing Telegram "
    "coaching message from the structured JSON only. Use only facts present in "
    "the JSON. Deterministic decisions are binding: do not change readiness "
    "state, training adjustments, Wger status, goals, thresholds, dates, "
    "numbers, units, or safety warnings. Include every required must_include_facts "
    "item with its numbers and units preserved. Do not invent symptoms, injuries, "
    "meals, workouts, medical claims, race goals, personal history, or missing "
    "subjective inputs. If data quality is low or a fact is missing, acknowledge "
    "uncertainty instead of filling gaps. Keep advice informational, not medical. "
    "Return only the final message text. No labels, JSON, explanations, options, "
    "or follow-up questions."
)

LEGACY_REWRITE_SYSTEM_PROMPT = (
    "Pete rewrites the draft into one natural Telegram message. Return only the rewritten message. "
    "No options, explanations, labels, preambles, or follow-up questions. Do not add, remove, or "
    "change facts, numbers, exercises, dates, targets, medical claims, readiness decisions, Wger "
    "status, or advice. Preserve important metrics, useful line breaks, and Telegram-friendly "
    "formatting."
)

DEFAULT_MUST_NOT_INVENT = (
    "Do not invent workouts, symptoms, pain, meals, races, injuries, or medical advice.",
    "Do not change prescribed loads, RIR, set reductions, Wger status, dates, or targets.",
    "Do not use wearable calories as exact calorie targets.",
)

PROMPT_COACH_STATE_KEYS = (
    "date",
    "summary",
    "derived",
    "baselines",
    "data_quality",
    "missing_subjective_inputs",
    "coaching_notes",
)
PROMPT_MAX_MAPPING_ITEMS = 80
PROMPT_MAX_LIST_ITEMS = 20
PROMPT_MAX_STRING_CHARS = 1200


class CoachVoiceClient(Protocol):
    def chat(self, messages: Sequence[Mapping[str, str]]) -> str: ...


CoachVoicePayloadRecorder = Callable[..., None]


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
    must_include_facts: Sequence[CoachVoiceFact | Mapping[str, Any]] = field(default_factory=tuple)
    must_not_invent: Sequence[str] = field(default_factory=lambda: DEFAULT_MUST_NOT_INVENT)
    style: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return _json_safe(
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
                "constraints_and_warnings": list(self.constraints_and_warnings or ()),
                "must_include_facts": [_fact_to_dict(item) for item in self.must_include_facts],
                "must_not_invent": list(self.must_not_invent or DEFAULT_MUST_NOT_INVENT),
                "style": dict(self.style or {}),
            }
        )


class CoachVoiceService:
    """Compose final coach messages when enabled, falling back on any issue."""

    def __init__(
        self,
        *,
        enabled: bool,
        client: CoachVoiceClient | None = None,
        model_name: str | None = None,
        payload_recorder: CoachVoicePayloadRecorder | None = None,
    ) -> None:
        self.enabled = enabled
        self.client = client
        self.model_name = model_name
        self.payload_recorder = payload_recorder

    def compose(self, request: CoachVoiceRequest | Mapping[str, Any], *, fallback_message: str) -> str:
        fallback = "" if fallback_message is None else str(fallback_message)
        request_payload = _request_to_payload(request)
        prompt_messages: list[dict[str, str]] = []
        start = perf_counter()
        model = self.model_name or str(getattr(self.client, "model", "unknown"))

        if not fallback.strip():
            self._record_payload(
                request_payload=request_payload,
                prompt_messages=prompt_messages,
                fallback_text=fallback,
                final_text=fallback,
                response_text=None,
                model=model,
                status="skipped_empty_fallback",
                duration_ms=0,
                error=None,
            )
            return fallback

        if not self.enabled or self.client is None:
            self._record_payload(
                request_payload=request_payload,
                prompt_messages=prompt_messages,
                fallback_text=fallback,
                final_text=fallback,
                response_text=None,
                model=model,
                status="disabled",
                duration_ms=0,
                error=None,
            )
            return fallback

        try:
            prompt_payload = _to_prompt_payload(request_payload)
            payload_json = json.dumps(prompt_payload, sort_keys=True, ensure_ascii=False)
            prompt_messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Write the final Telegram message for this structured coaching request.\n\n"
                        f"Structured context JSON:\n{payload_json}"
                    ),
                },
            ]
            response = self.client.chat(prompt_messages)
            final_text = self._validate_output(response, request_payload)
            duration_ms = int((perf_counter() - start) * 1000)
            log_utils.info(f"Pete voice compose succeeded model={model} duration_ms={duration_ms}")
            self._record_payload(
                request_payload=request_payload,
                prompt_messages=prompt_messages,
                fallback_text=fallback,
                final_text=final_text,
                response_text=response,
                model=model,
                status="succeeded",
                duration_ms=duration_ms,
                error=None,
            )
            return final_text
        except Exception as exc:
            duration_ms = int((perf_counter() - start) * 1000)
            log_utils.warn(f"Pete voice compose failed; using deterministic fallback: {exc}")
            self._record_payload(
                request_payload=request_payload,
                prompt_messages=prompt_messages,
                fallback_text=fallback,
                final_text=fallback,
                response_text=None,
                model=model,
                status="failed",
                duration_ms=duration_ms,
                error=str(exc),
            )
            return fallback

    def rewrite(self, draft_message: str) -> str:
        """Legacy rewrite path retained only as a compatibility fallback."""

        if not self.enabled or self.client is None or not draft_message.strip():
            return draft_message

        messages = [
            {"role": "system", "content": LEGACY_REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Rewrite this draft only:\n\n{draft_message}"},
        ]

        start = perf_counter()
        try:
            rewritten = self.client.chat(messages)
            if not isinstance(rewritten, str) or not rewritten.strip():
                raise ValueError("voice rewrite returned empty content")
            duration_ms = int((perf_counter() - start) * 1000)
            model = self.model_name or str(getattr(self.client, "model", "unknown"))
            log_utils.info(f"Pete voice rewrite succeeded model={model} duration_ms={duration_ms}")
            return rewritten.strip()
        except Exception as exc:
            log_utils.warn(f"Pete voice rewrite failed; using original message: {exc}")
            return draft_message

    def _validate_output(self, response: Any, request_payload: Mapping[str, Any]) -> str:
        if not isinstance(response, str) or not response.strip():
            raise ValueError("voice compose returned empty content")
        text = response.strip()
        lowered = text.lower().lstrip()
        if lowered.startswith(("{", "[", "```", "here is", "here's", "sure,", "certainly,")):
            raise ValueError("voice compose returned a preamble or non-message content")

        style = request_payload.get("style") if isinstance(request_payload, Mapping) else {}
        if isinstance(style, Mapping):
            max_words = _to_int(style.get("max_words"))
            if max_words is not None and max_words > 0:
                words = re.findall(r"\S+", text)
                if len(words) > max_words + 25:
                    raise ValueError(f"voice compose exceeded max_words by too much: {len(words)} > {max_words}")

        for fact in request_payload.get("must_include_facts", []) if isinstance(request_payload, Mapping) else []:
            if not isinstance(fact, Mapping) or not fact.get("required"):
                continue
            missing = _missing_required_terms(text, fact)
            if missing:
                fact_id = fact.get("id") or "unknown"
                raise ValueError(f"voice compose omitted required fact {fact_id}: {', '.join(missing)}")

        return text

    def _record_payload(
        self,
        *,
        request_payload: Mapping[str, Any],
        prompt_messages: Sequence[Mapping[str, str]],
        fallback_text: str,
        final_text: str,
        response_text: str | None,
        model: str,
        status: str,
        duration_ms: int,
        error: str | None,
    ) -> None:
        if self.payload_recorder is None:
            return
        try:
            self.payload_recorder(
                message_type=str(request_payload.get("message_type") or "unknown"),
                schema_version=str(request_payload.get("schema_version") or SCHEMA_VERSION),
                request_payload=dict(request_payload),
                prompt_messages=[dict(message) for message in prompt_messages],
                response_text=response_text,
                fallback_text=fallback_text,
                final_text=final_text,
                model=model,
                status=status,
                duration_ms=duration_ms,
                error=error,
            )
        except Exception as exc:  # pragma: no cover - audit persistence must not block messages
            log_utils.warn(f"Failed to persist coach voice payload: {exc}")


def _request_to_payload(request: CoachVoiceRequest | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(request, CoachVoiceRequest):
        return request.to_payload()
    payload = dict(request or {})
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("must_not_invent", list(DEFAULT_MUST_NOT_INVENT))
    return _json_safe(payload)


def _fact_to_dict(item: CoachVoiceFact | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(item, CoachVoiceFact):
        return item.as_dict()
    return dict(item or {})


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _to_prompt_payload(request_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact prompt payload while leaving the persisted request intact."""

    payload = dict(request_payload or {})
    coach_state = payload.get("coach_state")
    if isinstance(coach_state, Mapping):
        compact_coach_state = {
            key: coach_state[key]
            for key in PROMPT_COACH_STATE_KEYS
            if key in coach_state
        }
        profile = coach_state.get("profile")
        if isinstance(profile, Mapping):
            compact_coach_state["profile"] = {
                key: profile[key]
                for key in ("display_name", "timezone", "goal_weight_kg", "height_cm")
                if key in profile
            }
        payload["coach_state"] = compact_coach_state

    return _compact_prompt_value(payload)


def _compact_prompt_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return _json_safe(value)
    if isinstance(value, str):
        if len(value) <= PROMPT_MAX_STRING_CHARS:
            return value
        return f"{value[:PROMPT_MAX_STRING_CHARS].rstrip()}..."
    if isinstance(value, Mapping):
        compact: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= PROMPT_MAX_MAPPING_ITEMS:
                compact["_truncated_items"] = len(value) - PROMPT_MAX_MAPPING_ITEMS
                break
            compact[str(key)] = _compact_prompt_value(item, depth=depth + 1)
        return compact
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        compact_list = [_compact_prompt_value(item, depth=depth + 1) for item in items[:PROMPT_MAX_LIST_ITEMS]]
        if len(items) > PROMPT_MAX_LIST_ITEMS:
            compact_list.append({"_truncated_items": len(items) - PROMPT_MAX_LIST_ITEMS})
        return compact_list
    return _json_safe(value)


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _missing_required_terms(text: str, fact: Mapping[str, Any]) -> list[str]:
    terms = fact.get("required_terms")
    if not terms:
        terms = _numbers_in_text(str(fact.get("text") or ""))
    missing: list[str] = []
    normalized_text = _normalize_number_text(text)
    for raw_term in terms or []:
        term = str(raw_term).strip()
        if not term:
            continue
        normalized_term = _normalize_number_text(term)
        if normalized_term and normalized_term not in normalized_text:
            missing.append(term)
    return missing


def _numbers_in_text(text: str) -> list[str]:
    return re.findall(r"(?<!\w)[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?!\w)", text)


def _normalize_number_text(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text.lower())
