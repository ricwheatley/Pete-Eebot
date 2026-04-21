BEGIN;

ALTER TABLE training_plan_workouts
    ALTER COLUMN exercise_id DROP NOT NULL;

CREATE OR REPLACE FUNCTION sp_plan_for_day(p_date DATE)
RETURNS TABLE (
    workout_date DATE,
    scheduled_time TIME,
    exercise_name TEXT,
    sets INT,
    reps INT,
    target_weight_kg NUMERIC
) LANGUAGE sql AS $$
    SELECT p_date::date AS workout_date,
           tpw.scheduled_time,
           COALESCE(tpw.details->>'display_name', NULLIF(tpw.comment, ''), e.name, 'Planned session') AS exercise_name,
           tpw.sets,
           tpw.reps,
           tpw.target_weight_kg
    FROM training_plan_workouts tpw
    JOIN training_plan_weeks tw ON tpw.week_id = tw.id
    JOIN training_plans tp ON tw.plan_id = tp.id
    LEFT JOIN wger_exercise e ON tpw.exercise_id = e.id
    WHERE tp.is_active = TRUE
      AND tp.start_date <= p_date
      AND (tp.start_date + ((tw.week_number + 1) * 7)) > p_date
      AND tpw.day_of_week = extract(isodow from p_date);
$$;


CREATE OR REPLACE FUNCTION sp_plan_for_week(p_start_date DATE)
RETURNS TABLE (
    workout_date DATE,
    day_of_week INT,
    scheduled_time TIME,
    exercise_name TEXT,
    sets INT,
    reps INT,
    target_weight_kg NUMERIC
) LANGUAGE sql AS $$
    SELECT (p_start_date + (tpw.day_of_week - 1))::date AS workout_date,
           tpw.day_of_week,
           tpw.scheduled_time,
           COALESCE(tpw.details->>'display_name', NULLIF(tpw.comment, ''), e.name, 'Planned session') AS exercise_name,
           tpw.sets,
           tpw.reps,
           tpw.target_weight_kg
    FROM training_plan_workouts tpw
    JOIN training_plan_weeks tw ON tpw.week_id = tw.id
    JOIN training_plans tp ON tw.plan_id = tp.id
    LEFT JOIN wger_exercise e ON tpw.exercise_id = e.id
    WHERE tp.is_active = TRUE
      AND tp.start_date <= p_start_date
      AND (tp.start_date + ((tw.week_number + 1) * 7)) > p_start_date
    ORDER BY
        tpw.day_of_week,
        COALESCE((tpw.details ->> 'sequence_order')::int, CASE WHEN tpw.is_cardio THEN 15 ELSE 20 END),
        tpw.scheduled_time;
$$;

COMMIT;
