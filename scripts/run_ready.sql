WITH ref AS (
  SELECT COALESCE(
    (SELECT max(date) FROM daily_summary),
    (SELECT max(start_time)::date FROM "Workout"),
    current_date
  )::date AS as_of
),
runs_base AS (
  SELECT
    w.start_time::date AS workout_date,
    w.start_time,
    wt.name AS workout_type,
    w.duration_sec,
    w.total_distance_km,
    ROUND((w.duration_sec / 60.0 / NULLIF(w.total_distance_km, 0))::numeric, 2) AS pace_min_per_km,
    ROUND(avg(hr.hr_avg)::numeric, 1) AS avg_hr,
    max(hr.hr_max) AS max_hr,
    ROUND(w.elevation_gain_m::numeric, 1) AS elevation_gain_m
  FROM "Workout" w
  JOIN "WorkoutType" wt ON wt.type_id = w.type_id
  LEFT JOIN "WorkoutHeartRate" hr ON hr.workout_id = w.workout_id
  CROSS JOIN ref r
  WHERE w.start_time::date >= r.as_of - INTERVAL '180 days'
    AND w.total_distance_km IS NOT NULL
    AND w.total_distance_km > 0
    AND (
      lower(wt.name) LIKE '%run%'
      OR lower(wt.name) LIKE '%jog%'
    )
  GROUP BY
    w.workout_id, w.start_time, wt.name, w.duration_sec,
    w.total_distance_km, w.elevation_gain_m
),
rollups AS (
  SELECT
    window_days,
    count(ds.date) AS days_with_summary,
    ROUND(avg(ds.steps)::numeric, 0) AS avg_steps,
    ROUND(avg(ds.exercise_minutes)::numeric, 1) AS avg_exercise_minutes,
    ROUND(avg(ds.distance_m / 1000.0)::numeric, 2) AS avg_daily_distance_km,
    ROUND(avg(ds.hr_resting)::numeric, 1) AS avg_resting_hr,
    ROUND(avg(ds.hrv_sdnn_ms)::numeric, 1) AS avg_hrv_sdnn_ms,
    ROUND(avg(ds.vo2_max)::numeric, 1) AS avg_vo2_max,
    ROUND(avg(ds.sleep_asleep_minutes / 60.0)::numeric, 2) AS avg_sleep_hours,
    ROUND(avg(ds.weight_kg)::numeric, 2) AS avg_weight_kg,
    ROUND(avg(ds.body_fat_pct)::numeric, 2) AS avg_body_fat_pct,
    ROUND(avg(ds.body_age_delta_years)::numeric, 1) AS avg_body_age_delta_years
  FROM (VALUES (7), (28), (90)) w(window_days)
  CROSS JOIN ref r
  LEFT JOIN daily_summary ds
    ON ds.date BETWEEN r.as_of - ((w.window_days - 1) * INTERVAL '1 day') AND r.as_of
  GROUP BY window_days
),
weekly_runs AS (
  SELECT
    date_trunc('week', workout_date)::date AS week_start,
    count(*) AS run_count,
    ROUND(sum(total_distance_km)::numeric, 2) AS total_run_km,
    ROUND(max(total_distance_km)::numeric, 2) AS longest_run_km,
    ROUND((sum(duration_sec) / 3600.0)::numeric, 2) AS total_run_hours,
    ROUND((sum(duration_sec) / 60.0 / NULLIF(sum(total_distance_km), 0))::numeric, 2) AS avg_pace_min_per_km,
    ROUND(avg(avg_hr)::numeric, 1) AS avg_run_hr
  FROM runs_base
  GROUP BY date_trunc('week', workout_date)::date
),
planned_runs AS (
  SELECT
    tp.start_date,
    tw.week_number,
    tpw.day_of_week,
    COALESCE(tpw.details->>'display_name', tpw.comment, e.name, 'planned run') AS planned_session,
    tpw.details
  FROM training_plans tp
  JOIN training_plan_weeks tw ON tw.plan_id = tp.id
  JOIN training_plan_workouts tpw ON tpw.week_id = tw.id
  LEFT JOIN wger_exercise e ON e.id = tpw.exercise_id
  WHERE tp.is_active = true
    AND tpw.is_cardio = true
  ORDER BY tw.week_number, tpw.day_of_week
)
SELECT jsonb_pretty(jsonb_build_object(
  'as_of', (SELECT as_of FROM ref),
  'latest_daily_summary', (
    SELECT to_jsonb(ds)
    FROM daily_summary ds, ref r
    WHERE ds.date <= r.as_of
    ORDER BY ds.date DESC
    LIMIT 1
  ),
  'rolling_daily_metrics', (
    SELECT jsonb_agg(to_jsonb(rollups) ORDER BY window_days)
    FROM rollups
  ),
  'weekly_running_last_26_weeks', (
    SELECT jsonb_agg(to_jsonb(x) ORDER BY x.week_start DESC)
    FROM (
      SELECT * FROM weekly_runs
      ORDER BY week_start DESC
      LIMIT 26
    ) x
  ),
  'recent_runs_last_60', (
    SELECT jsonb_agg(to_jsonb(x) ORDER BY x.start_time DESC)
    FROM (
      SELECT *
      FROM runs_base
      ORDER BY start_time DESC
      LIMIT 60
    ) x
  ),
  'longest_runs_last_180_days', (
    SELECT jsonb_agg(to_jsonb(x) ORDER BY x.total_distance_km DESC)
    FROM (
      SELECT *
      FROM runs_base
      ORDER BY total_distance_km DESC
      LIMIT 10
    ) x
  ),
  'active_planned_cardio', (
    SELECT COALESCE(jsonb_agg(to_jsonb(planned_runs)), '[]'::jsonb)
    FROM planned_runs
  ),
  'latest_strength_training_maxes', (
    SELECT COALESCE(jsonb_agg(to_jsonb(x) ORDER BY x.measured_at DESC, x.lift_code), '[]'::jsonb)
    FROM (
      SELECT DISTINCT ON (lift_code)
        lift_code, tm_kg, source, measured_at
      FROM training_max
      ORDER BY lift_code, measured_at DESC
    ) x
  ),
  'data_quality', jsonb_build_object(
    'daily_summary_rows_90d', (
      SELECT count(*) FROM daily_summary ds, ref r
      WHERE ds.date BETWEEN r.as_of - INTERVAL '89 days' AND r.as_of
    ),
    'run_workouts_180d', (SELECT count(*) FROM runs_base),
    'first_run_in_window', (SELECT min(workout_date) FROM runs_base),
    'latest_run', (SELECT max(workout_date) FROM runs_base)
  )
)) AS marathon_readiness_snapshot;