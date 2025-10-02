-- Update sp_upsert_body_age to consume direct VO2 max values and HRV adjustments
BEGIN;

CREATE OR REPLACE FUNCTION sp_upsert_body_age(p_target_date date, p_birth_date date)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_start               date := p_target_date - INTERVAL '6 days';
    v_bodyfat_avg         double precision;
    v_steps_avg           double precision;
    v_ex_min_avg          double precision;
    v_rhr_avg             double precision;
    v_sleep_asleep_avg    double precision;
    v_vo2_direct          double precision;
    v_hrv_avg             double precision;
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
    v_chrono_years        double precision;
    v_body_age            double precision;
    v_cap_min             double precision;
    v_cap_applied         boolean;
    v_used_vo2_direct     boolean := false;
    v_any_rows            integer;
BEGIN
    IF p_target_date IS NULL OR p_birth_date IS NULL THEN
        RAISE EXCEPTION 'sp_upsert_body_age: Both p_target_date and p_birth_date are required';
    END IF;
    SELECT COUNT(*) INTO v_any_rows FROM daily_summary ds WHERE ds.date BETWEEN v_start AND p_target_date;
    IF v_any_rows = 0 THEN RETURN; END IF;
    SELECT
        avg(ds.body_fat_pct)::double precision,
        avg(ds.steps)::double precision,
        avg(ds.exercise_minutes)::double precision,
        avg(ds.hr_resting)::double precision,
        avg(ds.sleep_asleep_minutes)::double precision,
        avg(ds.vo2_max)::double precision,
        avg(ds.hrv_sdnn_ms)::double precision
    INTO v_bodyfat_avg,
         v_steps_avg,
         v_ex_min_avg,
         v_rhr_avg,
         v_sleep_asleep_avg,
         v_vo2_direct,
         v_hrv_avg
    FROM daily_summary ds
    WHERE ds.date BETWEEN v_start AND p_target_date;
    v_chrono_years := EXTRACT(EPOCH FROM (p_target_date::timestamp - p_birth_date::timestamp)) / 31557600.0;
    -- Prefer direct VO2 max measurements when available; otherwise fall back to derived estimate.
    IF v_vo2_direct IS NOT NULL THEN
        v_vo2 := v_vo2_direct;
        v_used_vo2_direct := true;
    ELSIF v_rhr_avg IS NOT NULL THEN
        v_vo2 := 38 - 0.15 * (v_chrono_years - 40) - 0.15 * (COALESCE(v_rhr_avg, 60) - 60) + 0.01 * COALESCE(v_ex_min_avg, 0);
    ELSE
        v_vo2 := 35;
    END IF;
    v_crf := GREATEST(0.0, LEAST(100.0, ((v_vo2 - 20.0) / 40.0) * 100.0));
    IF v_bodyfat_avg IS NULL THEN v_body_comp := 50.0; ELSIF v_bodyfat_avg <= 15.0 THEN v_body_comp := 100.0; ELSIF v_bodyfat_avg >= 30.0 THEN v_body_comp := 0.0;
    ELSE v_body_comp := (30.0 - v_bodyfat_avg) / 15.0 * 100.0; END IF;
    v_steps_score := CASE WHEN v_steps_avg IS NULL THEN 0.0 ELSE GREATEST(0.0, LEAST(100.0, (v_steps_avg / 12000.0) * 100.0)) END;
    v_ex_score := CASE WHEN v_ex_min_avg IS NULL THEN 0.0 ELSE GREATEST(0.0, LEAST(100.0, (v_ex_min_avg / 30.0) * 100.0)) END;
    v_activity := 0.6 * v_steps_score + 0.4 * v_ex_score;
    v_sleep_score := CASE WHEN v_sleep_asleep_avg IS NULL THEN 50.0 ELSE GREATEST(0.0, LEAST(100.0, 100.0 - (ABS(v_sleep_asleep_avg - 450.0) / 150.0) * 60.0)) END;
    v_rhr_score := CASE WHEN v_rhr_avg IS NULL THEN 50.0 WHEN v_rhr_avg <= 55.0 THEN 90.0 WHEN v_rhr_avg <= 60.0 THEN 80.0 WHEN v_rhr_avg <= 70.0 THEN 60.0 WHEN v_rhr_avg <= 80.0 THEN 40.0 ELSE 20.0 END;
    IF v_hrv_avg IS NOT NULL THEN
        IF v_hrv_avg < 25.0 THEN
            v_rhr_score := v_rhr_score - 20.0;
        ELSIF v_hrv_avg < 35.0 THEN
            v_rhr_score := v_rhr_score - 15.0;
        ELSIF v_hrv_avg < 45.0 THEN
            v_rhr_score := v_rhr_score - 10.0;
        ELSIF v_hrv_avg < 55.0 THEN
            v_rhr_score := v_rhr_score - 5.0;
        END IF;
        v_rhr_score := GREATEST(0.0, LEAST(100.0, v_rhr_score));
    END IF;
    v_recovery := 0.66 * v_sleep_score + 0.34 * v_rhr_score;
    v_composite := 0.40 * v_crf + 0.25 * v_body_comp + 0.20 * v_activity + 0.15 * v_recovery;
    v_body_age := v_chrono_years - 0.2 * (v_composite - 50.0);
    v_cap_min := v_chrono_years - 10.0;
    IF v_body_age < v_cap_min THEN v_body_age := v_cap_min; v_cap_applied := true; ELSE v_cap_applied := false; END IF;
    INSERT INTO body_age_daily (date, input_window_days, crf_score, body_comp_score, activity_score, recovery_score, composite_score, body_age_years, age_delta_years, used_vo2max_direct, cap_minus_10_applied, updated_at)
    VALUES (p_target_date, 7, ROUND(v_crf::numeric, 1), ROUND(v_body_comp::numeric, 1), ROUND(v_activity::numeric, 1), ROUND(v_recovery::numeric, 1), ROUND(v_composite::numeric, 1), ROUND(v_body_age::numeric, 1), ROUND((v_body_age - v_chrono_years)::numeric, 1), v_used_vo2_direct, v_cap_applied, now())
    ON CONFLICT (date) DO UPDATE SET
        input_window_days = EXCLUDED.input_window_days, crf_score = EXCLUDED.crf_score, body_comp_score = EXCLUDED.body_comp_score, activity_score = EXCLUDED.activity_score, recovery_score = EXCLUDED.recovery_score, composite_score = EXCLUDED.composite_score,
        body_age_years = EXCLUDED.body_age_years, age_delta_years = EXCLUDED.age_delta_years, used_vo2max_direct = EXCLUDED.used_vo2max_direct, cap_minus_10_applied = EXCLUDED.cap_minus_10_applied, updated_at = now();
END;
$$;

COMMIT;
