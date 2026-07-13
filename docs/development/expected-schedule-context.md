# Expected Schedule Context

Expected schedules are optional appliance context. They do not change
operating detection and do not turn one missed window into a fault. Direct
meters use retained transitions; validated, sufficiently confident NILM
appliances use assignment-only sessions.

## Configuration

Appliance Detail stores one of these choices per stable appliance key:

- a Home Assistant `schedule.*` entity; or
- one or more local weekday/start/end windows.

Each configuration includes a minimum expected runtime. Local windows use the
Home Assistant timezone, including cross-midnight and daylight-saving changes.

## Evidence policy

The runtime compares completed windows with retained direct start/stop events
or validated assignment sessions.
It records bounded window and outside-session identifiers so refreshes do not
count the same evidence twice. Three distinct observations are required before
missed or outside-window behavior becomes alert-ready.

Schedule conclusions are suppressed while maintenance is active, source data
is stale or unavailable, or a selected Schedule entity is unavailable. A
completed window that meets its minimum runtime clears the consecutive missed-
window evidence.

## Stored data

Storage schema v8 adds bounded `appliance_schedule_settings` and
`appliance_schedule_evidence` mappings. Transient schedule context remains in
coordinator state and is rebuilt from current Home Assistant state and retained
events.
