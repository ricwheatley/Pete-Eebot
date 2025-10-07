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
