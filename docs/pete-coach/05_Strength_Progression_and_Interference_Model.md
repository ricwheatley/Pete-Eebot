# Strength Progression and Interference Model

## Purpose

The coach must develop strength while protecting running progression and fat-loss recovery.

Current approximate lifts:

- Bench: 50kg
- Squat: 60kg
- Deadlift: 70kg

Targets:

- Bench: 100kg
- Squat: 100kg
- Deadlift: 140kg

## Strategic View

The user is rebuilding strength and endurance at the same time while losing weight.

This means:

- Strength can progress strongly early.
- Lower-body strength must be managed around running.
- Strength maintenance is acceptable during high-volume marathon blocks.
- Maximal strength ambitions should not sabotage running consistency.
- Nutrition consistency matters, especially protein and carbohydrates around hard sessions.

## Training Max

Use a training max rather than true max.

Default:

- Training max = 85-90% of estimated 1RM.

If the API provides `training_maxes_kg`, use them.

If no reliable training max exists, use conservative working weights until recent top sets establish a baseline.

## Progression Model

### Early phase

Use simple progression:

- Add small loads when reps are completed cleanly.
- Prioritize technique and consistency.
- Keep 1-3 reps in reserve on most sets.

### Intermediate phase

Use wave progression, similar to 5/3/1:

- Week 1: 5s
- Week 2: 3s
- Week 3: heavier top set
- Week 4: deload

Use this as a structure, not dogma.

### Marathon build phase

Shift lower-body lifting toward maintenance:

- Fewer hard squat/deadlift sets.
- Maintain intensity moderately.
- Reduce volume.
- Avoid grinding reps.

## Main Lift Rules

### Bench Press

Bench interferes least with running.

Rules:

- Progress if readiness is green and recent bench sessions are completed cleanly.
- Maintain if sleep and HRV are poor.
- Do not grind frequently.

### Squat

Squat has high interference with running.

Rules:

- Avoid heavy squat before key run sessions.
- Avoid heavy squat the day after long run if legs are not recovered.
- Reduce volume when run load increases.
- Use technique-focused or submaximal work during marathon peak.

### Deadlift

Deadlift has the highest systemic fatigue cost.

Rules:

- Deadlift heavy no more than once per week.
- Avoid heavy deadlifts near long runs or hard intervals.
- Keep most work submaximal.
- Reduce deadlift volume first when fatigue accumulates.

## Interference Rules

### High run-load week

If run volume or intensity is high:

- Bench may progress.
- Squat should maintain or progress very cautiously.
- Deadlift should maintain or reduce volume.

### High lower-body soreness

If soreness is high:

- Remove heavy squat/deadlift.
- Use light technique work, mobility, or upper-body-only strength.

### Poor readiness

If readiness is amber:

- Bench: moderate work allowed.
- Squat: reduce load or volume.
- Deadlift: skip heavy work.

If readiness is red:

- No heavy lifting.

### Poor fueling context

If logged nutrition or subjective feedback suggests low energy availability:

- Keep protein stable.
- Add carbohydrates around training.
- Hold lower-body progression.
- Do not chase rep PRs.

## Strength Session Templates

### Full Body A

- Squat main work
- Bench volume
- Row
- Hamstring accessory
- Core

### Full Body B

- Deadlift main work
- Overhead press or bench variation
- Pull-up/lat pulldown
- Split squat or lunge, light
- Core

### Full Body C

- Bench main work
- Squat technique/light volume
- RDL or hip hinge, moderate
- Row
- Carries or core

## Strength Adjustment by Running Phase

| Running phase | Strength priority |
|---|---|
| Base | Build strength |
| Build | Build upper, maintain lower |
| Peak | Maintain strength |
| Taper | Low volume, low fatigue |
| Post-race | Rebuild strength block |

## Rep Reserve

Use RIR if available.

Rules:

- RIR 2-3: normal training
- RIR 1: occasional hard work
- RIR 0: rare, not during high run load
- repeated RIR 0: too much intensity

## Progression Criteria

Progress a lift if:

- readiness green
- no pain
- last session completed with acceptable RIR
- technique was clean
- no major running priority within 24-48 hours
- sleep is not severely compromised
- nutrition is adequate enough to support training

Hold a lift if:

- readiness amber
- RIR was lower than planned
- soreness is moderate
- key run is soon
- weight loss is aggressive
- nutrition logs are partial and hunger/fatigue is high

Reduce a lift if:

- readiness red
- pain is present
- form broke down
- deadlift/squat fatigue affects running
- underfueling signs are present

## Failed Reps

Do not normalize failed reps.

If a lift is failed:

- reduce load next session
- check sleep, logged nutrition, and recent run load
- avoid adding more intensity
- consider deload if repeated
