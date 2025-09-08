# 📂 docs/

This folder is the **system of record** for raw and processed data
from all integrations.

Contents:
- **withings/** → History of weight, body fat, HR, etc.
- **apple/** → Daily sync of steps, calories, HR, sleep.
- **wger/** → Active workout plans + synced state.
- **analytics/** → Processed metrics:
  - `body_age.json` → today’s body age
  - `history.json` → rolling body age history
  - `unified_metrics.json` → merged view of Apple + Withings + Wger + analytics

💡 Think of this folder as the **current state of the world + JSON history**.
