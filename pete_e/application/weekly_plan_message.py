"""Application-owned weekly-plan selection, presentation, and coach voice."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol, cast

from pete_e.application.coach_voice_types import CoachVoiceFact, CoachVoiceRequest


class WeeklyPlanReader(Protocol):
    """Read only the active plan and one selected plan week."""

    def get_active_plan(self) -> Mapping[str, Any] | None: ...

    def get_plan_week(
        self,
        plan_id: object,
        week_number: int,
    ) -> Iterable[Mapping[str, Any]] | None: ...


class WeeklyPlanRenderer(Protocol):
    """Render raw plan rows through the established domain presentation facade."""

    def build_weekly_plan(
        self,
        plan_week_data: Iterable[Mapping[str, Any]],
        week_number: int,
        week_start: date | None = None,
    ) -> str: ...


class WeeklyPlanVoiceComposer(Protocol):
    """Optionally turn a deterministic weekly schedule into coach voice."""

    def compose(
        self,
        request: CoachVoiceRequest,
        *,
        fallback_message: str,
    ) -> str: ...


class WeeklyPlanCoachStateProvider(Protocol):
    def __call__(self, target: date) -> object: ...


WeeklyPlanLogger = Callable[[str, str], None]


class WeeklyPlanMessageBuilder(Protocol):
    def build_message(
        self,
        *,
        target_date: date | None = None,
        current_date: date | None = None,
    ) -> str: ...


class _ActivePlanLoader(Protocol):
    def __call__(self) -> object: ...


class _PlanWeekLoader(Protocol):
    def __call__(self, plan_id: object, week_number: int) -> object: ...


class _VoiceComposeCallable(Protocol):
    def __call__(
        self,
        request: CoachVoiceRequest,
        *,
        fallback_message: str,
    ) -> object: ...


@dataclass(frozen=True)
class LegacyWeeklyPlanReader:
    """Normalize the two legacy DAL reader names behind the typed read port."""

    active_plan_loader: _ActivePlanLoader
    plan_week_loader: _PlanWeekLoader

    def get_active_plan(self) -> Mapping[str, Any] | None:
        return cast(Mapping[str, Any] | None, self.active_plan_loader())

    def get_plan_week(
        self,
        plan_id: object,
        week_number: int,
    ) -> Iterable[Mapping[str, Any]] | None:
        return cast(
            Iterable[Mapping[str, Any]] | None,
            self.plan_week_loader(plan_id, week_number),
        )


@dataclass(frozen=True)
class LegacyWeeklyPlanVoiceComposer:
    """Retain callable-only legacy voice discovery without leaking it into policy."""

    composer: _VoiceComposeCallable

    def compose(
        self,
        request: CoachVoiceRequest,
        *,
        fallback_message: str,
    ) -> str:
        return cast(
            str,
            self.composer(request, fallback_message=fallback_message),
        )


def select_legacy_weekly_plan_reader(source: object | None) -> WeeklyPlanReader | None:
    """Select the preferred legacy read capabilities once, at the adapter edge."""

    if source is None:
        return None
    active_loader = getattr(source, "get_active_plan", None)
    if not callable(active_loader):
        return None
    for name in ("get_plan_week", "get_plan_week_rows"):
        week_loader = getattr(source, name, None)
        if callable(week_loader):
            return LegacyWeeklyPlanReader(
                active_plan_loader=cast(_ActivePlanLoader, active_loader),
                plan_week_loader=cast(_PlanWeekLoader, week_loader),
            )
    return None


def select_legacy_weekly_plan_voice(
    source: object | None,
) -> WeeklyPlanVoiceComposer | None:
    """Expose a voice composer only when the legacy collaborator is callable."""

    composer = getattr(source, "compose", None)
    if not callable(composer):
        return None
    return LegacyWeeklyPlanVoiceComposer(cast(_VoiceComposeCallable, composer))


@dataclass(frozen=True)
class _Failure:
    message: str


@dataclass(frozen=True)
class _WeekSelection:
    target: date
    active_plan: Mapping[str, Any]
    plan_id: object
    week_number: int
    week_start: date


def _discard_log(_message: str, _level: str) -> None:
    return None


def resolve_weekly_plan_target(
    *,
    target_date: date | None,
    current_date: date,
) -> date:
    """Apply the established Sunday-to-Monday default selection rule."""

    if target_date is not None:
        return target_date
    if current_date.isoweekday() == 7:
        return current_date + timedelta(days=1)
    return current_date


def _coerce_start_date(value: object, logger: WeeklyPlanLogger) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        logger("Active plan start date could not be parsed.", "ERROR")
        return None


def _coerce_total_weeks(value: object) -> int:
    try:
        return int(cast(Any, value or 0))
    except (TypeError, ValueError):
        return 0


def select_plan_week(
    active_plan: Mapping[str, Any],
    *,
    target: date,
    logger: WeeklyPlanLogger,
) -> _WeekSelection | _Failure:
    """Select the lifecycle week while retaining every legacy error string."""

    start_date = _coerce_start_date(active_plan.get("start_date"), logger)
    if start_date is None:
        return _Failure("The active training plan has an invalid start date.")
    days_since_start = (target - start_date).days
    if days_since_start < 0:
        return _Failure(f"The active training plan starts on {start_date.isoformat()}.")
    total_weeks = _coerce_total_weeks(active_plan.get("weeks"))
    if total_weeks <= 0:
        return _Failure("The active training plan is missing its duration.")
    week_number = (days_since_start // 7) + 1
    if week_number > total_weeks:
        return _Failure(
            "The current training plan has finished. Time to generate a new one!"
        )
    plan_id = active_plan.get("id")
    if plan_id is None:
        return _Failure("The active training plan is missing its identifier.")
    return _WeekSelection(
        target=target,
        active_plan=active_plan,
        plan_id=plan_id,
        week_number=week_number,
        week_start=start_date + timedelta(days=(week_number - 1) * 7),
    )


def weekly_plan_required_terms(rows: Iterable[object]) -> list[str]:
    """Return up to ten unique non-empty legacy exercise-name terms."""

    terms: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("exercise_name") or "").strip()
        if name and name not in terms:
            terms.append(name)
        if len(terms) >= 10:
            break
    return terms


def _dictionary_state(coach_state: object) -> dict[str, Any]:
    return coach_state if isinstance(coach_state, dict) else {}


def build_weekly_plan_voice_request(
    *,
    fallback: str,
    selection: _WeekSelection,
    plan_week_rows: list[Mapping[str, Any]],
    coach_state: object,
) -> CoachVoiceRequest:
    """Build the exact structured request consumed by the existing voice service."""

    state = _dictionary_state(coach_state)
    profile_value = state.get("profile")
    profile = profile_value if isinstance(profile_value, dict) else {}
    required_terms = [str(selection.week_number)]
    required_terms.extend(weekly_plan_required_terms(plan_week_rows))
    fact = CoachVoiceFact(
        id="weekly_plan_schedule",
        text=fallback,
        source="training_plan",
        required=True,
        required_terms=tuple(required_terms),
    )
    return CoachVoiceRequest(
        message_type="weekly_plan",
        intent="weekly training plan overview",
        audience={
            "name": profile.get("display_name") or "Ric",
            "timezone": profile.get("timezone") or "Europe/London",
        },
        dates={
            "target_date": selection.target.isoformat(),
            "week_start": selection.week_start.isoformat(),
            "week_end": (selection.week_start + timedelta(days=6)).isoformat(),
        },
        metrics_report={},
        coach_state=cast(Mapping[str, Any], coach_state),
        goals=state.get("goal_state", {}),
        recent_context={
            "active_plan": selection.active_plan,
            "plan_week_rows": plan_week_rows,
            "plan_context": state.get("plan_context", {}),
            "recent_workouts": state.get("recent_workouts", {}),
        },
        deterministic_decisions={
            "week_number": selection.week_number,
            "week_start": selection.week_start.isoformat(),
            "exact_schedule_must_be_preserved": True,
        },
        constraints_and_warnings=list(state.get("coaching_notes", [])),
        must_include_facts=[fact],
        style={
            "channel": "telegram",
            "voice": "Pete",
            "tone": "clear, personal, trainer-like, practical",
            "max_words": 260,
            "format": "compact weekly schedule with exact sessions preserved",
        },
    )


@dataclass(frozen=True)
class WeeklyPlanPresentationService:
    """Coordinate weekly-plan reading, rendering, context, and optional voice."""

    reader: WeeklyPlanReader | None
    renderer: WeeklyPlanRenderer
    voice_composer: WeeklyPlanVoiceComposer | None = None
    coach_state_provider: WeeklyPlanCoachStateProvider | None = None
    logger: WeeklyPlanLogger = _discard_log
    today: Callable[[], date] = date.today

    def build_message(
        self,
        *,
        target_date: date | None = None,
        current_date: date | None = None,
    ) -> str:
        target = resolve_weekly_plan_target(
            target_date=target_date,
            current_date=current_date or self.today(),
        )
        if self.reader is None:
            return "Training plan data source is not available."
        active_plan = self._load_active_plan()
        if isinstance(active_plan, _Failure):
            return active_plan.message
        selection = select_plan_week(active_plan, target=target, logger=self.logger)
        if isinstance(selection, _Failure):
            return selection.message
        plan_week_rows = self._load_plan_week(selection)
        if isinstance(plan_week_rows, _Failure):
            return plan_week_rows.message
        return self._present(selection, plan_week_rows)

    def _load_active_plan(self) -> Mapping[str, Any] | _Failure:
        reader = cast(WeeklyPlanReader, self.reader)
        try:
            active_plan = reader.get_active_plan()
        except Exception as exc:
            self.logger(f"Failed to load active plan: {exc}", "ERROR")
            return _Failure("Failed to load the active training plan.")
        if not active_plan:
            return _Failure("There is no active training plan in the database.")
        return active_plan

    def _load_plan_week(
        self,
        selection: _WeekSelection,
    ) -> Iterable[Mapping[str, Any]] | _Failure:
        reader = cast(WeeklyPlanReader, self.reader)
        try:
            rows = reader.get_plan_week(
                selection.plan_id,
                selection.week_number,
            )
        except Exception as exc:
            self.logger(f"Failed to load plan week data: {exc}", "ERROR")
            return _Failure(
                "Could not retrieve workouts for "
                f"Plan ID {selection.plan_id}, Week {selection.week_number}."
            )
        if not rows:
            return _Failure(
                "Could not find workout data for "
                f"Plan ID {selection.plan_id}, Week {selection.week_number}."
            )
        return rows

    def _present(
        self,
        selection: _WeekSelection,
        rows: Iterable[Mapping[str, Any]],
    ) -> str:
        fallback = self.renderer.build_weekly_plan(
            rows,
            selection.week_number,
            week_start=selection.week_start,
        )
        materialized_rows = list(rows)
        if self.voice_composer is None:
            return fallback
        coach_state = self._load_coach_state(selection.target)
        request = build_weekly_plan_voice_request(
            fallback=fallback,
            selection=selection,
            plan_week_rows=materialized_rows,
            coach_state=coach_state,
        )
        return self.voice_composer.compose(request, fallback_message=fallback)

    def _load_coach_state(self, target: date) -> object:
        if self.coach_state_provider is None:
            return {}
        try:
            return self.coach_state_provider(target)
        except Exception as exc:
            self.logger(
                "Failed to load structured coach state for weekly voice context: "
                f"{exc}",
                "WARN",
            )
            return {}


__all__ = [
    "LegacyWeeklyPlanReader",
    "LegacyWeeklyPlanVoiceComposer",
    "WeeklyPlanCoachStateProvider",
    "WeeklyPlanMessageBuilder",
    "WeeklyPlanPresentationService",
    "WeeklyPlanReader",
    "WeeklyPlanRenderer",
    "WeeklyPlanVoiceComposer",
    "build_weekly_plan_voice_request",
    "resolve_weekly_plan_target",
    "select_legacy_weekly_plan_reader",
    "select_legacy_weekly_plan_voice",
    "select_plan_week",
    "weekly_plan_required_terms",
]
