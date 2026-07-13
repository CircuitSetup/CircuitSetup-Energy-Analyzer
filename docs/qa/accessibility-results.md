# Accessibility Results

## Automated Audit

`@axe-core/playwright` runs against Appliance Insights, Appliance Detail, Setup
Health, the NILM workspace, and Alert Evidence in both desktop and mobile
Chromium projects. The final audit reports no Axe violations.

The browser suite also verifies:

- NILM lane tabs use roving keyboard focus and update `aria-selected`.
- controls have accessible labels and button names;
- Appliance Detail sessions expose keyboard-operable detail and evidence links;
- the mobile document has no horizontal overflow;
- failed NILM loading exposes an operable Retry action;
- important graphs retain text, list, or table fallback content in the shipped
  panel contract tests.

The accessibility audit is scoped to the shipped custom panel in the static
harness. The disposable Home Assistant browser gate separately verifies that
the same panel renders inside the real Home Assistant shell without
integration-specific browser errors.

The first audit exposed insufficient selected-state contrast and a skipped
heading level in the NILM inspector. The selected text now uses the theme's
primary text color, and the inspector uses an `h2` below the page `h1`.
