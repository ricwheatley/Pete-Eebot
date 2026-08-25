-- New percentage-based strength prescriptions must always have a usable load.
-- NOT VALID preserves deployability when an installation contains historical
-- rows that need the explicit repair workflow; PostgreSQL still enforces the
-- constraint for all new and updated rows.
ALTER TABLE training_plan_workouts
    DROP CONSTRAINT IF EXISTS training_plan_workouts_percentage_target_positive;

ALTER TABLE training_plan_workouts
    ADD CONSTRAINT training_plan_workouts_percentage_target_positive
    CHECK (
        is_cardio
        OR percent_1rm IS NULL
        OR (
            percent_1rm > 0
            AND target_weight_kg IS NOT NULL
            AND target_weight_kg > 0
        )
    ) NOT VALID;

COMMENT ON CONSTRAINT training_plan_workouts_percentage_target_positive
    ON training_plan_workouts IS
    'Percentage-based strength rows require positive percentages and target loads; historical invalid rows must be repaired before validation.';
