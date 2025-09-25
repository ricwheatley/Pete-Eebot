"""
Main orchestrator for Pete-Eebot's core logic.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# DAL and Clients
from pete_e.domain.data_access import DataAccessLayer
from pete_e.infrastructure.postgres_dal import PostgresDal, close_pool
from pete_e.infrastructure.withings_client import WithingsClient, WithingsReauthRequired
from pete_e.infrastructure.wger_client import WgerClient
from pete_e.infrastructure import telegram_sender

# Core Logic and Helpers
from pete_e.domain.narrative_builder import NarrativeBuilder, PeteVoice
from pete_e.domain.plan_builder import build_block, build_strength_test
from pete_e.domain.progression import PlanProgressionDecision, calibrate_plan_week
from pete_e.domain.validation import (
    ValidationDecision,
    validate_and_adjust_plan,
    summarise_readiness,
)
from pete_e.application import wger_sender
from pete_e.cli import messenger as messenger_cli
from pete_e.domain import body_age, metrics_service, french_trainer, phrase_picker
from pete_e.domain.user_helpers import calculate_age
from pete_e.infrastructure import log_utils
from pete_e.infrastructure import plan_rw
from pete_e.config import settings
from pete_e.application.apple_dropbox_ingest import (
    AppleIngestError,
    get_last_successful_import_timestamp,
    run_apple_health_ingest,
)

DAILY_SYNC_SOURCES = (
    "AppleDropbox",
    "Withings",
    "Wger",
    "BodyAge",
)
WITHINGS_ONLY_SOURCES = (
    "Withings",
    "BodyAge",
)

STRENGTH_TEST_INTERVAL_WEEKS = 13



def _closes_postgres_pool(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        finally:
            close_pool()
    return wrapper


class DailySummaryDispatchLedger:
    """Tracks which dates have had their daily summary dispatched."""

    def __init__(
        self,
        *,
        store_path: Path | None = None,
        retention_days: int = 14,
    ) -> None:
        self.retention_days = max(1, int(retention_days))
        if store_path is None:
            base_dir = settings.log_path.parent
            self.path = base_dir / "daily_summary_dispatch.json"
        else:
            store_path = Path(store_path)
            if store_path.is_dir():
                self.path = store_path / "daily_summary_dispatch.json"
            else:
                self.path = store_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[str, str]] | None = None

    def _load(self) -> Dict[str, Dict[str, str]]:
        if self._cache is not None:
            return self._cache
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            data: Dict[str, Dict[str, str]] = {}
        else:
            raw = raw.strip()
            if not raw:
                data = {}
            else:
                try:
                    loaded = json.loads(raw)
                except json.JSONDecodeError:
                    log_utils.log_message(
                        "Daily summary dispatch ledger was corrupt; resetting.",
                        "WARN",
                    )
                    data = {}
                else:
                    if isinstance(loaded, dict):
                        data = {}
                        for key, value in loaded.items():
                            if isinstance(key, str) and isinstance(value, dict):
                                data[key] = {
                                    str(sub_key): ("" if sub_val is None else str(sub_val))
                                    for sub_key, sub_val in value.items()
                                }
                    else:
                        data = {}
        self._cache = data
        return data

    def _persist(self, data: Dict[str, Dict[str, str]]) -> None:
        self.path.write_text(
            json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        self._cache = data

    def _prune_expired(self, data: Dict[str, Dict[str, str]], reference_date: date) -> bool:
        cutoff = reference_date - timedelta(days=self.retention_days)
        removed = False
        for key in list(data.keys()):
            try:
                entry_date = date.fromisoformat(key)
            except ValueError:
                data.pop(key, None)
                removed = True
                continue
            if entry_date < cutoff:
                data.pop(key, None)
                removed = True
        return removed

    def was_sent(self, target_date: date) -> bool:
        data = self._load()
        if self._prune_expired(data, target_date):
            self._persist(data)
        iso_value = target_date.isoformat()
        entry = data.get(iso_value)
        if not entry:
            return False
        sent_at = entry.get("sent_at")
        return bool(sent_at)

    def mark_sent(self, target_date: date, summary: str) -> None:
        data = self._load()
        if self._prune_expired(data, target_date):
            pass
        preview = (summary or "").strip()
        if len(preview) > 180:
            preview = f"{preview[:177]}..."
        data[target_date.isoformat()] = {
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "summary_preview": preview,
        }
        self._persist(data)


@dataclass(frozen=True)
class WeeklyCalibrationResult:
    """Aggregate outcome of the weekly calibration workflow."""

    plan_id: int | None
    week_number: int | None
    week_start: date
    progression: PlanProgressionDecision | None
    validation: ValidationDecision | None
    message: str


@dataclass(frozen=True)
class CycleRolloverResult:
    """Outcome of the automated cycle rollover pipeline."""

    plan_id: int | None
    created: bool
    exported: bool
    start_date: date
    message: str | None = None


@dataclass(frozen=True)
class DailyAutomationResult:
    """Summary of the automated daily flow outcome."""

    ingest_success: bool
    failed_sources: List[str]
    source_statuses: Dict[str, str]
    summary_target: date
    summary_sent: bool
    summary_attempted: bool
    undelivered_alerts: List[str]


@dataclass(frozen=True)
class WeeklyAutomationResult:
    """Wraps weekly calibration and any rollover attempt."""

    calibration: WeeklyCalibrationResult
    rollover: CycleRolloverResult | None
    rollover_triggered: bool
    reference_date: date



@dataclass(frozen=True)
class NudgeCandidate:
    """Encapsulates a Telegram nudge before rendering."""

    tag: str
    sprinkles: List[str] | None = None


def _next_monday(reference: date) -> date:
    """Return the next Monday strictly after the reference date."""

    delta = (7 - reference.weekday()) % 7
    if delta == 0:
        delta = 7
    return reference + timedelta(days=delta)


def _ensure_date(value) -> date | None:
    """Best effort conversion of DB date/datetime/iso strings to date."""

    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class Orchestrator:
    """
    Handles the main business logic and coordination between different parts
    of the application.
    """

    def __init__(
        self,
        dal: DataAccessLayer = None,
        summary_dispatch_ledger: DailySummaryDispatchLedger | None = None,
    ) -> None:
        self.dal = dal or PostgresDal()
        self.narrative_builder = NarrativeBuilder()
        self.summary_dispatch_ledger = summary_dispatch_ledger or DailySummaryDispatchLedger()

    def _describe_session(self, rows: Iterable[Mapping[str, Any]]) -> str | None:
        strength_names: list[str] = []
        cardio_present = False
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            if row.get("is_cardio"):
                cardio_present = True
                continue
            name = row.get("exercise_name") or row.get("name")
            if name:
                strength_names.append(str(name))
        if not strength_names and not cardio_present:
            return None
        unique_strength = sorted({name for name in strength_names})
        if unique_strength and cardio_present:
            focus = ", ".join(unique_strength[:2])
            if len(unique_strength) > 2:
                focus += ", ..."
            return f"Strength ({focus}) + cardio"
        if unique_strength:
            focus = ", ".join(unique_strength[:2])
            if len(unique_strength) > 2:
                focus += ", ..."
            return f"Strength ({focus})"
        if cardio_present:
            return "Cardio / conditioning"
        return None

    def _build_calendar_context(self, message_date: date) -> Dict[str, Any]:
        context: Dict[str, Any] = {}
        try:
            active_plan = self.dal.get_active_plan()
        except Exception as exc:
            log_utils.log_message(f"Failed to load active plan for trainer context: {exc}", "WARN")
            return context
        if not active_plan:
            return context
        start_date = _ensure_date(active_plan.get("start_date"))
        weeks_raw = active_plan.get("weeks")
        try:
            total_weeks = int(weeks_raw) if weeks_raw is not None else None
        except (TypeError, ValueError):
            total_weeks = None
        if start_date is None or not total_weeks or total_weeks <= 0:
            return context
        days_since_start = (message_date - start_date).days
        if days_since_start < 0:
            return context
        week_number = (days_since_start // 7) + 1
        if week_number > total_weeks:
            return context
        plan_id = active_plan.get("id")
        if plan_id is None:
            return context
        try:
            week_rows = self.dal.get_plan_week(plan_id, week_number)
        except Exception as exc:
            log_utils.log_message(f"Failed to load plan week {week_number} for trainer context: {exc}", "WARN")
            return context
        dow_target = message_date.isoweekday()
        todays: list[Mapping[str, Any]] = []
        for row in week_rows or []:
            if not isinstance(row, Mapping):
                continue
            try:
                dow_value = int(row.get("day_of_week"))
            except (TypeError, ValueError):
                continue
            if dow_value == dow_target:
                todays.append(row)
        if not todays:
            context["today_session_type"] = "rest"
            return context
        label = self._describe_session(todays)
        context["today_session_type"] = label or "training"
        return context

    def build_trainer_message(self, *, message_date: date | None = None) -> str:
        metrics = metrics_service.get_metrics_overview(self.dal)
        context = self._build_calendar_context(message_date or date.today())
        return french_trainer.compose_daily_message(metrics, context)

    def send_trainer_message(self, *, message_date: date | None = None) -> str:
        message = self.build_trainer_message(message_date=message_date)
        if not message or not message.strip():
            return ""
        if not self.send_telegram_message(message):
            raise RuntimeError("Telegram send failed for trainer summary.")
        return message

    def get_daily_summary(self, target_date: date = None) -> str:
        """
        Generates a human-readable summary for a given day.
        If Apple Health data is missing, sends a cheeky Telegram nudge.
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)  # Default to yesterday

        log_utils.log_message(f"Generating daily summary for {target_date.isoformat()}", "INFO")
        summary_raw = self.dal.get_daily_summary(target_date)

        if not summary_raw:
            return f"I have no data for {target_date.strftime('%A, %B %d')}. Something might have gone wrong with the daily sync."

        summary_data = dict(summary_raw)

        if not summary_data.get("readiness_state"):
            try:
                readiness_snapshot = summarise_readiness(
                    self.dal, target_date + timedelta(days=1)
                )
            except Exception as exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(
                    f"Failed to compute readiness snapshot for {target_date.isoformat()}: {exc}",
                    "WARN",
                )
            else:
                if readiness_snapshot.state != "ready":
                    summary_data["readiness_state"] = readiness_snapshot.state
                    summary_data["readiness_headline"] = readiness_snapshot.headline
                    if readiness_snapshot.tip:
                        summary_data["readiness_tip"] = readiness_snapshot.tip

        # --- Cheeky Apple Health nudge ---
        if summary_data.get("steps") is None and summary_data.get("hr_resting") is None:
            nudge = phrase_picker.random_phrase(tags=["#AppleNudge"])
            try:
                self.send_telegram_message(nudge)
                log_utils.log_message(f"Sent Apple Health nudge: {nudge}", "INFO")
            except Exception as e:
                log_utils.log_message(f"Failed to send Apple Health nudge: {e}", "WARN")

        return self.narrative_builder.build_daily_summary(summary_data)



    def dispatch_nudges(self, *, reference_date: date | None = None) -> List[str]:
        """Evaluate the latest data snapshot and send any relevant nudges."""

        reference = reference_date or date.today()

        try:
            history_raw = list(self.dal.get_historical_metrics(14))
        except Exception as exc:  # pragma: no cover - defensive guardrail
            log_utils.log_message(
                f"Failed to load historical metrics for nudges: {exc}",
                "WARN",
            )
            history_raw = []

        cleaned_history: List[Dict[str, Any]] = []
        for entry in history_raw:
            if not isinstance(entry, dict):
                continue
            entry_date = entry.get("date")
            if isinstance(entry_date, date) and entry_date <= reference:
                cleaned_history.append(dict(entry))
        cleaned_history.sort(key=lambda item: item["date"])

        lift_log: Dict[str, List[Dict[str, Any]]] = {}
        load_lift = getattr(self.dal, "load_lift_log", None)
        if callable(load_lift):
            try:
                raw_log = load_lift(end_date=reference)
            except Exception as exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(
                    f"Failed to load lift log for nudges: {exc}",
                    "WARN",
                )
                raw_log = {}
            else:
                for key, entries in (raw_log or {}).items():
                    if not entries:
                        continue
                    bucket: List[Dict[str, Any]] = []
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        entry_date = entry.get("date")
                        if entry_date is not None and isinstance(entry_date, date):
                            if entry_date > reference:
                                continue
                        bucket.append(dict(entry))
                    if bucket:
                        lift_log[str(key)] = bucket

        candidates = self._build_nudge_candidates(
            cleaned_history,
            lift_log,
            reference,
        )

        dispatched: List[str] = []
        for candidate in candidates:
            sprinkles = list(candidate.sprinkles or [])
            message = PeteVoice.nudge(candidate.tag, sprinkles)
            try:
                delivered = bool(self.send_telegram_message(message))
            except Exception as exc:  # pragma: no cover - defensive guardrail
                delivered = False
                log_utils.log_message(
                    f"Failed to send nudge {candidate.tag}: {exc}",
                    "WARN",
                )
            if delivered:
                dispatched.append(message)
        return dispatched

    def generate_strength_test_week(self, start_date: date = date.today()) -> bool:
        """Create, activate, and export a strength test week."""

        try:
            plan_id = build_strength_test(self.dal, start_date)
            if not plan_id:
                raise ValueError("Strength test builder returned invalid plan identifier.")

            activator = getattr(self.dal, "mark_plan_active", None)
            if callable(activator):
                activator(plan_id)

            wger_sender.push_week(
                self.dal,
                plan_id,
                week=1,
                start_date=start_date,
            )
        except Exception as exc:  # pragma: no cover - defensive guardrail
            log_utils.log_message(
                f"Failed to generate strength test week: {exc}",
                "ERROR",
            )
            return False

        log_utils.log_message(
            f"Strength test week {plan_id} generated and exported.",
            "INFO",
        )
        return True

    def _build_nudge_candidates(
        self,
        history: List[Dict[str, Any]],
        lift_log: Dict[str, List[Dict[str, Any]]],
        reference: date,
    ) -> List[NudgeCandidate]:
        candidates: List[NudgeCandidate] = []

        withings_candidate = self._nudge_for_stale_withings(history, reference)
        if withings_candidate:
            candidates.append(withings_candidate)

        strain_candidate = self._nudge_for_high_strain(history, reference)
        if strain_candidate:
            candidates.append(strain_candidate)

        pb_sprinkles = self._personal_best_sprinkles(lift_log, reference)
        if pb_sprinkles:
            candidates.append(NudgeCandidate("#PersonalBest", pb_sprinkles))

        return candidates

    def _nudge_for_stale_withings(
        self,
        history: List[Dict[str, Any]],
        reference: date,
    ) -> NudgeCandidate | None:
        raw_window = getattr(settings, "NUDGE_WITHINGS_STALE_DAYS", 3)
        try:
            window = max(1, int(raw_window))
        except (TypeError, ValueError):
            window = 3

        if not history:
            return None

        missing_streak = 0
        last_weight_date: date | None = None

        for entry in reversed(history):
            entry_date = entry["date"]
            if entry_date > reference:
                continue
            weight = entry.get("weight_kg")
            if weight is None:
                missing_streak += 1
                continue
            last_weight_date = entry_date
            break

        if missing_streak < window or last_weight_date is None:
            return None

        days_since = (reference - last_weight_date).days
        if days_since < window:
            return None

        detail = (
            f"No Withings weight logged since {last_weight_date.isoformat()} "
            f"({days_since} day(s))."
        )
        sprinkles = [detail, "Hop on the scale so I can keep the trend charts honest."]
        return NudgeCandidate("#WithingsCheck", sprinkles)

    def _nudge_for_high_strain(
        self,
        history: List[Dict[str, Any]],
        reference: date,
    ) -> NudgeCandidate | None:
        raw_threshold = getattr(settings, "NUDGE_STRAIN_THRESHOLD", 185.0)
        raw_window = getattr(settings, "NUDGE_STRAIN_CONSECUTIVE_DAYS", 3)
        try:
            threshold = float(raw_threshold)
        except (TypeError, ValueError):
            threshold = 185.0
        try:
            window = max(1, int(raw_window))
        except (TypeError, ValueError):
            window = 3

        if len(history) < window:
            return None

        scores: List[tuple[date, float]] = []
        for entry in history:
            entry_date = entry["date"]
            if entry_date > reference:
                continue
            scores.append((entry_date, self._estimate_daily_strain(entry)))

        if len(scores) < window:
            return None

        recent = scores[-window:]
        if not all(score >= threshold for _, score in recent):
            return None

        prior = scores[:-window]
        if prior and prior[-1][1] >= threshold:
            return None

        avg_recent = sum(score for _, score in recent) / window
        details = [
            f"Strain has been above {threshold:.0f} for {window} day(s). Average {avg_recent:.0f}.",
        ]
        if prior:
            details.append(
                f"Yesterday landed at {prior[-1][1]:.0f}, so bank some recovery time."
            )
        else:
            details.append("Let's bank the gains with a lighter day.")

        return NudgeCandidate("#HighStrainRest", details)

    def _personal_best_sprinkles(
        self,
        lift_log: Dict[str, List[Dict[str, Any]]],
        reference: date,
    ) -> List[str]:
        summaries: List[str] = []

        for exercise_id, entries in lift_log.items():
            best_prior: tuple[float, int] | None = None
            best_today: tuple[float, int] | None = None
            best_entry: Dict[str, Any] | None = None

            for entry in entries:
                entry_date = entry.get("date")
                if entry_date is not None and (
                    not isinstance(entry_date, date) or entry_date > reference
                ):
                    continue

                weight_raw = entry.get("weight_kg")
                if weight_raw is None:
                    continue
                try:
                    weight = float(weight_raw)
                except (TypeError, ValueError):
                    continue

                reps_raw = entry.get("reps")
                try:
                    reps = int(reps_raw) if reps_raw is not None else 0
                except (TypeError, ValueError):
                    reps = 0

                score = (weight, reps)

                if entry_date == reference:
                    if best_today is None or score > best_today:
                        best_today = score
                        best_entry = entry
                else:
                    if best_prior is None or score > best_prior:
                        best_prior = score

            if best_entry is None or (
                best_prior is not None and best_today is not None and best_today <= best_prior
            ):
                continue

            best_weight = float(best_entry.get("weight_kg", 0.0) or 0.0)
            reps_display = best_entry.get("reps")

            detail = f"Exercise {exercise_id} PB: {best_weight:.1f} kg"
            if reps_display:
                try:
                    reps_int = int(reps_display)
                except (TypeError, ValueError):
                    reps_int = None
                if reps_int:
                    detail += f" x {reps_int}"

            if best_prior is not None:
                detail += f" (prev {best_prior[0]:.1f} kg)"

            summaries.append(detail)

        return summaries

    def _estimate_daily_strain(self, entry: Dict[str, Any]) -> float:
        if "strain_score" in entry and entry["strain_score"] is not None:
            try:
                return float(entry["strain_score"])
            except (TypeError, ValueError):
                pass

        minutes = float(entry.get("exercise_minutes") or 0)
        calories = float(entry.get("calories_active") or 0)
        volume = float(entry.get("strength_volume_kg") or 0)
        return (minutes * 1.2) + (calories / 15.0) + (volume / 200.0)


    def get_week_plan_summary(self, target_date: date = None) -> str:
        """Generates a human-readable summary of the current week's training plan."""
        if target_date is None:
            target_date = date.today()

        log_utils.log_message(
            f"Generating weekly plan summary for week of {target_date.isoformat()}",
            "INFO",
        )

        active_plan = self.dal.get_active_plan()
        if not active_plan:
            return "There is no active training plan in the database."

        start_value = active_plan.get("start_date")
        if isinstance(start_value, datetime):
            start_date = start_value.date()
        elif isinstance(start_value, date):
            start_date = start_value
        elif isinstance(start_value, str):
            try:
                start_date = date.fromisoformat(start_value)
            except ValueError:
                log_utils.log_message("Active plan start date could not be parsed.", "ERROR")
                return "The active training plan has an invalid start date."
        else:
            return "The active training plan has an invalid start date."

        days_since_start = (target_date - start_date).days
        if days_since_start < 0:
            return f"The active training plan starts on {start_date.isoformat()}."

        try:
            total_weeks = int(active_plan.get("weeks") or 0)
        except (TypeError, ValueError):
            total_weeks = 0
        if total_weeks <= 0:
            return "The active training plan is missing its duration."

        week_number = (days_since_start // 7) + 1
        if week_number > total_weeks:
            return "The current training plan has finished. Time to generate a new one!"

        plan_id = active_plan.get("id")
        if plan_id is None:
            return "The active training plan is missing its identifier."

        try:
            plan_week_data = self.dal.get_plan_week(plan_id, week_number)
        except Exception as exc:
            log_utils.log_message(f"Failed to load plan week data: {exc}", "ERROR")
            return f"Could not retrieve workouts for Plan ID {plan_id}, Week {week_number}."

        if not plan_week_data:
            return f"Could not find workout data for Plan ID {plan_id}, Week {week_number}."

        week_start = start_date + timedelta(days=(week_number - 1) * 7)
        return self.narrative_builder.build_weekly_plan(
            plan_week_data,
            week_number,
            week_start=week_start,
        )

    # TODO: Replace the fallback logic when DataAccessLayer.get_plan has a full
    #       implementation that returns the plan structure from the database.
    def get_plan(self, plan_id: int) -> Dict[str, Any]:
        """Return the stored training plan or warn if the DAL stub is invoked."""

        getter = getattr(self.dal, "get_plan", None)
        if not callable(getter):
            log_utils.log_message(
                "Data access layer does not expose get_plan(); returning empty plan.",
                "WARN",
            )
            return {}

        try:
            plan_data = getter(plan_id)
        except NotImplementedError:
            log_utils.log_message(
                "Data access layer get_plan() raised NotImplementedError; TODO: implement plan retrieval.",
                "WARN",
            )
            return {}
        except Exception as exc:
            log_utils.log_message(
                f"Failed to retrieve plan {plan_id}: {exc}",
                "ERROR",
            )
            return {}

        if not plan_data:
            log_utils.log_message(
                (
                    f"Data access layer get_plan() returned no data for plan {plan_id}. "
                    "TODO: implement full plan retrieval."
                ),
                "WARN",
            )
            return {}

        if isinstance(plan_data, dict):
            return dict(plan_data)

        log_utils.log_message(
            (
                f"Data access layer get_plan() returned unexpected type {type(plan_data)!r} "
                f"for plan {plan_id}; expected a mapping."
            ),
            "WARN",
        )
        return {}


    def send_telegram_message(self, message: str) -> bool:
        """Sends a message using the Telegram sender."""
        return telegram_sender.send_message(message)

    def _auto_send_daily_summary(self, *, target_date: date) -> bool:
        """Generate and send Pierre's trainer summary with idempotency."""
        if self.summary_dispatch_ledger.was_sent(target_date):
            log_utils.log_message(
                f"Skipping auto summary send for {target_date.isoformat()}; already sent.",
                "INFO",
            )
            return False

        message_date = target_date + timedelta(days=1)
        try:
            summary_text = self.send_trainer_message(message_date=message_date)
        except Exception as exc:
            log_utils.log_message(
                f"Auto trainer summary send failed for {target_date.isoformat()}: {exc}",
                "ERROR",
            )
            return False

        if not summary_text or not summary_text.strip():
            log_utils.log_message(
                f"Auto trainer summary skipped for {target_date.isoformat()}: summary empty.",
                "WARN",
            )
            return False

        self.summary_dispatch_ledger.mark_sent(target_date, summary_text)
        log_utils.log_message(
            f"Auto trainer summary sent for {target_date.isoformat()}",
            "INFO",
        )
        return True
    @_closes_postgres_pool
    def run_weekly_calibration(
        self,
        reference_date: date | None = None,
    ) -> WeeklyCalibrationResult:
        """Calibrate the upcoming training week using progression and recovery signals."""

        today = reference_date or date.today()
        week_start = _next_monday(today)

        active_plan = self.dal.get_active_plan()
        if not active_plan:
            message = "No active training plan found; weekly calibration skipped."
            log_utils.log_message(message, "WARN")
            return WeeklyCalibrationResult(
                plan_id=None,
                week_number=None,
                week_start=week_start,
                progression=None,
                validation=None,
                message=message,
            )

        plan_id = active_plan.get("id")
        if plan_id is None:
            message = "Active plan record lacks an id; weekly calibration skipped."
            log_utils.log_message(message, "ERROR")
            return WeeklyCalibrationResult(
                plan_id=None,
                week_number=None,
                week_start=week_start,
                progression=None,
                validation=None,
                message=message,
            )

        plan_start = _ensure_date(active_plan.get("start_date"))
        if plan_start is None:
            message = "Active plan is missing a valid start_date; weekly calibration skipped."
            log_utils.log_message(message, "ERROR")
            return WeeklyCalibrationResult(
                plan_id=plan_id,
                week_number=None,
                week_start=week_start,
                progression=None,
                validation=None,
                message=message,
            )

        weeks_total_raw = active_plan.get("weeks")
        try:
            weeks_total: Optional[int] = int(weeks_total_raw) if weeks_total_raw is not None else None
        except (TypeError, ValueError):
            weeks_total = None

        days_since_start = (week_start - plan_start).days
        week_number = 1 if days_since_start < 0 else (days_since_start // 7) + 1
        if weeks_total is not None and week_number > weeks_total:
            message = (
                f"Upcoming week {week_number} exceeds plan length ({weeks_total}); calibration skipped."
            )
            log_utils.log_message(message, "WARN")
            return WeeklyCalibrationResult(
                plan_id=plan_id,
                week_number=week_number,
                week_start=week_start,
                progression=None,
                validation=None,
                message=message,
            )

        progression_decision = calibrate_plan_week(
            self.dal,
            plan_id=plan_id,
            week_number=week_number,
            persist=True,
        )
        if progression_decision.updates and not progression_decision.persisted:
            log_utils.log_message(
                "Progression recommended updates but DAL did not persist them.",
                "WARN",
            )

        validation_decision = validate_and_adjust_plan(self.dal, week_start)

        readiness = validation_decision.readiness
        if validation_decision.needs_backoff:
            alert_parts = [f"Readiness alert: {readiness.headline}"]
            if readiness.reasons:
                alert_parts.append(f"Reasons: {', '.join(readiness.reasons)}")
            if readiness.tip:
                alert_parts.append(f"Tip: {readiness.tip}")
            alert_message = " ".join(alert_parts)
            try:
                sent = bool(telegram_sender.send_alert(alert_message))
            except Exception as exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(f"Failed to send readiness alert: {exc}", "WARN")
            else:
                if sent:
                    log_utils.log_message("Dispatched readiness alert for weekly back-off.", "INFO")
                else:
                    log_utils.log_message("Readiness alert send returned False; Telegram suppressed.", "WARN")

        log_payload: List[str] = [
            f"plan_id={plan_id}",
            f"week={week_number}",
            f"week_start={week_start.isoformat()}",
        ]
        log_payload.extend(progression_decision.notes)
        log_payload.extend(validation_decision.log_entries)

        if hasattr(self.dal, "save_validation_log"):
            try:
                self.dal.save_validation_log("weekly_calibration", log_payload)
            except Exception as exc:
                log_utils.log_message(
                    f"Failed to persist weekly calibration log: {exc}",
                    "WARN",
                )

        updates_count = len(progression_decision.updates)
        if updates_count:
            note_preview = progression_decision.notes[0] if progression_decision.notes else ""
            if len(note_preview) > 90:
                note_preview = note_preview[:87] + "..."
            progression_summary = (
                f"{updates_count} load update(s) applied. " + note_preview
            ).strip()
        else:
            progression_summary = "No load adjustments required."

        message = (
            f"Week {week_number} starting {week_start.isoformat()} recalibrated: "
            f"{progression_summary} {validation_decision.explanation}"
        ).strip()

        log_utils.log_message(f"Weekly calibration summary: {message}", "INFO")

        return WeeklyCalibrationResult(
            plan_id=plan_id,
            week_number=week_number,
            week_start=week_start,
            progression=progression_decision,
            validation=validation_decision,
            message=message,
        )
    @_closes_postgres_pool
    def run_daily_sync(self, days: int) -> Tuple[bool, List[str], Dict[str, str], List[str]]:
        """
        Orchestrates the daily data synchronization process.

        This method fetches data from all external sources, saves it to the
        database, and triggers necessary recalculations. The returned tuple
        captures overall success, failing sources, per-source statuses, and any
        alert messages that could not be dispatched via Telegram.
        """
        today = date.today()
        log_utils.log_message(f"Orchestrator starting sync for last {days} days.", "INFO")

        withings_client = WithingsClient()
        wger_client = WgerClient() # Assuming a WgerClient class exists
        withings_reauth_alert_sent = False

        failed_sources: List[str] = []
        source_statuses: Dict[str, str] = {name: "ok" for name in DAILY_SYNC_SOURCES}
        alert_messages: List[str] = []
        undelivered_alerts: List[str] = []

        try:
            apple_report = run_apple_health_ingest()
        except AppleIngestError as exc:
            log_utils.log_message(
                f"Apple Health Dropbox ingest failed before sync window: {exc}",
                "ERROR",
            )
            failed_sources.append("AppleDropbox")
            source_statuses["AppleDropbox"] = "failed"
            alert_messages.append(f"Apple Health ingest failed: {exc}")
        except Exception as exc:
            log_utils.log_message(
                f"Apple Health Dropbox ingest failed before sync window: {exc}",
                "ERROR",
            )
            failed_sources.append("AppleDropbox")
            source_statuses["AppleDropbox"] = "failed"
            alert_messages.append(f"Apple Health ingest failed: {exc}")
        else:
            processed_files = len(apple_report.sources)
            log_utils.log_message(
                (
                    "Apple Health Dropbox ingest finished. "
                    f"Processed {processed_files} file(s), "
                    f"{apple_report.workouts} workouts, "
                    f"and {apple_report.daily_points} metric points."
                ),
                "INFO",
            )

            try:
                last_import_ts = get_last_successful_import_timestamp()
            except AppleIngestError as checkpoint_error:
                log_utils.log_message(
                    f"Unable to determine last Apple import timestamp: {checkpoint_error}",
                    "WARN",
                )
            else:
                max_stale_days = getattr(settings, "APPLE_MAX_STALE_DAYS", 3)
                try:
                    max_stale_days = int(max_stale_days)
                except (TypeError, ValueError):
                    max_stale_days = 3

                if max_stale_days >= 0:
                    if last_import_ts is None:
                        alert_messages.append(
                            "Apple Health Dropbox ingest has never completed. Please re-authorise Dropbox access."
                        )
                    else:
                        now_utc = datetime.now(timezone.utc)
                        age = now_utc - last_import_ts
                        if age >= timedelta(days=max_stale_days):
                            days_stale = int(age.total_seconds() // 86400)
                            if age.total_seconds() % 86400:
                                days_stale += 1
                            days_stale = max(days_stale, max_stale_days)
                            alert_messages.append(
                                (
                                    f"Apple Health Dropbox has received no new files for {days_stale} day(s). "
                                    "Confirm the automation or run a manual Dropbox import."
                                )
                            )

        try:
            wger_logs_by_date = wger_client.get_logs_by_date(days=days)
        except Exception as e:
            log_utils.log_message(
                f"Failed to retrieve Wger logs for sync window ({days} days): {e}",
                "ERROR",
            )
            failed_sources.append("Wger")
            source_statuses["Wger"] = "failed"
            wger_logs_by_date = {}

        wger_logs_found = False

        for offset in range(days, 0, -1):
            target_day = today - timedelta(days=offset)
            target_iso = target_day.isoformat()
            log_utils.log_message(f"Syncing data for {target_iso}", "INFO")

            # --- Withings ---
            try:
                withings_data = withings_client.get_summary(days_back=offset)
                if withings_data:
                    self.dal.save_withings_daily(
                        day=target_day,
                        weight_kg=withings_data.get("weight"),
                        body_fat_pct=withings_data.get("fat_percent"),
                        muscle_pct=withings_data.get("muscle_percent"),
                        water_pct=withings_data.get("water_percent"),
                    )
            except WithingsReauthRequired as exc:
                log_utils.log_message(f"Withings sync failed for {target_iso}: {exc}", "ERROR")
                failed_sources.append("Withings")
                source_statuses["Withings"] = "failed"

                if getattr(settings, "WITHINGS_ALERT_REAUTH", True) and not withings_reauth_alert_sent:
                    token_state = getattr(withings_client, "get_token_state", lambda: None)()
                    reason_text = getattr(token_state, "reason", None) if token_state else None
                    reason_text = reason_text or str(exc)
                    alert_messages.append(
                        (
                            "Withings refresh token is invalid and needs reauthorisation: "
                            f"{reason_text}. Please run the Withings reauthorisation workflow."
                        )
                    )
                    withings_reauth_alert_sent = True
            except Exception as e:
                log_utils.log_message(f"Withings sync failed for {target_iso}: {e}", "ERROR")
                failed_sources.append("Withings")
                source_statuses["Withings"] = "failed"

                if getattr(settings, "WITHINGS_ALERT_REAUTH", True) and not withings_reauth_alert_sent:
                    token_state = getattr(withings_client, "get_token_state", lambda: None)()
                    if token_state and getattr(token_state, "requires_reauth", False):
                        reason_text = getattr(token_state, "reason", None) or str(e)
                        alert_messages.append(
                            (
                                "Withings refresh token is invalid and needs reauthorisation: "
                                f"{reason_text}. Please run the Withings reauthorisation workflow."
                            )
                        )
                        withings_reauth_alert_sent = True

            # --- Wger Workout Logs ---
            try:
                day_logs = wger_logs_by_date.get(target_iso, [])
                if day_logs:
                    wger_logs_found = True
                    exercise_counters: Dict[Any, int] = {}
                    for log in day_logs:
                        exercise_key = log.get("exercise_id")
                        if exercise_key is None:
                            exercise_key = ("__missing__", len(exercise_counters))
                        set_number = exercise_counters.get(exercise_key, 0) + 1
                        exercise_counters[exercise_key] = set_number

                        self.dal.save_wger_log(
                            day=target_day,
                            exercise_id=log.get("exercise_id"),
                            set_number=set_number,
                            reps=log.get("reps"),
                            weight_kg=log.get("weight"),
                            rir=log.get("rir"),
                        )
            except Exception as e:
                log_utils.log_message(f"Wger sync failed for {target_iso}: {e}", "ERROR")
                failed_sources.append("Wger")
                source_statuses["Wger"] = "failed"

            # --- Body Age Recalculation ---
            try:
                self._recalculate_body_age(target_day)
            except Exception as e:
                log_utils.log_message(f"Body Age calculation failed for {target_iso}: {e}", "ERROR")
                failed_sources.append("BodyAge")
                source_statuses["BodyAge"] = "failed"


        try:
            log_utils.log_message("Refreshing daily_summary view...", "INFO")
            self.dal.refresh_daily_summary_view()
        except Exception as exc:
            log_utils.log_message(f"Failed to refresh daily_summary view: {exc}", "ERROR")
            alert_messages.append("daily_summary view refresh failed; data may be stale.")

        if wger_logs_found:
            log_utils.log_message("Refreshing actual muscle volume view...", "INFO")
            self.dal.refresh_actual_view()

        unique_failures = sorted(set(failed_sources))

        if len(unique_failures) == len(DAILY_SYNC_SOURCES):
            alert_messages.append(
                "Daily sync failed for all sources: " + ', '.join(unique_failures)
            )

        success = not unique_failures

        if success and days == 1 and not alert_messages:
            summary_target = today - timedelta(days=1)
            try:
                self._auto_send_daily_summary(target_date=summary_target)
            except Exception as auto_exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(
                    f"Auto summary dispatch raised an unexpected error for {summary_target.isoformat()}: {auto_exc}",
                    "ERROR",
                )

        if alert_messages:
            alert_text = "\n".join(alert_messages)
            alert_sent = False
            try:
                alert_sent = bool(telegram_sender.send_alert(alert_text))
            except Exception as alert_exc:
                log_utils.log_message(
                    f"Failed to send Telegram alert: {alert_exc}",
                    "ERROR",
                )
                alert_sent = False

            if not alert_sent:
                undelivered_alerts = list(alert_messages)
                combined_alerts = "\n".join(f"- {message}" for message in undelivered_alerts)
                log_utils.log_message(
                    (
                        "Telegram alert dispatch unavailable; pending alerts will be "
                        f"surfaced in automation logs.\n{combined_alerts}"
                    ),
                    "ERROR",
                )

        if success and days == 1:
            try:
                self.dispatch_nudges(reference_date=today)
            except Exception as nudge_exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(
                    f"Failed to dispatch nudges for {today.isoformat()}: {nudge_exc}",
                    "WARN",
                )

        return success, unique_failures, source_statuses, undelivered_alerts
    @_closes_postgres_pool
    def run_end_to_end_day(
        self,
        *,
        days: int = 1,
        summary_date: date | None = None,
    ) -> DailyAutomationResult:
        """Run the daily ingestion flow and ensure a summary is sent."""

        days = max(1, int(days))
        success, failures, statuses, pending_alerts = self.run_daily_sync(days)
        summary_target = summary_date or (date.today() - timedelta(days=1))
        failures_list = list(failures)
        status_map = dict(statuses)
        summary_attempted = False

        already_sent = self.summary_dispatch_ledger.was_sent(summary_target)
        summary_sent = already_sent

        if pending_alerts:
            combined = "\n".join(f"- {message}" for message in pending_alerts)
            log_utils.log_message(
                (
                    "Pending alerts could not be delivered via Telegram and require "
                    f"attention.\n{combined}"
                ),
                "ERROR",
            )

        if not success:
            log_utils.log_message(
                "End-to-end daily flow skipping summary because ingest failed.",
                "WARN",
            )
        elif days != 1:
            log_utils.log_message(
                "End-to-end daily flow ran for multiple days; summary dispatch deferred.",
                "INFO",
            )
        elif failures_list:
            log_utils.log_message(
                "End-to-end daily flow saw source failures; summary will not be resent.",
                "WARN",
            )
        elif already_sent:
            summary_sent = True
        else:
            try:
                summary_attempted = True
                summary_sent = bool(
                    self._auto_send_daily_summary(target_date=summary_target)
                )
            except Exception as exc:  # pragma: no cover - defensive guardrail
                summary_sent = False
                log_utils.log_message(
                    f"End-to-end daily summary send failed for {summary_target.isoformat()}: {exc}",
                    "ERROR",
                )

        return DailyAutomationResult(
            ingest_success=success,
            failed_sources=failures_list,
            source_statuses=status_map,
            summary_target=summary_target,
            summary_sent=summary_sent,
            summary_attempted=summary_attempted,
            undelivered_alerts=list(pending_alerts),
        )

    def _should_run_cycle_rollover(
        self,
        reference_date: date,
        calibration: WeeklyCalibrationResult,
    ) -> bool:
        """Determine whether the weekly flow should trigger a cycle rollover."""

        if getattr(settings, "AUTO_CYCLE_ROLLOVER_ENABLED", True) is False:
            return False

        if reference_date.isoweekday() != 7:
            return False

        interval_raw = getattr(settings, "CYCLE_ROLLOVER_INTERVAL_WEEKS", 4)
        try:
            interval = int(interval_raw)
        except (TypeError, ValueError):
            interval = 4
        if interval <= 0:
            interval = 4

        week_index = reference_date.isocalendar()[1]
        if week_index % interval != 0:
            return False

        return calibration.plan_id is not None
    @_closes_postgres_pool
    def run_end_to_end_week(
        self,
        *,
        reference_date: date | None = None,
        force_rollover: bool = False,
        rollover_weeks: int = 4,
    ) -> WeeklyAutomationResult:
        """Run weekly calibration and, when required, perform cycle rollover."""

        reference = reference_date or date.today()
        weeks = max(1, int(rollover_weeks or 1))

        calibration_result = self.run_weekly_calibration(reference_date=reference)

        try:
            rollover_due = self._should_run_cycle_rollover(
                reference, calibration_result
            )
        except Exception as exc:  # pragma: no cover - defensive guardrail
            log_utils.log_message(
                f"Failed to evaluate cycle rollover predicate: {exc}",
                "ERROR",
            )
            rollover_due = False

        should_rollover = force_rollover or rollover_due
        rollover_result: CycleRolloverResult | None = None
        rollover_triggered = False

        if should_rollover:
            rollover_triggered = True
            try:
                rollover_result = self.run_cycle_rollover(
                    reference_date=reference,
                    weeks=weeks,
                )
            except Exception as exc:  # pragma: no cover - defensive guardrail
                log_utils.log_message(
                    f"Weekly end-to-end rollover failed for {reference.isoformat()}: {exc}",
                    "ERROR",
                )

        return WeeklyAutomationResult(
            calibration=calibration_result,
            rollover=rollover_result,
            rollover_triggered=rollover_triggered,
            reference_date=reference,
        )
    @_closes_postgres_pool
    def run_withings_only_sync(self, days: int) -> Tuple[bool, List[str], Dict[str, str]]:
        """Fetch Withings data for the requested window and update dependent calculations."""
        days = max(1, days)
        today = date.today()
        log_utils.log_message(f"Withings-only sync starting for last {days} days.", "INFO")

        withings_client = WithingsClient()
        failures: List[str] = []
        source_statuses: Dict[str, str] = {name: "ok" for name in WITHINGS_ONLY_SOURCES}

        for offset in range(days, 0, -1):
            target_day = today - timedelta(days=offset)
            target_iso = target_day.isoformat()
            log_utils.log_message(f"Syncing Withings data for {target_iso}", "INFO")

            try:
                withings_data = withings_client.get_summary(days_back=offset)
                if withings_data:
                    self.dal.save_withings_daily(
                        day=target_day,
                        weight_kg=withings_data.get("weight"),
                        body_fat_pct=withings_data.get("fat_percent"),
                        muscle_pct=withings_data.get("muscle_percent"),
                        water_pct=withings_data.get("water_percent"),
                    )
            except Exception as exc:
                log_utils.log_message(f"Withings sync failed for {target_iso}: {exc}", "ERROR")
                failures.append(f"Withings:{target_iso}")
                source_statuses["Withings"] = "failed"
                continue

            try:
                self._recalculate_body_age(target_day)
            except Exception as exc:
                log_utils.log_message(f"Body Age calculation failed for {target_iso}: {exc}", "ERROR")
                failures.append(f"BodyAge:{target_iso}")
                source_statuses["BodyAge"] = "failed"

        return not failures, failures, source_statuses

    def _recalculate_body_age(self, target_day: date) -> None:
        try:
            self.dal.compute_body_age_for_date(
                target_day,
                birth_date=settings.USER_DATE_OF_BIRTH,
            )
            log_utils.log_message(
                f"Body age computed in SQL and upserted for {target_day.isoformat()}",
                "INFO",
            )
        except Exception as e:
            log_utils.log_message(
                f"Body age SQL compute failed for {target_day.isoformat()}: {e}",
                "ERROR",
            )
            # Optionally re-raise in development
            # raise
    @_closes_postgres_pool
    def generate_and_deploy_next_plan(self, start_date: date, weeks: int) -> int:
        """
        Builds and deploys the next training plan cycle.

        Notes
        -----
        Only 4-week blocks are currently supported. Requests for a different
        duration are rejected to avoid implying that variable-length plans are
        available.
        """
        log_utils.log_message(
            f"Generating new {weeks}-week plan starting {start_date.isoformat()}",
            "INFO"
        )

        if weeks != 4:
            log_utils.log_message(
                "Requested plan length of "
                f"{weeks} weeks is not supported (only 4-week plans are available).",
                "ERROR",
            )
            return -1

        try:
            should_build_strength_test = False
            has_any_plan = True
            last_strength_test_date: date | None = None

            plan_checker = getattr(self.dal, "has_any_plan", None)
            if callable(plan_checker):
                try:
                    has_any_plan = bool(plan_checker())
                except Exception as exc:
                    log_utils.log_message(
                        f"Failed to check for existing plans: {exc}",
                        "WARN",
                    )
                    has_any_plan = True

            tm_map: Dict[str, Any] = {}
            try:
                tm_map = plan_rw.latest_training_max()
            except Exception as exc:
                log_utils.log_message(
                    f"Failed to load latest training max values: {exc}",
                    "WARN",
                )

            latest_tm_date_reader = getattr(plan_rw, "latest_training_max_date", None)
            if callable(latest_tm_date_reader):
                try:
                    last_strength_test_date = latest_tm_date_reader()
                except Exception as exc:
                    log_utils.log_message(
                        f"Failed to load latest training max date: {exc}",
                        "WARN",
                    )
            else:
                log_utils.log_message(
                    "Training max date lookup not available; defaulting to strength test schedule",
                    "WARN",
                )

            if not has_any_plan or not tm_map:
                should_build_strength_test = True
            elif last_strength_test_date is None:
                log_utils.log_message(
                    "No historical strength test date found; scheduling test week.",
                    "INFO",
                )
                should_build_strength_test = True
            else:
                next_strength_test_due = last_strength_test_date + timedelta(
                    weeks=STRENGTH_TEST_INTERVAL_WEEKS
                )
                if start_date >= next_strength_test_due:
                    log_utils.log_message(
                        "Strength test due based on last test "
                        f"{last_strength_test_date.isoformat()} and "
                        f"{STRENGTH_TEST_INTERVAL_WEEKS}-week interval.",
                        "INFO",
                    )
                    should_build_strength_test = True

            # Build and persist the plan in one step
            if should_build_strength_test:
                plan_id = build_strength_test(self.dal, start_date)
                plan_kind = "strength test"
            else:
                plan_id = build_block(self.dal, start_date)
                plan_kind = f"{weeks}-week block"

            log_utils.log_message(
                f"Successfully saved new {plan_kind} plan with ID: {plan_id}", "INFO"
            )

            activator = getattr(self.dal, "mark_plan_active", None)
            if callable(activator) and plan_id:
                try:
                    activator(plan_id)
                except Exception as exc:
                    log_utils.log_message(
                        f"Failed to mark plan {plan_id} as active: {exc}",
                        "WARN",
                    )

            if not should_build_strength_test:
                try:
                    progression_decision = calibrate_plan_week(
                        self.dal,
                        plan_id=plan_id,
                        week_number=1,
                        persist=True,
                    )
                except Exception as calibration_error:  # pragma: no cover - log only
                    log_utils.log_message(
                        "Failed to calibrate week 1 for plan "
                        f"{plan_id}: {calibration_error}",
                        "ERROR",
                    )
                else:
                    log_utils.log_message(
                        "Applied progression calibration to week 1 for plan "
                        f"{plan_id}: {progression_decision}",
                        "INFO",
                    )

            # Refresh the plan view to include the new data
            self.dal.refresh_plan_view()

            if should_build_strength_test and plan_id:
                try:
                    wger_sender.push_week(
                        self.dal,
                        plan_id,
                        week=1,
                        start_date=start_date,
                    )
                except Exception as export_error:
                    log_utils.log_message(
                        f"Failed to export strength test plan {plan_id}: {export_error}",
                        "ERROR",
                    )

            return plan_id

        except Exception as e:
            log_utils.log_message(
                f"Failed to generate and deploy new plan: {e}", "ERROR"
            )
            return -1  # Return a sentinel value indicating failure
    @_closes_postgres_pool
    def run_cycle_rollover(
        self,
        *,
        reference_date: date | None = None,
        weeks: int = 4,
    ) -> CycleRolloverResult:
        """Generate the next training cycle and export week one to Wger."""

        today = reference_date or date.today()
        next_start = _next_monday(today)
        log_utils.log_message(
            f"Cycle rollover triggered for {next_start.isoformat()}",
            "INFO",
        )

        plan_id: int | None = None
        created = False

        finder = getattr(self.dal, "find_plan_by_start_date", None)
        existing_plan = None
        if callable(finder):
            try:
                existing_plan = finder(next_start)
            except Exception as exc:
                log_utils.log_message(
                    f"Failed to query existing plan for {next_start.isoformat()}: {exc}",
                    "ERROR",
                )

        if isinstance(existing_plan, dict) and existing_plan.get("id") is not None:
            plan_id = int(existing_plan["id"])
            log_utils.log_message(
                f"Reusing existing plan {plan_id} starting {next_start.isoformat()}",
                "INFO",
            )
        else:
            plan_id = self.generate_and_deploy_next_plan(start_date=next_start, weeks=weeks)
            created = plan_id > 0
            if not created:
                message = f"Cycle rollover failed to generate plan for {next_start.isoformat()}."
                log_utils.log_message(message, "ERROR")
                return CycleRolloverResult(
                    plan_id=None,
                    created=False,
                    exported=False,
                    start_date=next_start,
                    message=message,
                )

        if plan_id is None or plan_id <= 0:
            message = f"Cycle rollover received invalid plan id {plan_id}; aborting export."
            log_utils.log_message(message, "ERROR")
            return CycleRolloverResult(
                plan_id=None,
                created=created,
                exported=False,
                start_date=next_start,
                message=message,
            )

        try:
            push_result = wger_sender.push_week(
                self.dal,
                plan_id,
                week=1,
                start_date=next_start,
            )
        except Exception as exc:
            log_utils.log_message(
                f"Cycle rollover export failed for plan {plan_id}: {exc}",
                "ERROR",
            )
            return CycleRolloverResult(
                plan_id=plan_id,
                created=created,
                exported=False,
                start_date=next_start,
                message=str(exc),
            )

        exported = False
        message: str | None = None

        if isinstance(push_result, dict):
            status = push_result.get("status")
            if status == "exported":
                exported = True
            elif status == "skipped":
                log_utils.log_message(
                    f"Week 1 for plan {plan_id} already exported; skipping Wger push.",
                    "INFO",
                )
            else:
                log_utils.log_message(
                    f"Unexpected rollover push result for plan {plan_id}: {push_result}",
                    "WARN",
                )
        else:
            exported = bool(push_result)

        if exported:
            message = PeteVoice.nudge(
                "#SprintComplete",
                ["I've reviewed the cycle, created the new block, and posted Week 1 to Wger"],
            )
            try:
                self.send_telegram_message(message)
            except Exception as exc:
                log_utils.log_message(
                    f"Failed to send cycle rollover Telegram nudge: {exc}",
                    "WARN",
                )

        return CycleRolloverResult(
            plan_id=plan_id,
            created=created,
            exported=exported,
            start_date=next_start,
            message=message,
        )



