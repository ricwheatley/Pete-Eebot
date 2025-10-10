# pete_e/domain/plan_factory.py
"""
Contains the business logic for constructing different types of training plans.
This factory creates in-memory representations of plans, which are then
persisted by an application service.
"""
from __future__ import annotations
import random
from datetime import date, time
from typing import Dict, Any, List, Optional

from pete_e.domain import schedule_rules
from pete_e.domain.repositories import PlanRepository

class PlanFactory:
    """Creates structured, in-memory representations of training plans."""

    def __init__(self, plan_repository: PlanRepository):
        """
        Requires a PlanRepository to fetch necessary data like assistance pools
        and core exercise IDs.
        """
        self.plan_repository = plan_repository

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

    def create_531_block_plan(self, start_date: date, training_maxes: Dict[str, float]) -> Dict[str, Any]:
        """
        Builds a 4-week, 5/3/1 training block. Returns a structured dictionary
        representing the full plan, ready for persistence.
        (Logic migrated from plan_builder.py and orchestrator.py)
        """
        weeks_in_plan = 4
        plan_weeks: List[Dict[str, Any]] = []

        # Fetch assistance/core pools once
        core_ids = self.plan_repository.get_core_pool_ids()

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

                # 2. Add Main Lift
                main_lift_scheme = schedule_rules.WEEK_PCTS[week_num]
                target_weight = self._get_target_weight(training_maxes, main_lift_id, main_lift_scheme["percent_1rm"])
                week_workouts.append({
                    "day_of_week": dow, "exercise_id": main_lift_id,
                    "sets": main_lift_scheme["sets"], "reps": main_lift_scheme["reps"],
                    "percent_1rm": main_lift_scheme["percent_1rm"], "rir_cue": main_lift_scheme["rir_cue"],
                    "target_weight_kg": target_weight, "is_cardio": False,
                    "scheduled_time": schedule_rules.weight_slot_for_day(dow).strftime("%H:%M:%S")
                })
                
                # 3. Add Assistance Lifts
                assistance_ids = self.plan_repository.get_assistance_pool_for(main_lift_id)
                chosen_assistance = self._pick_random(assistance_ids, 2)
                
                if chosen_assistance:
                    a1_scheme = schedule_rules.ASSISTANCE_1
                    week_workouts.append({
                        "day_of_week": dow, "exercise_id": chosen_assistance[0],
                        "sets": a1_scheme["sets"] - (1 if is_deload_week else 0),
                        "reps": a1_scheme["reps_low"], "rir_cue": a1_scheme["rir_cue"], "is_cardio": False,
                        "scheduled_time": schedule_rules.weight_slot_for_day(dow).strftime("%H:%M:%S")
                    })
                if len(chosen_assistance) > 1:
                    a2_scheme = schedule_rules.ASSISTANCE_2
                    week_workouts.append({
                        "day_of_week": dow, "exercise_id": chosen_assistance[1],
                        "sets": a2_scheme["sets"] - (1 if is_deload_week else 0),
                        "reps": a2_scheme["reps_low"], "rir_cue": a2_scheme["rir_cue"], "is_cardio": False,
                        "scheduled_time": schedule_rules.weight_slot_for_day(dow).strftime("%H:%M:%S")
                    })

                # 4. Add Core Work
                chosen_core = self._pick_random(core_ids, 1)
                if chosen_core:
                    core_scheme = schedule_rules.CORE_SCHEME
                    week_workouts.append({
                        "day_of_week": dow, "exercise_id": chosen_core[0],
                        "sets": core_scheme["sets"] - (1 if is_deload_week else 0),
                        "reps": core_scheme["reps_low"], "rir_cue": core_scheme["rir_cue"], "is_cardio": False,
                        "scheduled_time": schedule_rules.weight_slot_for_day(dow).strftime("%H:%M:%S")
                    })

            plan_weeks.append({"week_number": week_num, "workouts": week_workouts})

        return {"start_date": start_date, "weeks": weeks_in_plan, "plan_weeks": plan_weeks}

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