-- ============================================
-- Body Age calculation in PostgreSQL, faithful to the Python algorithm
-- ============================================

-- 0) Ensure the target table exists and has the required columns
CREATE TABLE IF NOT EXISTS body_age_daily (
    date                        date PRIMARY KEY,
    input_window_days           int      NOT NULL DEFAULT 7,
    crf_score                   numeric(5,1),
    body_comp_score             numeric(5,1),
    activity_score              numeric(5,1),
    recovery_score              numeric(5,1),
    composite_score             numeric(5,1),
    body_age_years              numeric(6,1),
    age_delta_years             numeric(6,1),
    used_vo2max_direct          boolean  NOT NULL DEFAULT false,
    cap_minus_10_applied        boolean  NOT NULL DEFAULT false,
    updated_at                  timestamptz NOT NULL DEFAULT now()
);

-- Add any missing columns idempotently
DO $DDL$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'input_window_days'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN input_window_days int NOT NULL DEFAULT 7;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'crf_score'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN crf_score numeric(5,1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'body_comp_score'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN body_comp_score numeric(5,1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'activity_score'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN activity_score numeric(5,1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'recovery_score'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN recovery_score numeric(5,1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'composite_score'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN composite_score numeric(5,1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'body_age_years'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN body_age_years numeric(6,1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'age_delta_years'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN age_delta_years numeric(6,1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'used_vo2max_direct'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN used_vo2max_direct boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'cap_minus_10_applied'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN cap_minus_10_applied boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'body_age_daily' AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE body_age_daily ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
    END IF;
END
$DDL$;

-- 1) Single‑day upsert procedure
-- Mirrors your Python: 7‑day averages, weights 40/25/20/15, -10 years cap, no direct VO2 path.
CREATE OR REPLACE FUNCTION sp_upsert_body_age(
    p_target_date   date,
    p_birth_date    date
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_start               date := p_target_date - INTERVAL '6 days';

    -- 7‑day window averages from daily_summary
    v_bodyfat_avg         double precision;
    v_steps_avg           double precision;
    v_ex_min_avg          double precision;
    v_rhr_avg             double precision;
    v_sleep_asleep_avg    double precision;

    -- Scores and composites
    v_vo2                 double precision;
    v_crf                 double precision;
    v_body_comp           double precision;
    v_steps_score         double precision;
    v_ex_score            double precision;
    v_activity            double precision;
    v_sleep_score         double precision;
    v_rhr_score           double precision;
    v_recovery            double precision;
    v_composite           double precision;

    -- Age maths
    v_chrono_years        double precision;
    v_body_age            double precision;
    v_cap_min             double precision;
    v_cap_applied         boolean;

    -- helper
    v_any_rows            integer;
BEGIN
    IF p_target_date IS NULL THEN
        RAISE EXCEPTION 'sp_upsert_body_age: p_target_date is required';
    END IF;
    IF p_birth_date IS NULL THEN
        RAISE EXCEPTION 'sp_upsert_body_age: p_birth_date is required';
    END IF;

    -- Do we have any rows at all in the window
    SELECT COUNT(*) INTO v_any_rows
    FROM daily_summary ds
    WHERE ds.date BETWEEN v_start AND p_target_date;

    IF v_any_rows = 0 THEN
        -- Nothing to compute for this date
        RETURN;
    END IF;

    -- Pull averages, NULLs are fine, AVG ignores NULLs like the Python "average" helper
    SELECT
        avg(ds.body_fat_pct)::double precision,
        avg(ds.steps)::double precision,
        avg(ds.exercise_minutes)::double precision,
        avg(ds.hr_resting)::double precision,
        avg(ds.sleep_asleep_minutes)::double precision
    INTO
        v_bodyfat_avg,
        v_steps_avg,
        v_ex_min_avg,
        v_rhr_avg,
        v_sleep_asleep_avg
    FROM daily_summary ds
    WHERE ds.date BETWEEN v_start AND p_target_date;

    -- Chronological age in years at p_target_date, using mean tropical year
    v_chrono_years := EXTRACT(EPOCH FROM (p_target_date::timestamp - p_birth_date::timestamp)) / 31557600.0;

    -- ===== CRF (40%) =====
    -- Python:
    -- vo2 = 38 - 0.15*(chrono_age - 40) - 0.15*((rhr or 60) - 60) + 0.01*(exmin or 0) if rhr not None else 35
    IF v_rhr_avg IS NOT NULL THEN
        v_vo2 := 38
                 - 0.15 * (v_chrono_years - 40)
                 - 0.15 * ((COALESCE(v_rhr_avg, 60)) - 60)
                 + 0.01 * (COALESCE(v_ex_min_avg, 0));
    ELSE
        v_vo2 := 35;
    END IF;

    -- crf = clamp( (vo2 - 20) / (60 - 20) * 100, 0, 100 )
    v_crf := GREATEST(0.0, LEAST(100.0, ((v_vo2 - 20.0) / 40.0) * 100.0));

    -- ===== Body composition (25%) =====
    -- If bodyfat None -> 50, elif <=15 -> 100, elif >=30 -> 0, else linear between
    IF v_bodyfat_avg IS NULL THEN
        v_body_comp := 50.0;
    ELSIF v_bodyfat_avg <= 15.0 THEN
        v_body_comp := 100.0;
    ELSIF v_bodyfat_avg >= 30.0 THEN
        v_body_comp := 0.0;
    ELSE
        v_body_comp := (30.0 - v_bodyfat_avg) / (30.0 - 15.0) * 100.0;
    END IF;

    -- ===== Activity (20%) =====
    -- steps_score = 0 if steps None else clamp( (steps/12000)*100, 0, 100)
    v_steps_score := CASE
        WHEN v_steps_avg IS NULL THEN 0.0
        ELSE GREATEST(0.0, LEAST(100.0, (v_steps_avg / 12000.0) * 100.0))
    END;
    -- ex_score = 0 if exmin None else clamp( (exmin/30)*100 )
    v_ex_score := CASE
        WHEN v_ex_min_avg IS NULL THEN 0.0
        ELSE GREATEST(0.0, LEAST(100.0, (v_ex_min_avg / 30.0) * 100.0))
    END;

    v_activity := 0.6 * v_steps_score + 0.4 * v_ex_score;

    -- ===== Recovery (15%) =====
    -- Sleep: if None -> 50 else clamp( 100 - (abs(sleep - 450)/150)*60 )
    v_sleep_score := CASE
        WHEN v_sleep_asleep_avg IS NULL THEN 50.0
        ELSE GREATEST(
                 0.0,
                 LEAST(100.0, 100.0 - (ABS(v_sleep_asleep_avg - 450.0) / 150.0) * 60.0)
             )
    END;

    -- RHR discrete buckets
    v_rhr_score := CASE
        WHEN v_rhr_avg IS NULL THEN 50.0
        WHEN v_rhr_avg <= 55.0 THEN 90.0
        WHEN v_rhr_avg <= 60.0 THEN 80.0
        WHEN v_rhr_avg <= 70.0 THEN 60.0
        WHEN v_rhr_avg <= 80.0 THEN 40.0
        ELSE 20.0
    END;

    v_recovery := 0.66 * v_sleep_score + 0.34 * v_rhr_score;

    -- ===== Composite and Body Age =====
    v_composite := 0.40 * v_crf + 0.25 * v_body_comp + 0.20 * v_activity + 0.15 * v_recovery;

    -- body_age = chrono_age - 0.2 * (composite - 50)
    v_body_age := v_chrono_years - 0.2 * (v_composite - 50.0);

    -- Cap improvements at -10 years
    v_cap_min := v_chrono_years - 10.0;
    IF v_body_age < v_cap_min THEN
        v_body_age := v_cap_min;
        v_cap_applied := true;
    ELSE
        v_cap_applied := false;
    END IF;

    -- Upsert rounded values per Python output
    INSERT INTO body_age_daily (
        date,
        input_window_days,
        crf_score,
        body_comp_score,
        activity_score,
        recovery_score,
        composite_score,
        body_age_years,
        age_delta_years,
        used_vo2max_direct,
        cap_minus_10_applied,
        updated_at
    )
    VALUES (
        p_target_date,
        7,
        ROUND(v_crf::numeric, 1),
        ROUND(v_body_comp::numeric, 1),
        ROUND(v_activity::numeric, 1),
        ROUND(v_recovery::numeric, 1),
        ROUND(v_composite::numeric, 1),
        ROUND(v_body_age::numeric, 1),
        ROUND((v_body_age - v_chrono_years)::numeric, 1),
        false,
        v_cap_applied,
        now()
    )
    ON CONFLICT (date) DO UPDATE SET
        input_window_days     = EXCLUDED.input_window_days,
        crf_score             = EXCLUDED.crf_score,
        body_comp_score       = EXCLUDED.body_comp_score,
        activity_score        = EXCLUDED.activity_score,
        recovery_score        = EXCLUDED.recovery_score,
        composite_score       = EXCLUDED.composite_score,
        body_age_years        = EXCLUDED.body_age_years,
        age_delta_years       = EXCLUDED.age_delta_years,
        used_vo2max_direct    = EXCLUDED.used_vo2max_direct,
        cap_minus_10_applied  = EXCLUDED.cap_minus_10_applied,
        updated_at            = now();
END;
$$;

-- 2) Convenience range backfill
CREATE OR REPLACE FUNCTION sp_upsert_body_age_range(
    p_start_date   date,
    p_end_date     date,
    p_birth_date   date
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    d date;
BEGIN
    IF p_start_date IS NULL OR p_end_date IS NULL OR p_start_date > p_end_date THEN
        RAISE EXCEPTION 'sp_upsert_body_age_range: invalid date range %, %', p_start_date, p_end_date;
    END IF;

    d := p_start_date;
    WHILE d <= p_end_date LOOP
        PERFORM sp_upsert_body_age(d, p_birth_date);
        d := d + INTERVAL '1 day';
    END LOOP;
END;
$$;
