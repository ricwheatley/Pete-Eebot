# Fatigue and Readiness Model

## Purpose

This model translates objective and subjective signals into training decisions.

Use the API's `readiness_state` first, then interpret underlying signals and nutrition context.

## Readiness States

### Green

Meaning:

- Recovery markers are acceptable.
- Training load is tolerable.
- No serious pain or illness.
- Data quality is adequate.

Allowed actions:

- Complete the planned session.
- Progress one stressor only:
  - run volume, or
  - run intensity, or
  - strength load, or
  - calorie deficit,
  not all at once.

### Amber

Meaning:

- Some fatigue is present, but not enough to require rest.
- The plan may continue with modification.

Allowed actions:

- Keep easy sessions easy.
- Reduce intensity by one level.
- Reduce volume by 10-25%.
- Keep strength at maintenance loads.
- Avoid hard run plus heavy lower-body work.
- Keep nutrition stable or add carbs around training.

### Red

Meaning:

- Recovery, illness, injury risk, sleep debt, underfueling, or data confidence is materially adverse.

Allowed actions:

- Rest.
- Walk.
- Mobility.
- Short easy run only if no pain/illness and user insists.
- No intervals.
- No maximal lifting.
- No calorie tightening.

## Acute Fatigue Flags

Treat these as acute stress markers:

- Resting HR elevated versus baseline.
- HRV suppressed versus baseline.
- Sleep debt elevated.
- High soreness.
- High stress.
- Recent long run or heavy deadlift/squat.
- New pain.
- Reduced motivation plus poor sleep.
- High hunger and rapid weight loss.
- Nutrition logs suggest low intake or poor logging consistency during high load.

## Illness Pattern

If the user reports illness or the API shows a suspicious pattern:

- RHR meaningfully up
- HRV down
- respiratory rate up
- wrist temperature abnormal
- sleep disturbed

Action:

- No intensity.
- No heavy lifting.
- Easy walk or full rest.
- Return to training only after symptoms improve.

## Injury Pattern

High-risk signs:

- Focal bone pain
- Limping
- Pain worsening during run
- Sharp pain
- Joint swelling
- Pain persisting at rest
- Pain changing gait
- Achilles/calf pain during faster running
- Knee pain worsening downhill
- Back pain after deadlifts with neurological symptoms

Action:

- Stop progression.
- Remove painful movements.
- Recommend medical/physio assessment when severe, persistent, or gait-altering.

## Underfueling Pattern

Possible underfueling exists when several are present:

- Weight loss faster than 1% bodyweight/week.
- HRV down.
- RHR up.
- Sleep quality down.
- Hunger high.
- Mood or motivation low.
- Runs feel unusually hard.
- Strength performance drops.
- Libido or general wellbeing drops.
- Recurrent niggles.
- Logged nutrition is low or inconsistent during high training load.

Action:

- Add calories.
- Prefer carbohydrates around training.
- Avoid further deficit tightening.
- Reduce intensity temporarily.

## Stressor Stacking Rule

Avoid stacking more than two major stressors in one day.

Major stressors:

- Long run
- Threshold workout
- Interval workout
- Heavy squat/deadlift
- Large calorie deficit
- Poor sleep
- High work/life stress
- Illness recovery
- New mileage high

Examples:

- Long run plus large deficit: avoid.
- Intervals plus heavy squats: usually avoid.
- Poor sleep plus deadlift PR attempt: avoid.
- Green readiness plus easy run plus moderate deficit: acceptable.

## Deload Rules

Trigger or recommend deload if:

- `deload_due = true`
- readiness red repeatedly
- amber for more than three days with declining trend
- performance falls across multiple sessions
- sleep debt persists
- niggles accumulate
- load rose faster than planned
- underfueling pattern persists

Default deload:

- Reduce run volume 20-40%.
- Remove hard intervals.
- Keep easy running.
- Reduce strength volume 30-50%.
- Keep movement quality.
- Maintain protein.
- Do not deepen calorie deficit.

## Return-to-Progression Rule

After a red or deload period, resume progression only when:

- Sleep improves.
- RHR returns near baseline.
- HRV stabilizes.
- Pain is absent or clearly improving.
- Easy runs feel easy again.
- Strength sessions feel technically clean.
- Nutrition is stable enough to support training.

Resume at 80-90% of previous load, not 100%.
