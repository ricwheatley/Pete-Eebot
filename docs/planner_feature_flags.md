# Planner Feature Flags

Planner feature flags are opt-in switches for experimental plan-generation behavior. Safe defaults are used when no override is configured.

Last audited: 2026-05-15.

## Current Flags

| Flag | Default | Effect |
| --- | --- | --- |
| `experimental_relaxed_session_spacing` | `false` | Keeps quality runs that would normally be removed when scheduled within 24 hours of heavy squat/deadlift work. Use only for controlled planner experiments. |

## Configuration

Set flags with `PETEEEBOT_PLANNER_FEATURE_FLAGS`.

Examples:

```bash
# Safe default: no experimental planner behavior.
PETEEEBOT_PLANNER_FEATURE_FLAGS=""

# Enable one experiment.
PETEEEBOT_PLANNER_FEATURE_FLAGS="experimental_relaxed_session_spacing=true"

# Disable explicitly.
PETEEEBOT_PLANNER_FEATURE_FLAGS="experimental_relaxed_session_spacing=false"
```

The parser also accepts a bare enabled flag:

```bash
PETEEEBOT_PLANNER_FEATURE_FLAGS="experimental_relaxed_session_spacing"
```

Unknown flag names or invalid boolean values fail fast during startup. This is intentional so a typo cannot silently change plan generation.

## Operational Workflow

1. Confirm the current value:

   ```bash
   printenv PETEEEBOT_PLANNER_FEATURE_FLAGS
   ```

2. Enable or disable the flag in the runtime environment (`.env`, systemd environment file, or deployment secret source).

3. Restart the API/job process that generates plans so the domain settings are rebuilt from configuration.

4. Generate a plan in a controlled window.

5. Check audit logs for actual flag effects:

   ```bash
   jq -c 'select(.tag=="AUDIT" and .checkpoint=="planner_feature_flags")' /var/log/pete_eebot/pete_history.log
   ```

Only non-default flags that actually affect plan generation emit this audit checkpoint. The persisted plan metadata also includes:

- `planner_feature_flags`: full evaluated flag state.
- `planner_feature_flag_overrides`: flags whose values differ from defaults.
- `planner_feature_flag_effects`: trace-derived effects applied during generation.

## Rollback

Unset the environment variable or set the flag to `false`, restart the process, then regenerate future plans. Existing persisted plans are not mutated by changing a flag.
