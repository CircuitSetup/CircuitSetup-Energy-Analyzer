# NILM Appliance Identity Audit

## Current Identity

At `f66df7a`, a persisted NILM assignment has an `assignment_id`, appliance
metadata, the owning mains `circuit_id`, validation state, session IDs, and a
bounded assignment-filtered history. Virtual entity/device IDs also include the
assignment. There is no canonical logical appliance key such as
`nilm:<assignment_id>` shared by detail, alerts, attention, and navigation.

## Current Data Flow

- Assignments: `FeatureStoreData.nilm_appliance_assignments_by_circuit`
- Sessions: `FeatureStoreData.nilm_session_history_by_circuit`, capped by
  retention and count
- Detail: `appliance_detail._nilm_detail`
- Virtual state: `nilm_virtual.nilm_virtual_appliance_states`
- Workspace payload: `panel.nilm_workspace_payload`
- Evidence links: `alert_links.alert_evidence_path` and panel action builders

## Complete

- Assignment persistence and versioned migration
- Assignment-filtered workspace sessions and bounded history
- Virtual running state, estimated power/energy, lifecycle, and confidence
- Mains source context in NILM detail
- Review services and workspace actions

## Partial Or Missing

- Canonical key `nilm:<assignment_id>`: missing
- Assignment-specific runtime and run count in Appliance Detail: missing
- Assignment session timeline in the detail model: history graph only
- Restart reconstruction: persisted sessions exist, but live virtual state can
  depend on in-memory unmatched edges
- Alert target: assignment features may exist, while evidence/detail navigation
  can still target the mains circuit
- Validation gate: lifecycle/confidence gates exist; confirmed-session,
  distinct-day, and false-positive thresholds are not combined
- Today vs Normal: absent for NILM detail
- Direct-meter conversion preserving label/history: absent

## Compatibility Requirements

- Keep assignment ID, mains circuit ID, mains source entity, and appliance ID
  separate.
- Preserve existing assignment and session storage; migrate additively.
- Keep mains visible as source context without using mains history as appliance
  history.
- Keep current panel/API/service paths and virtual entity IDs stable.
- Route new NILM findings to the canonical assignment detail while retaining
  circuit context for evidence and masking.
