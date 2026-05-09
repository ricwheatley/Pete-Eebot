"""Unified planner domain primitives + Phase 1 context/budget engines."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from pete_e.domain import logging as log_utils


class PlanDecisionReasonCode(str, Enum):
    """Structured reason codes for planner trace events."""

    CONTEXT_ASSEMBLED = "context_assembled"
    BUDGET_COMPUTED = "budget_computed"
    CANDIDATE_GENERATED = "candidate_generated"
    CANDIDATE_REJECTED = "candidate_rejected"
    CONSTRAINT_APPLIED = "constraint_applied"
    WEEK_FINALIZED = "week_finalized"


@dataclass(frozen=True)
class WeeklyStressBudget:
    """Per-week training load target and bounds."""

    target: float
    minimum: float
    maximum: float
    run_target: float = 0.0
    strength_target: float = 0.0
    confidence: float = 0.0
    insufficient_data_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionConstraintSet:
    """Hard and soft constraints used when filtering candidate sessions."""

    max_sessions: int
    min_recovery_days: int
    disallowed_days: tuple[int, ...] = ()


@dataclass(frozen=True)
class GlobalTrainingContext:
    """Planner input context assembled before budgeting and candidate generation."""

    plan_start_date: date
    week_number: int
    readiness_score: float
    historical_weekly_load: float
    constraints: SessionConstraintSet
    goal_phase: str = "build"
    training_maxes: Dict[str, Optional[float]] = field(default_factory=dict)
    recent_running_workouts: tuple[Dict[str, Any], ...] = ()
    historical_health_metrics: tuple[Dict[str, Any], ...] = ()
    recent_strength_workload: float = 0.0
    adherence_ratio: Optional[float] = None
    insufficient_data_flags: tuple[str, ...] = ()


class ContextAssembler:
    """Collect all planning inputs from DAL-like collaborators."""

    def __init__(self, dal: Any) -> None:
        self._dal = dal

    def assemble(self, *, plan_start_date: date, week_number: int, goal_phase: str = "build") -> GlobalTrainingContext:
        flags: list[str] = []
        training_maxes = self._safe_call("get_latest_training_maxes", default={})
        running = self._safe_call("get_recent_running_workouts", default=[], kwargs={"days": 14, "end_date": plan_start_date})
        health = self._safe_call("get_historical_metrics", default=[], args=(21,))
        strength = self._safe_call("get_recent_strength_workouts", default=[], kwargs={"days": 14, "end_date": plan_start_date})
        adherence = self._safe_call("get_recent_adherence_signal", default=None, kwargs={"days": 21, "end_date": plan_start_date})
        readiness_score = self._derive_readiness_score(health)
        historical_weekly_load = self._estimate_historical_weekly_load(running, strength)
        strength_workload = self._estimate_strength_workload(strength)
        if not training_maxes:
            flags.append("missing_training_maxes")
        if len(running) < 2:
            flags.append("limited_running_history")
        if len(health) < 7:
            flags.append("limited_health_history")
        if len(strength) < 2:
            flags.append("limited_strength_history")
        return GlobalTrainingContext(
            plan_start_date=plan_start_date,
            week_number=week_number,
            readiness_score=readiness_score,
            historical_weekly_load=historical_weekly_load,
            constraints=SessionConstraintSet(max_sessions=5, min_recovery_days=1),
            goal_phase=goal_phase,
            training_maxes=training_maxes,
            recent_running_workouts=tuple(running),
            historical_health_metrics=tuple(health),
            recent_strength_workload=strength_workload,
            adherence_ratio=adherence,
            insufficient_data_flags=tuple(flags),
        )

    def _safe_call(self, fn_name: str, *, default: Any, args: tuple[Any, ...] = (), kwargs: Optional[dict[str, Any]] = None) -> Any:
        fn = getattr(self._dal, fn_name, None)
        if not callable(fn):
            return default
        return fn(*args, **(kwargs or {}))

    def _derive_readiness_score(self, history: List[Dict[str, Any]]) -> float:
        if not history:
            return 0.5
        latest = history[-1] if isinstance(history[-1], dict) else {}
        hrv = float(latest.get("hrv_recovery_score") or latest.get("hrv_score") or 50.0)
        body = float(latest.get("body_battery") or latest.get("recovery_score") or 50.0)
        return max(0.0, min(1.0, ((hrv + body) / 2.0) / 100.0))

    def _estimate_historical_weekly_load(self, running: List[Dict[str, Any]], strength: List[Dict[str, Any]]) -> float:
        run_points = sum(float(w.get("duration_sec", 0.0)) / 60.0 for w in running)
        strength_points = sum(float(w.get("volume_kg", 0.0)) / 100.0 for w in strength)
        return round((run_points + strength_points) / 2.0, 1)

    def _estimate_strength_workload(self, strength: List[Dict[str, Any]]) -> float:
        return round(sum(float(w.get("volume_kg", 0.0)) for w in strength), 1)


class StressBudgetEngine:
    """Allocate weekly stress budget by readiness and phase."""

    def compute(self, context: GlobalTrainingContext) -> WeeklyStressBudget:
        readiness = context.readiness_score
        base = max(40.0, context.historical_weekly_load or 80.0)
        if readiness >= 0.7:
            total = base * 1.1
        elif readiness >= 0.4:
            total = base * 0.95
        else:
            total = base * 0.75
        phase_split = {"build": 0.55, "peak": 0.65, "deload": 0.45}.get(context.goal_phase, 0.55)
        if readiness < 0.4:
            phase_split = min(phase_split, 0.50)
        run_target = total * phase_split
        strength_target = total - run_target
        flag_count = len(context.insufficient_data_flags)
        confidence = max(0.2, min(1.0, 0.95 - (0.15 * flag_count)))
        return WeeklyStressBudget(
            target=round(total, 1),
            minimum=round(total * 0.85, 1),
            maximum=round(total * 1.15, 1),
            run_target=round(run_target, 1),
            strength_target=round(strength_target, 1),
            confidence=round(confidence, 2),
            insufficient_data_flags=context.insufficient_data_flags,
        )


@dataclass(frozen=True)
class PlanDecisionTrace:
    """Serializable, structured trace message for planner decisions."""

    week_number: int
    stage: str
    reason_code: PlanDecisionReasonCode
    detail: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["reason_code"] = self.reason_code.value
        return data


class UnifiedLoadCoordinator:
    """Unified planner load coordinator with deterministic constraint execution."""

    def __init__(self, *, context_assembler: Optional[ContextAssembler] = None, stress_budget_engine: Optional[StressBudgetEngine] = None) -> None:
        self._decision_trace: List[PlanDecisionTrace] = []
        self._context_assembler = context_assembler
        self._stress_budget_engine = stress_budget_engine or StressBudgetEngine()

    @property
    def decision_trace(self) -> Sequence[PlanDecisionTrace]:
        return tuple(self._decision_trace)

    def assemble_context(self, *, plan_start_date: date, week_number: int, goal_phase: str = "build") -> GlobalTrainingContext:
        """Build minimal global context for a planning week."""

        context = (
            self._context_assembler.assemble(
                plan_start_date=plan_start_date,
                week_number=week_number,
                goal_phase=goal_phase,
            )
            if self._context_assembler
            else GlobalTrainingContext(
                plan_start_date=plan_start_date,
                week_number=week_number,
                readiness_score=0.5,
                historical_weekly_load=80.0,
                constraints=SessionConstraintSet(max_sessions=5, min_recovery_days=1),
            )
        )
        self._emit_trace(
            PlanDecisionTrace(
                week_number=week_number,
                stage="assemble_context",
                reason_code=PlanDecisionReasonCode.CONTEXT_ASSEMBLED,
                detail="Created baseline planning context.",
                payload={"readiness_score": context.readiness_score, "insufficient_data_flags": list(context.insufficient_data_flags)},
            )
        )
        return context

    def compute_budget(self, context: GlobalTrainingContext) -> WeeklyStressBudget:
        """Compute initial stress budget from the global context."""

        budget = self._stress_budget_engine.compute(context)
        self._emit_trace(
            PlanDecisionTrace(
                week_number=context.week_number,
                stage="compute_budget",
                reason_code=PlanDecisionReasonCode.BUDGET_COMPUTED,
                detail="Computed placeholder weekly stress budget.",
                payload=asdict(budget),
            )
        )
        return budget

    def generate_candidates(
        self,
        context: GlobalTrainingContext,
        budget: WeeklyStressBudget,
    ) -> List[Dict[str, Any]]:
        """Generate candidate sessions prior to constraint filtering."""

        candidates: List[Dict[str, Any]] = []
        self._emit_trace(
            PlanDecisionTrace(
                week_number=context.week_number,
                stage="generate_candidates",
                reason_code=PlanDecisionReasonCode.CANDIDATE_GENERATED,
                detail="Generated placeholder candidate set.",
                payload={"candidate_count": len(candidates), "budget_target": budget.target},
            )
        )
        return candidates

    def apply_constraints(
        self,
        context: GlobalTrainingContext,
        candidates: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Apply constraints to candidate sessions and return feasible sessions."""

        feasible = [dict(candidate) for candidate in candidates]
        ordered_constraints = (
            self._apply_long_run_vs_lower_strength_volume,
            self._apply_heavy_strength_vs_run_quality,
            self._apply_bilateral_recovery_backoff,
            self._apply_hard_session_spacing,
        )
        for fn in ordered_constraints:
            feasible = fn(context, feasible)
        self._emit_trace(
            PlanDecisionTrace(
                week_number=context.week_number,
                stage="apply_constraints",
                reason_code=PlanDecisionReasonCode.CONSTRAINT_APPLIED,
                detail="Applied unified weekly constraints in deterministic order.",
                payload={"input_count": len(candidates), "feasible_count": len(feasible)},
            )
        )
        return feasible

    def _apply_long_run_vs_lower_strength_volume(self, context: GlobalTrainingContext, sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        long_run = next((s for s in sessions if s.get("session_type") == "long_run"), None)
        lower_strength = [s for s in sessions if s.get("session_type") == "strength" and s.get("lower_body") is True]
        if not long_run or not lower_strength:
            return sessions
        if float(long_run.get("stress", 0.0)) < 8.0:
            return sessions
        adjusted = 0
        for session in lower_strength:
            volume = int(session.get("volume_sets", 0))
            if volume > 4:
                session["volume_sets"] = 4
                adjusted += 1
        if adjusted:
            self._emit_trace(PlanDecisionTrace(
                week_number=context.week_number,
                stage="constraint_long_run_lower_strength",
                reason_code=PlanDecisionReasonCode.CONSTRAINT_APPLIED,
                detail="Long run load reduced lower-body strength volume.",
                payload={"adjusted_sessions": adjusted},
            ))
        return sessions

    def _apply_heavy_strength_vs_run_quality(self, context: GlobalTrainingContext, sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        heavy_week = any(s.get("session_type") == "strength" and s.get("intensity_tag") == "heavy_top_set" for s in sessions)
        if not heavy_week:
            return sessions
        adjusted = 0
        for session in sessions:
            if session.get("session_type") == "run" and session.get("quality") == "high":
                session["quality"] = "moderate"
                session["stress"] = max(0.0, float(session.get("stress", 0.0)) - 2.0)
                adjusted += 1
        if adjusted:
            self._emit_trace(PlanDecisionTrace(
                week_number=context.week_number,
                stage="constraint_heavy_strength_run_quality",
                reason_code=PlanDecisionReasonCode.CONSTRAINT_APPLIED,
                detail="Heavy strength week reduced high-quality run intensity.",
                payload={"adjusted_sessions": adjusted},
            ))
        return sessions

    def _apply_bilateral_recovery_backoff(self, context: GlobalTrainingContext, sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if context.readiness_score >= 0.7:
            return sessions
        state = "amber" if context.readiness_score >= 0.4 else "red"
        strength_adj = 0
        run_adj = 0
        for session in sessions:
            if session.get("session_type") == "strength":
                session["stress"] = round(float(session.get("stress", 0.0)) * 0.85, 2)
                strength_adj += 1
            if session.get("session_type") in {"run", "long_run"}:
                session["stress"] = round(float(session.get("stress", 0.0)) * 0.85, 2)
                run_adj += 1
        if strength_adj or run_adj:
            self._emit_trace(PlanDecisionTrace(
                week_number=context.week_number,
                stage="constraint_bilateral_recovery_backoff",
                reason_code=PlanDecisionReasonCode.CONSTRAINT_APPLIED,
                detail="Readiness backoff lowered both strength and run stress.",
                payload={"readiness_state": state, "strength_adjusted": strength_adj, "run_adjusted": run_adj},
            ))
        return sessions

    def _apply_hard_session_spacing(self, context: GlobalTrainingContext, sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        heavy_days = {
            int(s.get("day_of_week"))
            for s in sessions
            if s.get("session_type") == "strength" and s.get("lift") in {"squat", "deadlift"} and s.get("intensity_tag") == "heavy_top_set"
        }
        if not heavy_days:
            return sessions
        dropped = 0
        kept: List[Dict[str, Any]] = []
        for session in sessions:
            if session.get("session_type") == "run" and session.get("quality") in {"high", "moderate"} and float(session.get("stress", 0.0)) >= 5.0 and not session.get("override_spacing"):
                run_day = int(session.get("day_of_week"))
                if any(abs(run_day - heavy_day) <= 1 for heavy_day in heavy_days):
                    dropped += 1
                    continue
            kept.append(session)
        if dropped:
            self._emit_trace(PlanDecisionTrace(
                week_number=context.week_number,
                stage="constraint_hard_session_spacing",
                reason_code=PlanDecisionReasonCode.CONSTRAINT_APPLIED,
                detail="Removed high-intensity run within 24h of heavy squat/deadlift.",
                payload={"removed_sessions": dropped},
            ))
        return kept

    def finalize_week(
        self,
        context: GlobalTrainingContext,
        feasible_sessions: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Finalize week output and emit closing decision trace."""

        finalized = list(feasible_sessions)
        self._emit_trace(
            PlanDecisionTrace(
                week_number=context.week_number,
                stage="finalize_week",
                reason_code=PlanDecisionReasonCode.WEEK_FINALIZED,
                detail="Finalized placeholder week output.",
                payload={"session_count": len(finalized)},
            )
        )
        return finalized

    def _emit_trace(self, trace: PlanDecisionTrace) -> None:
        self._decision_trace.append(trace)
        log_utils.info(f"plan_decision_trace={trace.to_dict()}")
