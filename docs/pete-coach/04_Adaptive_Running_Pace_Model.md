# Adaptive Running Pace Model

## Purpose

The coach must prescribe running using current fitness, not goal fitness.

Sub-3 marathon pace is approximately 4:15/km. This is the long-term target, not the default current training pace.

## Known Anchors

- Current half-marathon marker: approximately 2:15.
- Historical half-marathon PB: 1:42:30.
- Long-term marathon goal: sub-3.

Interpretation:

- The historical PB supports optimism about redevelopment.
- The current marker controls current training prescription.
- The sub-3 target controls long-term direction only.

## Effort Bands

When precise pace is uncertain, prescribe by effort first and pace second.

### Easy / Recovery

Purpose:

- aerobic base
- recovery
- durability
- fat oxidation support
- frequency building

Cues:

- conversational
- controlled breathing
- finishes feeling like more was available
- no heroic effort

### Steady

Purpose:

- aerobic strength
- medium-long development

Cues:

- purposeful but controlled
- can speak in short phrases
- not threshold

### Tempo / Threshold

Purpose:

- lactate threshold development
- half-marathon redevelopment
- marathon support

Cues:

- comfortably hard
- controlled strain
- sustainable for blocks
- not a race effort

### Interval / VO2

Purpose:

- improve aerobic power and speed economy

Cues:

- hard
- limited doses
- full warm-up and recovery
- not used during poor readiness

### Marathon Pace

Purpose:

- future race-specific work

Cues:

- only introduced meaningfully once the aerobic base supports it
- not forced early

## Current Fitness Pace Logic

If no recent race or tested threshold is available, do not invent precise paces.

Use recent workout data:

- average pace
- average HR
- max HR
- duration
- distance
- subjective effort, if available
- HR drift, if calculable
- recovery response the next day

Use nutrition context only as a modifier:

- If key sessions are poor and logged intake looks low, fuel better before lowering paces permanently.
- If nutrition logging is missing, do not assume underfueling; ask about hunger/fueling only if decision-critical.

## Pace Adjustment Rules

### If readiness is green

- Keep easy runs easy.
- Allow one quality session if planned.
- Progress duration before pace unless in a specific speed block.

### If readiness is amber

- Easy run only, or reduce quality session.
- Tempo becomes steady.
- Intervals become strides or easy run.
- Long run may be shortened 10-25%.
- Add carbs around training if underfueling is plausible.

### If readiness is red

- No quality session.
- No long-run progression.
- Rest, walk, mobility, or very short easy run only.

## Heart Rate Drift Logic

If available from workout detail:

- High drift during easy runs suggests aerobic durability is insufficient or fueling/hydration/recovery is poor.
- Do not increase pace if HR drift is worsening.
- Prefer extending easy consistency before adding intensity.

## Weekly Running Structure

### Early redevelopment

- 4 runs/week
- 1 long run
- 2 easy runs
- 1 light quality touch: strides, hills, or controlled tempo fragments

### Base development

- 4-5 runs/week
- long run builds gradually
- one threshold-focused session
- optional strides after easy run

### Build phase

- 5 runs/week
- long run
- medium-long run
- threshold workout
- short speed economy / hills

### Marathon-specific phase

Only after readiness gate:

- long run with controlled marathon-effort segments
- threshold maintenance
- medium-long aerobic run
- easy volume

## Volume Progression

Use conservative progression:

- Prefer 3 weeks build plus 1 week down.
- Do not increase weekly distance more than around 5-10% without strong reason.
- Do not increase long run and intensity load aggressively in the same week.
- After missed weeks, resume below previous peak.

## Sub-3 Readiness Gate

Do not frame the user as close to sub-3 until several are true:

- Sustained weekly running volume is robust.
- Long runs are durable.
- Easy pace improves at similar heart rate.
- Threshold pace improves materially.
- Recent half-marathon equivalent approaches low-1:30s and then below.
- Fueling long runs is reliable.
- Injury status is stable.
- Sleep is sufficient enough to absorb training.

## Example Training Decision Language

Use:

> Today is not a day to prove fitness. It is a day to bank aerobic work.

Use:

> The goal pace is 4:15/km, but today's training pace should be governed by current aerobic control, not the marathon ambition.

Do not use:

> Run marathon pace because the goal is sub-3.

## Treadmill Translation

When the user asks for treadmill settings, convert pace to km/h:

`speed_kmh = 60 / pace_min_per_km`

Examples:

- 6:00/km = 10.0 km/h
- 5:30/km = 10.9 km/h
- 5:00/km = 12.0 km/h
- 4:30/km = 13.3 km/h
- 4:15/km = 14.1 km/h

Use 0-1% incline unless the user specifies otherwise.
