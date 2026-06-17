# Feedback Loop Review

## Current behavior

- Alert feedback was already persisted in `FeatureStoreData.alert_feedback` and saved through the existing feature store.
- Alert feedback already affected persistent notifications, but the previous key was only `circuit_id:feature`, which could suppress unrelated evidence for the same feature.
- Acknowledging an alert retired the current alert episode and did not store future suppression feedback.
- Settings recommendation deny and dismiss decisions already persisted by recommendation unique key and evidence fingerprint, with cooldown behavior.
- NILM label, ignore, expected, and merge actions already updated stored signature dictionaries and panel payloads, but they remain tied to current signature IDs rather than stable NILM fingerprints.
- Evidence panel actions already call backend services with IDs embedded in the action payload, so normal users do not need to type IDs for the existing panel actions.
- Feedback-related services already raise `HomeAssistantError` for unknown alert, recommendation, circuit, and NILM signature IDs in the audited paths.
- Stored feedback survives reload/restart through Home Assistant storage, subject to existing retention pruning.

## Gaps found

- Alert feedback matching was too broad because `circuit_id:feature` did not include observed/baseline buckets, source roles, appliance profile, circuit mode, power-flow mode, or context.
- Future expected alerts were blocked from notifications but could still be promoted as active possible-issue evidence.
- Alert evidence did not expose feedback status, effect, expiration, or the matching feedback fingerprint.
- Expected and unhelpful alert feedback did not have status-specific expiration defaults.
- Unhelpful alert feedback still needs the planned settings-recommendation hook.
- NILM feedback still needs stable fingerprint persistence across reclustering order changes.
- Recommendation undo/reset behavior remains a follow-up.

## Files inspected

- `custom_components/circuitsetup_energy_analyzer/alerting.py`
- `custom_components/circuitsetup_energy_analyzer/storage.py`
- `custom_components/circuitsetup_energy_analyzer/services.py`
- `custom_components/circuitsetup_energy_analyzer/panel.py`
- `custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-panel.js`
- `custom_components/circuitsetup_energy_analyzer/settings_advisor.py`
- `custom_components/circuitsetup_energy_analyzer/unknown_loads.py`
- `custom_components/circuitsetup_energy_analyzer/nilm.py`
- `custom_components/circuitsetup_energy_analyzer/coordinator.py`
- `custom_components/circuitsetup_energy_analyzer/processors/`
- `tests/`

## Implementation plan

This work follows the suggested early PR scope:

1. Add a deterministic alert feedback fingerprint helper.
2. Keep the existing `alert_feedback` storage key but store fingerprint-shaped payloads with status, source alert, timestamps, expiration, circuit, feature, and evidence count.
3. Preserve legacy `circuit_id:feature` feedback lookup as a backward-compatible fallback.
4. Annotate future matching alert evidence with feedback metadata.
5. Keep matching expected evidence in retained history while preventing it from becoming a new active possible-issue alert or notification.
6. Require stronger repeated evidence for future alerts that match not-helpful feedback.
7. Surface feedback metadata and adjusted repeated-evidence requirements in alert evidence payloads.
8. Document the remaining feedback-loop gaps for follow-up PRs.

## Tests added

- `test_alert_feedback_fingerprint_is_stable_across_alert_timestamps`
- `test_alert_feedback_fingerprint_uses_context_without_timestamps`
- `test_feature_store_round_trips_fingerprint_alert_feedback`
- `test_expected_alert_feedback_suppresses_matching_future_notification`
- `test_expected_alert_feedback_does_not_suppress_unrelated_feature`
- `test_alert_evidence_payload_explains_expected_feedback_state`
- `test_policy_supports_adjusted_min_repeated_requirement`
- `test_unhelpful_feedback_raises_future_alert_requirement`
- `test_alert_evidence_payload_explains_unhelpful_adjusted_requirement`
