# Compact Entity Model Migration

Existing installs are not silently stripped of enabled legacy entities. During
the compatibility release, the integration records legacy compatibility keys so
user-enabled dashboards and automations can continue to work while new installs
use the compact model.

## New Installs

New config entries are marked with entity model version 2 and create compact
entities immediately.

## Existing Installs

Config entries without an entity model version are migrated to the legacy marker.
The migration keeps enabled or customized legacy entities through compatibility
keys and prunes legacy rows that are integration-disabled or hidden by the
integration when they are safe to remove.

The integration creates one non-urgent Repair issue for entries that still have
legacy analyzer entities. The Repair points users to the explicit migration
preview instead of creating one issue per circuit.

## Preview And Confirmation

Open:

```text
Settings > Devices & services > CircuitSetup Energy Analyzer > Configure > Migrate To Compact Entity Model
```

The preview lists:

- legacy entities that will be removed;
- replacement entity or location;
- entities that will remain;
- the new maintenance switch;
- expected count before and after;
- whether customized rows may return with default IDs if re-enabled later.

The cleanup only runs after confirming **Remove Legacy Entities**.

## Compatibility Behavior

| Legacy case | Behavior |
|---|---|
| Enabled legacy entity | Preserved by compatibility key until explicit migration. |
| User-hidden or user-disabled legacy entity | Treated as customized and not silently removed. |
| Integration-disabled/hidden legacy entity | Removed during safe cleanup. |
| Re-created optional entity | May return with default IDs if Home Assistant cannot preserve removed customizations; the preview warns about this. |
| Existing services | Remain registered for automations and scripts. |

## Maintenance Controls

The compact model replaces Start Maintenance and End Maintenance buttons with
`switch.<circuit>_maintenance`. Existing maintenance services remain available.

## Verification

The automated verification path for this branch covered:

- options-flow versioning and Expert selected groups;
- registry-driven legacy compatibility and cleanup preview;
- compact entity creation across sensor, binary sensor, button, select, number,
  and switch platforms;
- maintenance switch state and actions;
- Repairs issue creation for legacy rows;
- Home Assistant setup, reload, unload, and remove lifecycle tests;
- generated dashboard references and user-facing documentation checks.
