BEGIN;

CREATE TABLE IF NOT EXISTS core_pool (
    exercise_id INT PRIMARY KEY REFERENCES wger_exercise(id) ON DELETE CASCADE
);

COMMENT ON TABLE core_pool IS 'Operator-managed pool of core exercises used during plan generation.';

WITH ranked_active_plans AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY id DESC) AS row_num
    FROM training_plans
    WHERE is_active = true
)
UPDATE training_plans
SET is_active = false
WHERE id IN (
    SELECT id
    FROM ranked_active_plans
    WHERE row_num > 1
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_training_plans_single_active
    ON training_plans (is_active)
    WHERE is_active = true;

COMMIT;
