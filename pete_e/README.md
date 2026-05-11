# Pete-A Orchestrator

This directory houses Pete-E's orchestration logic as the personal trainer that coordinates activities across all external integrations – Wger, Withings, Apple, Telegram, etc.

The package is organised into application, domain, and infrastructure layers to separate orchestration from pure business rules.

Subfolders:
  - application/
  - cli/
  - config/
  - domain/
  - infrastructure/
  - resources/
  - utils/

    - Shared converters, formatters, math helpers, and miscellaneous utilities. Import modules as ``from pete_e.utils import converters`` to keep call sites explicit.

## Nutrition logging API (approximate-friendly)

`POST /nutrition/log-macros` accepts required macro grams and optional coaching fields:

- `protein_g`, `carbs_g`, `fat_g` (required, non-negative numbers)
- `alcohol_g`, `fiber_g`, `estimated_total_calories` (optional, nullable, non-negative numbers)

Behavior:

- If `estimated_total_calories` is provided, it is used as the entry calorie estimate.
- Otherwise calories are derived as `protein*4 + carbs*4 + fat*9 + alcohol*7`.
- Missing optional fields are preserved as `null` on raw entries and treated as `0` in aggregates.

Example payload:

```json
{
  "protein_g": 40,
  "carbs_g": 65,
  "fat_g": 18,
  "alcohol_g": 18,
  "fiber_g": 8,
  "estimated_total_calories": 750,
  "source": "photo_estimate",
  "context": "post_run",
  "confidence": "medium"
}
```
