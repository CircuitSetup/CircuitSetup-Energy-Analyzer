# Source Sensor Refresh Design

## Problem

The integration stores the sensor entity IDs discovered from selected source
devices. That list is rebuilt only when the user submits Edit Source Selection.
Sensors added to a selected device, or sensor entity IDs changed on that device,
therefore remain unavailable to appliance assignment until the user opens and
saves the source-selection form again.

## Goal

Add an explicit Refresh Source Sensors action to CircuitSetup Energy Analyzer
options. The action rescans the already-selected source devices, saves the
current device-derived sensor list, and reloads the integration without asking
the user to edit unrelated source settings.

## Non-Goals

- Do not refresh automatically when the options menu opens.
- Do not add a service, custom panel control, or background polling.
- Do not change selected source devices, manual extra sources, mains sources,
  or unrelated options. Existing circuit assignments are preserved; the
  current source-save merge may append newly matching sensors.

## Options Flow

Add `refresh_sources` to the existing options menu immediately after Edit
Source Selection. Its label is Refresh Source Sensors.

Selecting it opens a confirmation form explaining that the integration will:

1. Rescan the currently selected source devices.
2. Rebuild the stored device-derived source list from the current sensor IDs.
3. Preserve manually selected extra sources and all unrelated settings.
4. Reload the integration after saving.

The form uses Home Assistant's normal options-flow submit and back controls. No
custom frontend is required.

## Data Flow

On confirmation, the options step reuses the existing source-selection path:

1. Read the current source configuration with `_options_source_payload`.
2. Expand the stored source devices with
   `_async_source_selection_with_device_entities`.
3. Validate the result with `validate_options_input`.
4. Merge newly matching sensors into existing circuits with
   `_options_with_merged_source_circuit_sensors`.
5. Return `async_create_entry` with the updated options so Home Assistant
   reloads the config entry.

This keeps source discovery in one implementation and makes the explicit
refresh behave like saving Edit Source Selection without rendering or editing
that larger form.

## Failure Behavior

If the refreshed selection is invalid, no source devices are selected, or the
selected devices return no usable sensors, show an options-flow validation
error and do not save. Discovery exceptions continue through the existing
guarded discovery helper and fail the same no-device-sensors check rather than
silently removing the stored device-derived list.

## Tests

Add focused regressions that verify:

- the options menu and English translations expose Refresh Source Sensors;
- the refresh step shows a confirmation form before changing options;
- confirmation rescans the stored source devices;
- newly discovered device sensors replace the old device-derived list while
  manual extra sources and unrelated options remain unchanged;
- validation failures return the form with an error and preserve the config
  entry.

No panel cache-buster change is needed because no shipped frontend JavaScript
changes.
