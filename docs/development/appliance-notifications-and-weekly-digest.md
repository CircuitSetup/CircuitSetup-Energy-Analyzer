# Appliance Notifications And Weekly Digest

Appliance notification preferences are stored by stable appliance key. Safe
defaults leave existing issue notifications enabled while finished-running
messages remain opt-in. The central notification controller applies category,
NILM confidence, cooldown, delivery-mode, and Home Assistant local quiet-hour
policy before creating a persistent notification. Quiet-hour deferrals and
cooldown timestamps are durable and bounded to 100 records.

Immediate, daily-summary, weekly-digest-only, and disabled delivery modes are
supported. Direct STOP events create finished notifications only for opted-in
appliances; source-unavailable transitions are ignored. NILM confidence gates
only estimated appliances. Repairs remain outside this notification policy.

The weekly digest is disabled by default. When enabled, the analyzer stores one
idempotent report per local week, ranking changes from each appliance's own
normal separately from absolute energy use. Expected context is excluded from
the anomaly ranking, resolved items are omitted, and NILM validation remains a
separate section. Delivery can be panel-only, persistent notification, or a
validated `notify.*` mobile service.
