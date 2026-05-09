# pete_e/domain/plan_factory.py
"""
Contains the business logic for constructing different types of training plans.
This factory creates in-memory representations of plans, which are then
persisted by an application service.
"""
from __future__ import annotations
import random
from datetime import date
from typing import Dict, Any, List, Optional

from pete_e.domain import schedule_rules
from pete_e.domain.repositories import PlanRepository
from pete_e.domain.running_planner import RunningGoal, RunningPlanner
from pete_e.domain.unified_load_coordinator import GlobalTrainingContext, SessionConstraintSet, UnifiedLoadCoordinator, WeeklyStressBudget

class PlanFactory:
    """Creates structured, in-memory representations of training plans."""

    def __init__(self, plan_repository: PlanRepository):
        """
        Requires a PlanRepository to fetch necessary data like assistance pools
        and core exercise IDs.
        """
        self.plan_repository = plan_repository
        self.running_planner = RunningPlanner()
        self.unified_load_coordinator = UnifiedLoadCoordinator()

    def _pick_random(self, items: List[Any], k: int) -> List[Any]:
        """Safely picks k random items from a list."""
        if not items:
            return []
        k = min(k, len(items))
        return random.sample(items, k)

    def _round_to_2p5(self, value: float) -> float:
        """Rounds a weight value to the nearest 2.5kg."""
        return round(value / 2.5) * 2.5

    def _get_target_weight(self, tms: Dict[str, float], lift_id: int, percent: float) -> Optional[float]:
        """Calculates the target weight from a training max and percentage."""
        lift_code = schedule_rules.LIFT_CODE_BY_ID.get(lift_id)
        if not lift_code:
            return None
        
        training_max = tms.get(lift_code)
        if training_max is None:
            return None
            
        return self._round_to_2p5(training_max * percent / 100.0)

    def _workout_sort_key(self, workout: Dict[str, Any]) -> tuple[int, int, str]:
        details = workout.get("details")
        return (
            int(workout.get("day_of_week") or 0),
            schedule_rules.workout_display_order(
                is_cardio=bool(workout.get("is_cardio")),
                exercise_id=workout.get("exercise_id"),
                workout_type=workout.get("type"),
                details=details if isinstance(details, dict) else None,
            ),
            str(workout.get("scheduled_time") or ""),
        )
        """Perform workout sort key."""

    def create_unified_531_block_plan(
        self,
        start_date: date,
        training_maxes: Dict[str, float],
        *,
        running_goal: RunningGoal | None = None,
        health_metrics: List[Dict[str, Any]] | None = None,
        recent_runs: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """Build a 4-week 5/3/1 block via the unified coordinator."""
        weeks_in_plan = 4
        plan_weeks: List[Dict[str, Any]] = []
        trace_by_week: Dict[str, List[Dict[str, Any]]] = {}

        # Fetch assistance/core pools once
        core_ids = self.plan_repository.get_core_pool_ids() or schedule_rules.DEFAULT_CORE_POOL_IDS

        for week_num in range(1, weeks_in_plan + 1):
            is_deload_week = (week_num == 4)
            week_workouts: List[Dict[str, Any]] = []

            for dow, main_lift_id in schedule_rules.MAIN_LIFT_BY_DOW.items():
                # 1. Add Cardio/Blaze Session
                blaze_time = schedule_rules.BLAZE_TIMES.get(dow)
                if blaze_time:
                    week_workouts.append({
                        "day_of_week": dow, "exercise_id": schedule_rules.BLAZE_ID,
                        "sets": 1, "reps": 1, "is_cardio": True,
                        "scheduled_time": blaze_time.strftime("%H:%M:%S")
                    })

                # 2. Add Main Lift (classic 5/3/1 sets)
                slot_time = schedule_rules.weight_slot_for_day(dow)
                slot_str = slot_time.strftime("%H:%M:%S") if slot_time else None
                for set_scheme in schedule_rules.get_main_set_scheme(week_num):
                    percent = set_scheme["percent"]
                    target_weight = self._get_target_weight(training_maxes, main_lift_id, percent)
                    week_workouts.append({
                        "day_of_week": dow,
                        "exercise_id": main_lift_id,
                        "sets": set_scheme.get("sets", 1),
                        "reps": set_scheme["reps"],
                        "percent_1rm": percent,
                        "rir_cue": set_scheme.get("rir"),
                        "target_weight_kg": target_weight,
                        "is_cardio": False,
                        "scheduled_time": slot_str,
                    })
                
                # 3. Add Assistance Lifts
                assistance_ids = self.plan_repository.get_assistance_pool_for(main_lift_id)
                if not assistance_ids:
                    assistance_ids = schedule_rules.default_assistance_for(main_lift_id)
                chosen_assistance = self._pick_random(assistance_ids, 2)
                
                if chosen_assistance:
                    a1_scheme = schedule_rules.ASSISTANCE_1
                    week_workouts.append({
                        "day_of_week": dow, "exercise_id": chosen_assistance[0],
                        "sets": a1_scheme["sets"] - (1 if is_deload_week else 0),
                        "reps": a1_scheme["reps_low"], "rir_cue": a1_scheme["rir_cue"], "is_cardio": False,
                        "scheduled_time": slot_str,
                    })
                if len(chosen_assistance) > 1:
                    a2_scheme = schedule_rules.ASSISTANCE_2
                    week_workouts.append({
                        "day_of_week": dow, "exercise_id": chosen_assistance[1],
                        "sets": a2_scheme["sets"] - (1 if is_deload_week else 0),
                        "reps": a2_scheme["reps_low"], "rir_cue": a2_scheme["rir_cue"], "is_cardio": False,
                        "scheduled_time": slot_str,
                    })

                # 4. Add Core Work
                chosen_core = self._pick_random(core_ids, 1)
                if chosen_core:
                    core_scheme = schedule_rules.CORE_SCHEME
                    week_workouts.append({
                        "day_of_week": dow, "exercise_id": chosen_core[0],
                        "sets": core_scheme["sets"] - (1 if is_deload_week else 0),
                        "reps": core_scheme["reps_low"], "rir_cue": core_scheme["rir_cue"], "is_cardio": False,
                        "scheduled_time": slot_str,
                    })

            run_workouts = self.running_planner.build_week_sessions(
                week_number=week_num,
                goal=running_goal,
                health_metrics=health_metrics,
                recent_runs=recent_runs,
                plan_start_date=start_date,
            )
            strength_candidates = [self._strength_candidate_from_workout(item) for item in week_workouts if not item.get("is_cardio")]
            run_candidates = [self._run_candidate_from_workout(item) for item in run_workouts]
            context = self.unified_load_coordinator.assemble_context(
                plan_start_date=start_date,
                week_number=week_num,
                goal_phase="deload" if is_deload_week else "build",
            )
            context = GlobalTrainingContext(
                **{**context.__dict__, "constraints": SessionConstraintSet(max_sessions=64, min_recovery_days=1)}
            )
            budget = self.unified_load_coordinator.compute_budget(context)
            candidates = self.unified_load_coordinator.generate_candidates(context, budget, strength_candidates=strength_candidates, run_candidates=run_candidates)
            feasible = self.unified_load_coordinator.apply_constraints(context, candidates)
            finalized = self.unified_load_coordinator.finalize_week(context, feasible, budget)
            trace_by_week[str(week_num)] = [item.to_dict() for item in self.unified_load_coordinator.decision_trace if item.week_number == week_num]
            week_workouts = [w for w in week_workouts if not self._is_strength_workout_filtered(w, finalized)]
            week_workouts.extend(self._workout_from_candidate(candidate) for candidate in finalized if candidate.get("source") == "run")

            for dow in sorted(schedule_rules.TRAINING_DAY_STRETCH_ROUTINE_BY_DOW):
                stretch_details = schedule_rules.stretch_routine_for_day(dow)
                if not stretch_details:
                    continue
                week_workouts.append(
                    {
                        "day_of_week": dow,
                        "exercise_id": None,
                        "exercise_name": stretch_details["display_name"],
                        "sets": 0,
                        "reps": 0,
                        "is_cardio": False,
                        "type": schedule_rules.MOBILITY_WORKOUT_TYPE,
                        "comment": stretch_details["display_name"],
                        "recovery_focused": True,
                        "details": stretch_details,
                    }
                )

            week_workouts.sort(key=self._workout_sort_key)

            plan_weeks.append({"week_number": week_num, "workouts": week_workouts})

        return {
            "start_date": start_date,
            "weeks": weeks_in_plan,
            "plan_weeks": plan_weeks,
            "metadata": {
                "planner_version": "unified_load_coordinator_v1",
                "plan_decision_trace": trace_by_week,
            },
        }

    def create_531_block_plan(
        self,
        start_date: date,
        training_maxes: Dict[str, float],
        *,
        running_goal: RunningGoal | None = None,
        health_metrics: List[Dict[str, Any]] | None = None,
        recent_runs: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """Backward-compatible alias for unified 5/3/1 block planning."""
        return self.create_unified_531_block_plan(
            start_date,
            training_maxes,
            running_goal=running_goal,
            health_metrics=health_metrics,
            recent_runs=recent_runs,
        )

    def _strength_candidate_from_workout(self, workout: Dict[str, Any]) -> Dict[str, Any]:
        lift = schedule_rules.LIFT_CODE_BY_ID.get(workout.get("exercise_id"), "")
        return {
            "source": "strength",
            "workout": workout,
            "session_type": "strength",
            "day_of_week": workout.get("day_of_week"),
            "lower_body": lift in {"squat", "deadlift"},
            "lift": lift,
            "intensity_tag": "heavy_top_set" if workout.get("percent_1rm", 0) >= 85 else "moderate",
            "volume_sets": int(workout.get("sets") or 1),
            "stress": float(workout.get("sets") or 1) * (1.8 if lift in {"squat", "deadlift"} else 1.2),
        }

    def _run_candidate_from_workout(self, workout: Dict[str, Any]) -> Dict[str, Any]:
        comment = str(workout.get("comment") or "").lower()
        session_type = "long_run" if "long run" in comment else "run"
        quality = "high" if "quality" in comment else ("moderate" if "aerobic" in comment else "easy")
        stress = 7.0 if session_type == "long_run" else (6.0 if quality == "high" else 4.0)
        return {
            "source": "run",
            "workout": workout,
            "session_type": session_type,
            "day_of_week": workout.get("day_of_week"),
            "quality": quality,
            "stress": stress,
            "optional": bool(workout.get("optional")),
        }

    def _is_strength_workout_filtered(self, workout: Dict[str, Any], finalized: List[Dict[str, Any]]) -> bool:
        if workout.get("is_cardio"):
            return False
        included = {id(item.get("workout")) for item in finalized if item.get("source") == "strength"}
        return id(workout) not in included

    def _workout_from_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        return dict(candidate.get("workout") or {})

    def create_strength_test_plan(self, start_date: date, training_maxes: Dict[str, float]) -> Dict[str, Any]:
        """Builds a 1-week AMRAP strength test plan. Returns a structured dictionary."""
        week_workouts: List[Dict[str, Any]] = []

        # Add Blaze entries
        for dow, blaze_time in schedule_rules.BLAZE_TIMES.items():
            week_workouts.append({
                "day_of_week": dow, "exercise_id": schedule_rules.BLAZE_ID,
                "sets": 1, "reps": 1, "is_cardio": True, "scheduled_time": blaze_time.strftime("%H:%M:%S")
            })
        
        # Add AMRAP test main lifts
        for dow, ex_id in zip([1, 2, 4, 5], schedule_rules.TEST_WEEK_LIFT_ORDER):
            percent = schedule_rules.TEST_WEEK_PCTS[ex_id]
            target_weight = self._get_target_weight(training_maxes, ex_id, percent)
            week_workouts.append({
                "day_of_week": dow, "exercise_id": ex_id, "sets": 1, "reps": 1, "slot": "main",
                "percent_1rm": percent, "target_weight_kg": target_weight, "is_cardio": False,
                "scheduled_time": schedule_rules.weight_slot_for_day(dow).strftime("%H:%M:%S"),
                "comment": "AMRAP Test"
            })
        
        plan_week = {"week_number": 1, "workouts": week_workouts, "is_test": True}
        return {"start_date": start_date, "weeks": 1, "plan_weeks": [plan_week]}
