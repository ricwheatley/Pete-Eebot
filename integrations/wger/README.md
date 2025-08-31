# Wger automation (Pete E)

This directory contains automation to:
- Refresh the Wger exercise catalog (weekly)
- Generate a proposed 4-week plan (Fridays) and open a PR for review (Sundays you check)
- Apply an approved plan to Wger via the Routine API (manual dispatch)
- Pull the last day's workout logs (daily ~03:15 UK) for use in planning

**Secrets / Variables**  
- `WGER_API_KEY` (secret): API token from your Wger account (User Settings → API Key)
- `WGER_BASE_URL` (variable, optional): e.g. `https://wger.de/api/v2` (default) or your self-hosted base

**Typical flow**
1. `wger_catalog_refresh.yml` keeps `catalog/` up to date.
2. `wger_plan_and_pr.yml` writes `plans/plan_<start>_<end>.json` and opens a PR.
3. You review on Sunday morning. When happy either:
   - merge the PR (records the plan), then run `Apply plan to Wger` workflow pointing at that plan path; or
   - run `Apply plan to Wger` directly from the PR.
4. `wger_apply_plan.yml` writes the routine + days + exercises + configs via the Routine API and stores the routine id in `state/`.
5. `wger_logs_refresh.yml` pulls previous day's logs for progressive overload heuristics in the next cycle.

See the Python files for details.
