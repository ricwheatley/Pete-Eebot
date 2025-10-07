# Contributing Guidelines

## Shared Utilities

Pete-E centralises cross-cutting helpers inside `pete_e/utils/`. When adding or updating utilities, follow these conventions:

- **Module layout.** Organise helpers by responsibility: `converters.py` for type conversions, `formatters.py` for text rendering, `math.py` for numeric helpers, and `helpers.py` for miscellaneous glue. Create a new module only when a responsibility does not fit the existing ones.
- **Import style.** Prefer importing modules explicitly: `from pete_e.utils import converters` and call `converters.to_float(...)`. This keeps call sites clear about a helper's origin and reduces accidental name clashes. Import individual functions only when they are truly ubiquitous and the name is unambiguous.
- **Naming.** Choose descriptive, singular names (e.g. `to_float`, `to_date`, `minutes_to_hours`). Avoid prefixes such as `_as_*` or suffixes like `_util`; the module name already conveys that these are utilities.
- **Separation.** Utility code must remain free of application or domain dependencies to prevent circular imports. Rely only on the Python standard library or third-party packages already in use. If a helper requires knowledge of domain concepts, place it in the appropriate `application` or `domain` module instead.
- **Reusability.** Before introducing a new helper, review the existing modules to avoid duplicating behaviour. Shared improvements belong in `pete_e.utils` so other layers can benefit from them.

Documenting these expectations ensures future contributors extend the utilities consistently and keeps shared helpers easy to discover.
