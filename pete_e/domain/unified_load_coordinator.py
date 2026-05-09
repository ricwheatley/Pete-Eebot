"""Phase 0 unified planner domain primitives and coordinator skeleton."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Sequence

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
    """Phase 0 skeleton for the unified planner load coordinator."""

    def __init__(self) -> None:
        self._decision_trace: List[PlanDecisionTrace] = []

    @property
    def decision_trace(self) -> Sequence[PlanDecisionTrace]:
        return tuple(self._decision_trace)

    def assemble_context(self, *, plan_start_date: date, week_number: int) -> GlobalTrainingContext:
        """Build minimal global context for a planning week."""

        context = GlobalTrainingContext(
            plan_start_date=plan_start_date,
            week_number=week_number,
            readiness_score=0.5,
            historical_weekly_load=0.0,
            constraints=SessionConstraintSet(max_sessions=5, min_recovery_days=1),
        )
        self._emit_trace(
            PlanDecisionTrace(
                week_number=week_number,
                stage="assemble_context",
                reason_code=PlanDecisionReasonCode.CONTEXT_ASSEMBLED,
                detail="Created baseline planning context.",
                payload={"readiness_score": context.readiness_score},
            )
        )
        return context

    def compute_budget(self, context: GlobalTrainingContext) -> WeeklyStressBudget:
        """Compute initial stress budget from the global context."""

        budget = WeeklyStressBudget(target=100.0, minimum=75.0, maximum=125.0)
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

        feasible = list(candidates)
        self._emit_trace(
            PlanDecisionTrace(
                week_number=context.week_number,
                stage="apply_constraints",
                reason_code=PlanDecisionReasonCode.CONSTRAINT_APPLIED,
                detail="Applied placeholder constraint pass-through.",
                payload={"input_count": len(candidates), "feasible_count": len(feasible)},
            )
        )
        return feasible

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
