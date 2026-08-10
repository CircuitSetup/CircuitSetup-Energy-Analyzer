from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from statistics import median
from typing import Any

from ..const import CONF_ENABLE_EXPERIMENTAL_NILM, DOMAIN
from ..demo import demo_nilm_workspace_seed, is_demo_config
from ..discovery import sensor_metadata_role_conflict, sensor_role_from_metadata
from ..models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitMode,
    NilmSourceKind,
    SensorRole,
)
from ..nilm import (
    KnownLoadTopology,
    NilmEdge,
    build_nilm_assignment_model,
    known_load_topology_for_config,
    nilm_signature_is_assignable,
    normalize_nilm_assignment_model,
)
from ..profiles import nilm_source_kind, supports_direct_appliance_analysis


def configured_primary_assignment_id(circuit_id: str) -> str:
    """Return the stable configured-primary assignment ID for a source."""
    return f"{circuit_id}-configured-primary"


def nilm_assignment_is_active(assignment: Mapping[str, Any]) -> bool:
    """Return whether an assignment can receive reviewed evidence."""
    return str(assignment.get("lifecycle_state") or "").strip().lower() not in {
        "ignored",
        "retired",
    }


def nilm_assignment_publication_reason(
    assignment: Mapping[str, Any],
) -> str | None:
    """Return why an assignment cannot publish, or None when it can."""
    state = str(assignment.get("lifecycle_state") or "").strip().lower()
    if assignment.get("conversion_state") == "direct_meter":
        return "A direct-meter conversion cannot republish duplicate NILM entities."
    if state in {"ignored", "retired"}:
        return "Restore this hidden load before publishing."
    fingerprints = _clean_string_list(assignment.get("signature_fingerprints"))
    model_directions = {
        str(prototype.get("direction") or "")
        for prototype in normalize_nilm_assignment_model(assignment)[
            "transition_prototypes"
        ]
    }
    if (
        fingerprints
        and not any(map(nilm_signature_is_assignable, fingerprints))
        and model_directions != {"on", "off"}
    ):
        return (
            "A complete appliance run is still missing. Confirm one session with "
            "both the power-on and matching power-off transition so NILM can track "
            "state and energy before publishing."
        )
    if assignment.get("publish_entities") is True or state == "published":
        return None
    if state not in {"assigned", "validated", "ready_to_publish"}:
        return "Validate this assignment before publishing."
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    if (
        assignment.get("role") == "primary"
        or assignment_id.endswith("-configured-primary")
    ) and not _clean_string_list(assignment.get("signature_fingerprints")):
        return "Bind the configured primary signature before publishing."
    if not any(
        _clean_string_list(assignment.get(key))
        for key in ("signature_fingerprints", "session_ids", "label_interval_ids")
    ):
        return "Assign at least one detected load before publishing."
    if (
        assignment.get("helper_required") is True
        or assignment.get("requires_helper") is True
    ) and not _clean_string_list(assignment.get("helper_links")):
        return "Confirm a qualifying helper circuit before publishing."
    if _nonnegative_float_value(assignment.get("confidence"), default=0.0) < 0.8:
        return "Confirm more matching cycles until confidence reaches 80%."
    return None


class NilmController:
    """Own NILM appliance assignment lifecycle workflows."""

    def __init__(
        self,
        coordinator: Any,
        *,
        label_interval_max_items: int,
        assignment_max_items: int,
    ) -> None:
        self._coordinator = coordinator
        self._clean_string_list = _clean_string_list
        self._append_unique = _append_unique
        self._nonnegative_float_value = _nonnegative_float_value
        self._label_interval_datetime = _nilm_label_interval_datetime
        self._label_interval_id = _nilm_label_interval_id
        self._signature_fingerprint_value = _nilm_signature_fingerprint_value
        self._signature_assignment_label = _nilm_signature_assignment_label
        self._label_interval_max_items = label_interval_max_items
        self._round_optional_number = _round_optional_number
        self._assignment_interval_matches = _nilm_assignment_interval_matches
        self._overlap_seconds = _nilm_overlap_seconds
        self._validation_coverage_overlap_seconds = (
            _nilm_validation_coverage_overlap_seconds
        )
        self._float_or_none = _float_or_none
        self._datetime_or_none = _datetime_or_none
        self._assignment_appliance_id = _nilm_assignment_appliance_id
        self._assignment_id = _nilm_assignment_id
        self._assignment_max_items = assignment_max_items
        self._review_transaction_lock = asyncio.Lock()
        self._sample_processor: Any | None = None
        self._topology_processor: Any | None = None
        self._total_events_by_circuit: Any | None = None
        self._unmatched_edges_by_circuit: Any | None = None

    def configure_processors(
        self,
        *,
        sample_processor: Any,
        topology_processor: Any,
        total_events_by_circuit: Any,
        unmatched_edges_by_circuit: Any,
    ) -> None:
        """Attach NILM processors and runtime buckets after construction."""
        self._sample_processor = sample_processor
        self._topology_processor = topology_processor
        self._total_events_by_circuit = total_events_by_circuit
        self._unmatched_edges_by_circuit = unmatched_edges_by_circuit

    def enabled_for_config(self, config: Any) -> bool:
        """Return whether NILM processing is enabled for one circuit config."""
        coordinator = self._coordinator
        enabled = bool(
            coordinator.options.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                coordinator.entry_data.get(CONF_ENABLE_EXPERIMENTAL_NILM, False),
            )
        )
        return enabled and nilm_source_kind(config) is not None

    def clear_topology_state(self, circuit_id: str) -> None:
        """Clear retained NILM topology state and cached alert policy."""
        coordinator = self._coordinator
        coordinator.state.nilm_topology_status_by_circuit.pop(circuit_id, None)
        coordinator.state.nilm_topology_evidence_by_circuit.pop(circuit_id, None)
        coordinator.settings_controller.clear_nilm_topology_alert_policies(circuit_id)

    def process_sample(
        self,
        config: Any,
        sample: Any,
        events: Iterable[Any],
        context: Any | None = None,
    ) -> list[AlertEvidence]:
        """Process one NILM source sample and apply resulting state updates."""
        coordinator = self._coordinator
        result = self._sample_processor.process(
            sample,
            config,
            context or coordinator.context_builder.build(sample.timestamp),
            events=events,
        )
        coordinator.state_reducer.apply_updates(
            coordinator.state,
            result.state_updates,
        )
        if result.store_dirty:
            coordinator.store_persistence.mark_dirty()
        return list(result.alerts)

    def known_load_events(
        self,
        nilm_circuit_id: str,
        events: Iterable[Any],
    ) -> Iterable[Any]:
        """Yield events that may mask a mains NILM edge."""
        nilm_config = self._coordinator.circuit_registry.config_for_circuit(
            nilm_circuit_id
        )
        if (
            nilm_config is None
            or nilm_source_kind(nilm_config) is not NilmSourceKind.MAINS
        ):
            return
        known_load_circuit_ids = (
            self._coordinator.circuit_registry.known_load_circuit_ids
        )
        for event in events:
            if event.circuit_id == nilm_circuit_id:
                continue
            if (
                known_load_circuit_ids
                and event.circuit_id not in known_load_circuit_ids
            ):
                continue
            yield event

    def known_load_topology(self, circuit_id: str) -> KnownLoadTopology | None:
        """Return configured topology expectations for one known-load circuit."""
        registry = self._coordinator.circuit_registry
        config = registry.config_for_circuit(circuit_id)
        return known_load_topology_for_config(config) if config is not None else None

    def observe_known_load_topology(
        self,
        mains_config: Any,
        match: Any,
        context: Any | None = None,
    ) -> AlertEvidence | None:
        """Fold one known-load NILM topology match into analyzer state."""
        coordinator = self._coordinator
        result = self._topology_processor.process(
            mains_config,
            match,
            context or coordinator.context_builder.build(match.edge.timestamp),
        )
        coordinator.state_reducer.apply_updates(
            coordinator.state,
            result.state_updates,
        )
        return result.alerts[0] if result.alerts else None

    def helper_candidate_events(
        self, nilm_circuit_id: str, events: Iterable[Any]
    ) -> Iterable[Any]:
        """Yield current-entry direct-load events as correlation evidence."""
        registry = self._coordinator.circuit_registry
        for event in events:
            if event.circuit_id == nilm_circuit_id:
                continue
            config = registry.config_for_circuit(event.circuit_id)
            if config is not None and supports_direct_appliance_analysis(config):
                yield event

    def signature_payloads(
        self,
        circuit_id: str,
        signatures: Iterable[Any],
    ) -> list[dict[str, Any]]:
        """Build NILM signature review payloads for one circuit."""
        coordinator = self._coordinator
        return self._sample_processor._nilm_signature_payloads(
            circuit_id,
            signatures,
            coordinator.context_builder.build(coordinator.current_time()),
        )

    def refresh_state(self, circuit_id: str, context: Any | None = None) -> None:
        """Refresh derived NILM state for one circuit."""
        coordinator = self._coordinator
        result = self._sample_processor.refresh_state(
            circuit_id,
            context or coordinator.context_builder.build(coordinator.current_time()),
        )
        coordinator.state_reducer.apply_updates(
            coordinator.state,
            result.state_updates,
        )

    def seed_demo_state(self, config: Any, now: datetime) -> None:
        """Seed bundled NILM workspace demo data when the demo source is active."""
        if not is_demo_config(config):
            return

        coordinator = self._coordinator
        circuit_id = config.circuit_id
        seed = demo_nilm_workspace_seed(now, circuit_id=circuit_id)

        if not coordinator.store_data.nilm_signatures.get(circuit_id):
            coordinator.store_data.nilm_signatures[circuit_id] = _demo_seed_list(
                seed.get("signatures"),
            )
            coordinator.store_persistence.mark_dirty()

        if not coordinator.store_data.nilm_unknown_loads_by_circuit.get(circuit_id):
            unknown_loads = seed.get("unknown_loads")
            if isinstance(unknown_loads, Mapping):
                coordinator.store_data.nilm_unknown_loads_by_circuit[circuit_id] = dict(
                    unknown_loads
                )
            coordinator.store_persistence.mark_dirty()

        if not coordinator.store_data.nilm_session_history_by_circuit.get(circuit_id):
            coordinator.store_data.nilm_session_history_by_circuit[circuit_id] = (
                _demo_seed_list(seed.get("sessions"))
            )
            coordinator.store_persistence.mark_dirty()

        if not coordinator.store_data.nilm_label_intervals_by_circuit.get(circuit_id):
            coordinator.store_data.nilm_label_intervals_by_circuit[circuit_id] = (
                _demo_seed_list(seed.get("label_intervals"))
            )
            coordinator.store_persistence.mark_dirty()

        if not coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
            circuit_id,
        ):
            coordinator.store_data.nilm_appliance_assignments_by_circuit[circuit_id] = (
                _demo_seed_list(seed.get("assignments"))
            )
            coordinator.store_persistence.mark_dirty()

        total_events_by_circuit = self._total_events_by_circuit
        unmatched_edges_by_circuit = self._unmatched_edges_by_circuit
        total_events_by_circuit[circuit_id] = max(
            total_events_by_circuit[circuit_id],
            int(seed.get("total_events") or 0),
        )
        if not unmatched_edges_by_circuit[circuit_id]:
            unmatched_edges_by_circuit[circuit_id] = _demo_nilm_edges(seed.get("edges"))
        unmatched_edges = unmatched_edges_by_circuit[circuit_id]
        unmatched_edges_by_circuit[circuit_id] = unmatched_edges[:8]

    def hydrate_state_from_store(self) -> None:
        """Hydrate NILM runtime state from retained store data."""
        coordinator = self._coordinator
        rebuilt = self._normalize_legacy_expected_records()
        for (
            circuit_id,
            assignments,
        ) in coordinator.store_data.nilm_appliance_assignments_by_circuit.items():
            history = coordinator.store_data.nilm_session_history_by_circuit.get(
                circuit_id, ()
            )
            label_intervals = (
                coordinator.store_data.nilm_label_intervals_by_circuit.get(
                    circuit_id, ()
                )
            )
            for assignment in assignments:
                normalized = normalize_nilm_assignment_model(assignment)
                model = build_nilm_assignment_model(
                    assignment,
                    history,
                    label_intervals=label_intervals,
                )
                if (
                    model["transition_prototypes"]
                    and (
                        model["power_states_w"] != normalized["power_states_w"]
                        or model["transition_prototypes"]
                        != normalized["transition_prototypes"]
                    )
                ):
                    assignment.update(model)
                    rebuilt = True
                else:
                    assignment.update(normalized)
        if rebuilt:
            coordinator.store_persistence.mark_dirty()
        for circuit_id, signatures in coordinator.store_data.nilm_signatures.items():
            for signature in signatures:
                if signature.get("ignored") is True:
                    coordinator.ignored_nilm_signatures.add(
                        (circuit_id, str(signature.get("signature_id", "")))
                    )
            self.refresh_state(circuit_id)

    def _normalize_legacy_expected_records(self) -> bool:
        """Reopen persisted NILM records that used the removed Expected state."""
        store_data = self._coordinator.store_data
        circuit_ids = {
            *store_data.nilm_signatures,
            *store_data.nilm_appliance_assignments_by_circuit,
            *store_data.nilm_session_history_by_circuit,
            *store_data.nilm_label_intervals_by_circuit,
        }
        changed = False
        for circuit_id in circuit_ids:
            assignments = store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id,
                [],
            )
            expected_assignment_ids = {
                str(assignment.get("assignment_id") or "").strip()
                for assignment in assignments
                if str(assignment.get("lifecycle_state") or "").strip().lower()
                == "expected"
            }
            for signature in store_data.nilm_signatures.get(circuit_id, []):
                if (
                    str(signature.get("review_state") or "").strip().lower()
                    != "expected"
                    and signature.get("expected") is not True
                ):
                    continue
                signature.pop("expected", None)
                signature.pop("assignment_id", None)
                signature["review_state"] = "new"
                changed = True
            if not expected_assignment_ids:
                continue
            assignments[:] = [
                assignment
                for assignment in assignments
                if str(assignment.get("assignment_id") or "").strip()
                not in expected_assignment_ids
            ]
            for collection in (
                store_data.nilm_session_history_by_circuit.get(circuit_id, []),
                store_data.nilm_label_intervals_by_circuit.get(circuit_id, []),
            ):
                for evidence in collection:
                    if (
                        isinstance(evidence, dict)
                        and str(evidence.get("assignment_id") or "").strip()
                        in expected_assignment_ids
                    ):
                        evidence.pop("assignment_id", None)
            changed = True
        return changed

    def _rebuild_assignment_model(
        self, circuit_id: str, assignment: dict[str, Any]
    ) -> None:
        assignment.update(
            build_nilm_assignment_model(
                assignment,
                self._coordinator.store_data.nilm_session_history_by_circuit.get(
                    circuit_id, ()
                ),
                label_intervals=self._coordinator.store_data.nilm_label_intervals_by_circuit.get(
                    circuit_id, ()
                ),
            )
        )

    def upsert_assignment(
        self,
        circuit_id: str,
        *,
        label: str,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
        signature_fingerprint: Any = None,
        session_id: str | None = None,
        label_interval_id: str | None = None,
        lifecycle_state: str = "assigned",
        confidence: Any = 1.0,
        role: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a durable NILM appliance assignment."""
        assignment_id_text = str(assignment_id or "").strip()
        if assignment_id_text == configured_primary_assignment_id(circuit_id):
            config = self._coordinator.circuit_registry.config_for_circuit(circuit_id)
            if nilm_source_kind(config) is not NilmSourceKind.PRIMARY_MIXED:
                raise ValueError(
                    f"Circuit '{circuit_id}' has no configured primary assignment."
                )
            label = config.name
            appliance_id = config.circuit_id
            appliance_profile = config.appliance_profile.value
            role = "primary"
        label_text = str(label or "").strip()
        if not label_text:
            raise ValueError("Missing label.")
        appliance_id_text = str(
            appliance_id or ""
        ).strip() or self._assignment_appliance_id(label_text)
        assignments_by_circuit = (
            self._coordinator.store_data.nilm_appliance_assignments_by_circuit
        )
        assignments = assignments_by_circuit.setdefault(circuit_id, [])
        assignment = next(
            (
                item
                for item in assignments
                if (
                    (
                        assignment_id_text
                        and item.get("assignment_id") == assignment_id_text
                    )
                    or (
                        not assignment_id_text
                        and item.get("appliance_id") == appliance_id_text
                    )
                )
            ),
            None,
        )
        now = self._coordinator.current_time().isoformat()
        if assignment is None:
            assignment = {
                "assignment_id": assignment_id_text
                or self._assignment_id(circuit_id, appliance_id_text),
                "appliance_id": appliance_id_text,
                "display_name": label_text,
                "appliance_profile": str(appliance_profile or "").strip() or None,
                "mains_circuit_id": circuit_id,
                "signature_fingerprints": [],
                "session_ids": [],
                "label_interval_ids": [],
                "lifecycle_state": lifecycle_state,
                "confidence": 0.0,
                "created_at": now,
                "updated_at": now,
                "created_device": False,
                "publish_entities": False,
                "role": role or "component",
                "power_states_w": [],
                "transition_prototypes": [],
                "model_confidence": 0.0,
                "model_revision": 0,
            }
            assignment["appliance_key"] = f"nilm:{assignment['assignment_id']}"
            assignments.append(assignment)
        else:
            assignments[:] = [item for item in assignments if item is not assignment]
            assignments.append(assignment)
            assignment["display_name"] = label_text
            if appliance_profile:
                assignment["appliance_profile"] = str(appliance_profile).strip()
            assignment["lifecycle_state"] = lifecycle_state
            if role is not None:
                assignment["role"] = role
            assignment["updated_at"] = now
            assignment["appliance_key"] = f"nilm:{assignment['assignment_id']}"

        self._append_unique(
            assignment.setdefault("signature_fingerprints", []),
            signature_fingerprint,
        )
        self._append_unique(assignment.setdefault("session_ids", []), session_id)
        self._append_unique(
            assignment.setdefault("label_interval_ids", []),
            label_interval_id,
        )
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 1.0
        assignment["confidence"] = max(
            float(assignment.get("confidence") or 0.0),
            max(min(confidence_value, 1.0), 0.0),
        )
        del assignments[: -self._assignment_max_items]
        return assignment

    def assignment_session_history(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> list[dict[str, Any]]:
        """Return newest-first durable history owned by one assignment."""
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        assignment_id_text = str(assignment.get("assignment_id") or "").strip()
        session_ids = set(self._clean_string_list(assignment.get("session_ids")))
        history = self._coordinator.store_data.nilm_session_history_by_circuit.get(
            circuit_id,
            (),
        )
        sessions = [
            dict(session)
            for session in history
            if isinstance(session, Mapping)
            and _nilm_session_assignment_matches(
                session,
                assignment_id=assignment_id_text,
                session_ids=session_ids,
            )
        ]
        return sorted(
            sessions,
            key=lambda session: (
                self._datetime_or_none(session.get("end") or session.get("start"))
                or datetime.min.replace(tzinfo=UTC)
            ),
            reverse=True,
        )

    async def async_label_nilm_signature(
        self,
        circuit_id: str,
        signature_id: str,
        label: str,
    ) -> None:
        """Persist a user-confirmed label for a NILM signature."""
        coordinator = self._coordinator
        signatures = coordinator.store_data.nilm_signatures.setdefault(circuit_id, [])
        for signature in signatures:
            if signature.get("signature_id") == signature_id:
                signature["user_label"] = label
                await self._async_save_nilm_review_change(circuit_id)
                return
        signatures.append({"signature_id": signature_id, "user_label": label})
        await self._async_save_nilm_review_change(circuit_id)

    async def async_label_nilm_interval(
        self,
        circuit_id: str,
        *,
        label: str,
        start: Any,
        end: Any,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
        mains_entity_id: str | None = None,
        ground_truth_entity_id: str | None = None,
        validation_start: Any = None,
        validation_end: Any = None,
        interval_id: str | None = None,
        source: str = "manual",
        confidence: float = 1.0,
        observed_transition_w: Any = None,
        median_power_w: Any = None,
        measured_energy_kwh: Any = None,
    ) -> dict[str, Any]:
        """Persist one labeled NILM interval atomically."""
        async with self._review_transaction_lock:
            store_data = self._coordinator.store_data
            snapshots = {
                name: deepcopy(getattr(store_data, name))
                for name in (
                    "nilm_appliance_assignments_by_circuit",
                    "nilm_label_intervals_by_circuit",
                    "nilm_signatures",
                    "nilm_session_history_by_circuit",
                )
            }
            try:
                return await self._async_label_nilm_interval(
                    circuit_id,
                    label=label,
                    start=start,
                    end=end,
                    appliance_id=appliance_id,
                    appliance_profile=appliance_profile,
                    assignment_id=assignment_id,
                    mains_entity_id=mains_entity_id,
                    ground_truth_entity_id=ground_truth_entity_id,
                    validation_start=validation_start,
                    validation_end=validation_end,
                    interval_id=interval_id,
                    source=source,
                    confidence=confidence,
                    observed_transition_w=observed_transition_w,
                    median_power_w=median_power_w,
                    measured_energy_kwh=measured_energy_kwh,
                )
            except Exception:
                for name, snapshot in snapshots.items():
                    setattr(store_data, name, snapshot)
                self._coordinator.async_set_updated_data(self._coordinator.state)
                raise

    async def _async_label_nilm_interval(
        self,
        circuit_id: str,
        *,
        label: str,
        start: Any,
        end: Any,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
        mains_entity_id: str | None = None,
        ground_truth_entity_id: str | None = None,
        validation_start: Any = None,
        validation_end: Any = None,
        interval_id: str | None = None,
        source: str = "manual",
        confidence: float = 1.0,
        observed_transition_w: Any = None,
        median_power_w: Any = None,
        measured_energy_kwh: Any = None,
    ) -> dict[str, Any]:
        """Persist a user-labeled NILM graph interval."""
        label_text = str(label or "").strip()
        if not label_text:
            raise ValueError("Missing label.")
        start_dt = self._label_interval_datetime(start, "start")
        end_dt = self._label_interval_datetime(end, "end")
        if end_dt <= start_dt:
            raise ValueError("NILM label interval end must be after start.")

        coordinator = self._coordinator
        now_dt = coordinator.current_time()
        now = now_dt.isoformat()
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()
        interval_id_text = str(interval_id or "").strip() or self._label_interval_id(
            circuit_id,
            start_iso,
            end_iso,
            label_text,
        )
        intervals = coordinator.store_data.nilm_label_intervals_by_circuit.setdefault(
            circuit_id,
            [],
        )
        existing = next(
            (
                interval
                for interval in intervals
                if interval.get("interval_id") == interval_id_text
            ),
            None,
        )
        assignment_id_text = str(
            assignment_id or (existing or {}).get("assignment_id") or ""
        ).strip()
        linked_assignment = (
            self.assignment_for_id(circuit_id, assignment_id_text)
            if assignment_id_text
            else None
        )
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 1.0
        payload: dict[str, Any] = {
            "interval_id": interval_id_text,
            "mains_circuit_id": circuit_id,
            "appliance_id": str(appliance_id or label_text).strip(),
            "label": label_text,
            "start": start_iso,
            "end": end_iso,
            "source": str(source or "manual").strip() or "manual",
            "confidence": max(min(confidence_value, 1.0), 0.0),
            "mains_entity_id": str(mains_entity_id or "").strip(),
            "created_at": str(existing.get("created_at") if existing else now),
            "updated_at": now,
        }
        if existing and observed_transition_w is None:
            previous_transition_w = existing.get("observed_transition_w")
            if (
                isinstance(previous_transition_w, (int, float))
                and not isinstance(previous_transition_w, bool)
                and math.isfinite(float(previous_transition_w))
                and previous_transition_w >= 0
            ):
                payload["observed_transition_w"] = float(previous_transition_w)
        if observed_transition_w is not None:
            if isinstance(observed_transition_w, bool):
                raise ValueError("Invalid observed transition watts.")
            try:
                transition_w = float(observed_transition_w)
            except (TypeError, ValueError) as err:
                raise ValueError("Invalid observed transition watts.") from err
            if not math.isfinite(transition_w) or transition_w < 0.0:
                raise ValueError("Invalid observed transition watts.")
            payload["observed_transition_w"] = transition_w
        for key, value in (
            ("median_power_w", median_power_w),
            ("measured_energy_kwh", measured_energy_kwh),
        ):
            if value is None:
                if existing and self._float_or_none(existing.get(key)) is not None:
                    payload[key] = float(existing[key])
                continue
            if isinstance(value, bool):
                raise ValueError(f"Invalid {key}.")
            parsed = self._float_or_none(value)
            if parsed is None or parsed < 0:
                raise ValueError(f"Invalid {key}.")
            payload[key] = parsed
        ground_truth_text = str(ground_truth_entity_id or "").strip()
        if ground_truth_text:
            payload["ground_truth_entity_id"] = ground_truth_text
        if assignment_id_text:
            payload["assignment_id"] = assignment_id_text
        if validation_start is not None and validation_end is not None:
            validation_start_dt = self._label_interval_datetime(
                validation_start,
                "validation_start",
            )
            validation_end_dt = self._label_interval_datetime(
                validation_end,
                "validation_end",
            )
            if validation_end_dt <= validation_start_dt:
                raise ValueError("NILM validation end must be after start.")
            payload["validation_start"] = validation_start_dt.isoformat()
            payload["validation_end"] = validation_end_dt.isoformat()

        if existing is None:
            intervals.append(payload)
        else:
            existing.clear()
            existing.update(payload)
        if linked_assignment is not None:
            self._append_unique(
                linked_assignment.setdefault("label_interval_ids", []),
                interval_id_text,
            )
            linked_assignment["updated_at"] = now
        assignment = linked_assignment
        profile_text = str(appliance_profile or "").strip()
        if profile_text:
            assignment = self.upsert_assignment(
                circuit_id,
                label=label_text,
                appliance_id=payload["appliance_id"],
                appliance_profile=profile_text,
                assignment_id=assignment_id_text or None,
                label_interval_id=interval_id_text,
                lifecycle_state="needs_validation",
                confidence=payload["confidence"],
            )
            payload["assignment_id"] = assignment["assignment_id"]
            if existing is not None:
                existing["assignment_id"] = assignment["assignment_id"]
        if assignment is not None and self._auto_link_configured_primary_signature(
            circuit_id,
            assignment,
            (payload,),
        ):
            self._rebuild_assignment_model(circuit_id, assignment)
        del intervals[: -self._label_interval_max_items]

        coordinator.store_persistence.mark_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now_dt)
        return dict(payload)

    async def async_delete_nilm_label_interval(
        self,
        circuit_id: str,
        interval_id: str,
    ) -> bool:
        """Delete a user-labeled NILM graph interval."""
        interval_id_text = str(interval_id or "").strip()
        if not interval_id_text:
            raise ValueError("Missing interval_id.")
        coordinator = self._coordinator
        intervals = coordinator.store_data.nilm_label_intervals_by_circuit.setdefault(
            circuit_id,
            [],
        )
        remaining = [
            interval
            for interval in intervals
            if interval.get("interval_id") != interval_id_text
        ]
        if len(remaining) == len(intervals):
            return False
        coordinator.store_data.nilm_label_intervals_by_circuit[circuit_id] = remaining
        now_dt = coordinator.current_time()
        now = now_dt.isoformat()
        assignments = (
            coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id, ()
            )
        )
        for assignment in assignments:
            interval_ids = self._clean_string_list(
                assignment.get("label_interval_ids")
            )
            if interval_id_text in interval_ids:
                assignment["label_interval_ids"] = [
                    value for value in interval_ids if value != interval_id_text
                ]
                assignment["updated_at"] = now
        coordinator.store_persistence.mark_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now_dt)
        return True

    async def async_save_nilm_interval_changes(
        self,
        circuit_id: str,
        *,
        label: str,
        intervals: Iterable[Mapping[str, Any]],
        removed_interval_ids: Iterable[str] = (),
        assignment_id: str | None = None,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
    ) -> dict[str, Any]:
        """Atomically save a NILM assignment's interval membership."""
        async with self._review_transaction_lock:
            return await self._async_save_nilm_interval_changes(
                circuit_id,
                label=label,
                intervals=intervals,
                removed_interval_ids=removed_interval_ids,
                assignment_id=assignment_id,
                appliance_id=appliance_id,
                appliance_profile=appliance_profile,
            )

    async def _async_save_nilm_interval_changes(
        self,
        circuit_id: str,
        *,
        label: str,
        intervals: Iterable[Mapping[str, Any]],
        removed_interval_ids: Iterable[str] = (),
        assignment_id: str | None = None,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
    ) -> dict[str, Any]:
        label_text = str(label or "").strip()
        if not label_text:
            raise ValueError("Missing label.")
        drafts = list(intervals)
        if not all(isinstance(draft, Mapping) for draft in drafts):
            raise ValueError("Each NILM interval must be a mapping.")
        removed_ids = set(self._clean_string_list(removed_interval_ids))
        coordinator = self._coordinator
        store_data = coordinator.store_data
        assignment_id_text = str(assignment_id or "").strip()
        if removed_ids and not assignment_id_text:
            raise ValueError("assignment_id is required when removing intervals.")
        existing_assignment = (
            self.assignment_for_id(circuit_id, assignment_id_text)
            if assignment_id_text
            else None
        )
        if existing_assignment is not None and not nilm_assignment_is_active(
            existing_assignment
        ):
            raise ValueError(
                "NILM intervals can only be saved to an active assignment."
            )
        appliance_id_text = str(
            appliance_id
            or (existing_assignment or {}).get("appliance_id")
            or label_text
        ).strip()
        existing_by_id = {
            str(interval.get("interval_id") or "").strip(): interval
            for interval in store_data.nilm_label_intervals_by_circuit.get(
                circuit_id, ()
            )
            if isinstance(interval, Mapping)
        }
        if removed_ids:
            owned_ids = set(
                self._clean_string_list(existing_assignment.get("label_interval_ids"))
            )
            stale_removed_ids = sorted(
                interval_id
                for interval_id in removed_ids
                if interval_id not in owned_ids
                or str(
                    existing_by_id.get(interval_id, {}).get("assignment_id") or ""
                ).strip()
                != assignment_id_text
            )
            if stale_removed_ids:
                raise ValueError(
                    "Removed interval no longer belongs to the submitted assignment: "
                    + ", ".join(stale_removed_ids)
                )
        now_dt = coordinator.current_time()
        now = now_dt.isoformat()
        payloads: list[dict[str, Any]] = []
        interval_ids: set[str] = set()
        for draft in drafts:
            start_dt = self._label_interval_datetime(draft.get("start"), "start")
            end_dt = self._label_interval_datetime(draft.get("end"), "end")
            if end_dt <= start_dt:
                raise ValueError("NILM label interval end must be after start.")
            draft_label = str(draft.get("label") or label_text).strip()
            if not draft_label:
                raise ValueError("Missing label.")
            start = start_dt.isoformat()
            end = end_dt.isoformat()
            interval_id = str(draft.get("interval_id") or "").strip() or (
                self._label_interval_id(circuit_id, start, end, draft_label)
            )
            if interval_id in interval_ids:
                raise ValueError(f"Duplicate interval_id '{interval_id}'.")
            interval_ids.add(interval_id)
            existing = existing_by_id.get(interval_id, {})
            confidence = draft.get("confidence", 1.0)
            if isinstance(confidence, bool):
                raise ValueError("Invalid confidence.")
            try:
                confidence_value = float(confidence)
            except (TypeError, ValueError) as err:
                raise ValueError("Invalid confidence.") from err
            if not math.isfinite(confidence_value) or confidence_value < 0.0:
                raise ValueError("Invalid confidence.")
            payload = {
                "interval_id": interval_id,
                "mains_circuit_id": circuit_id,
                "appliance_id": str(
                    draft.get("appliance_id") or appliance_id_text
                ).strip(),
                "label": draft_label,
                "start": start,
                "end": end,
                "source": str(draft.get("source") or "manual").strip() or "manual",
                "confidence": min(confidence_value, 1.0),
                "created_at": str(existing.get("created_at") or now),
                "updated_at": now,
            }
            for key in (
                "mains_entity_id",
                "ground_truth_entity_id",
                "validation_start",
                "validation_end",
                "observed_transition_w",
                "median_power_w",
                "measured_energy_kwh",
            ):
                value = draft.get(key, existing.get(key))
                if value is None:
                    continue
                if key == "observed_transition_w":
                    if isinstance(value, bool):
                        raise ValueError("Invalid observed transition watts.")
                    try:
                        parsed = float(value)
                    except (TypeError, ValueError) as err:
                        raise ValueError("Invalid observed transition watts.") from err
                    if not math.isfinite(parsed) or parsed < 0.0:
                        raise ValueError("Invalid observed transition watts.")
                    payload[key] = parsed
                elif key in {"median_power_w", "measured_energy_kwh"}:
                    if isinstance(value, bool):
                        raise ValueError(f"Invalid {key}.")
                    parsed = self._float_or_none(value)
                    if parsed is None or not math.isfinite(parsed) or parsed < 0.0:
                        raise ValueError(f"Invalid {key}.")
                    payload[key] = parsed
                elif key in draft or key in existing:
                    payload[key] = value
            payloads.append(payload)

        stored_interval_count = len(
            store_data.nilm_label_intervals_by_circuit.get(circuit_id, ())
        )
        added_interval_count = sum(
            payload["interval_id"] not in existing_by_id for payload in payloads
        )
        if (
            stored_interval_count + added_interval_count
            > self._label_interval_max_items
        ):
            raise ValueError(
                f"A circuit can retain at most {self._label_interval_max_items} "
                "NILM label intervals."
            )

        snapshots = {
            name: deepcopy(getattr(store_data, name))
            for name in (
                "nilm_appliance_assignments_by_circuit",
                "nilm_label_intervals_by_circuit",
                "nilm_signatures",
                "nilm_session_history_by_circuit",
            )
        }
        try:
            assignment = (
                existing_assignment
                if existing_assignment is not None
                else self.upsert_assignment(
                    circuit_id,
                    label=label_text,
                    appliance_id=appliance_id_text,
                    appliance_profile=appliance_profile,
                    lifecycle_state="needs_validation",
                )
            )
            assignment_id_text = str(assignment["assignment_id"])
            selected_ids = interval_ids | removed_ids
            assignments = store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id, ()
            )
            previous_interval_ids = {
                id(candidate): self._clean_string_list(
                    candidate.get("label_interval_ids")
                )
                for candidate in assignments
            }
            for candidate in assignments:
                candidate["label_interval_ids"] = [
                    value
                    for value in self._clean_string_list(
                        candidate.get("label_interval_ids")
                    )
                    if value not in selected_ids
                ]
            assignment["label_interval_ids"] = self._clean_string_list(
                assignment.get("label_interval_ids")
            ) + [interval["interval_id"] for interval in payloads]
            assignment["updated_at"] = now
            updated_by_id = {payload["interval_id"]: payload for payload in payloads}
            stored_intervals = []
            for interval in store_data.nilm_label_intervals_by_circuit.get(
                circuit_id, ()
            ):
                interval_id = str(interval.get("interval_id") or "").strip()
                if interval_id in updated_by_id:
                    stored_intervals.append(updated_by_id.pop(interval_id))
                else:
                    preserved = dict(interval)
                    if interval_id in removed_ids:
                        preserved["assignment_id"] = None
                    stored_intervals.append(preserved)
            stored_intervals.extend(updated_by_id.values())
            for interval in stored_intervals:
                if interval["interval_id"] in interval_ids:
                    interval["assignment_id"] = assignment_id_text
            store_data.nilm_label_intervals_by_circuit[circuit_id] = stored_intervals
            self._auto_link_configured_primary_signature(
                circuit_id,
                assignment,
                payloads,
            )
            affected_assignments = [
                candidate
                for candidate in assignments
                if previous_interval_ids.get(id(candidate), [])
                != self._clean_string_list(candidate.get("label_interval_ids"))
            ]
            if not any(candidate is assignment for candidate in affected_assignments):
                affected_assignments.append(assignment)
            for candidate in affected_assignments:
                self._update_assignment_duration_bounds(circuit_id, candidate)
                self._rebuild_assignment_model(circuit_id, candidate)
            coordinator.store_persistence.mark_dirty()
            coordinator.async_set_updated_data(coordinator.state)
            await coordinator.store_persistence.async_save_if_dirty(now_dt)
        except Exception:
            for name, snapshot in snapshots.items():
                setattr(store_data, name, snapshot)
            coordinator.store_persistence.mark_dirty()
            coordinator.async_set_updated_data(coordinator.state)
            try:
                await coordinator.store_persistence.async_save_if_dirty(now_dt)
            except Exception:
                pass
            raise
        return dict(assignment)

    async def async_delete_nilm_appliance_assignment(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> bool:
        """Permanently delete a retired NILM assignment, preserving evidence."""
        async with self._review_transaction_lock:
            return await self._async_delete_nilm_appliance_assignment(
                circuit_id, assignment_id
            )

    async def _async_delete_nilm_appliance_assignment(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> bool:
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        if str(assignment.get("lifecycle_state") or "").lower() != "retired":
            raise ValueError("Only retired NILM assignments can be deleted.")
        coordinator = self._coordinator
        store_data = coordinator.store_data
        assignment_id_text = str(assignment_id).strip()
        entity_state = await self._async_wait_for_assignment_entities(
            assignment_id_text, False
        )
        if entity_state is True:
            raise ValueError(
                f"Deleting assignment '{assignment_id_text}' requires its Home "
                "Assistant entities to be removed first."
            )
        if entity_state is not False:
            raise ValueError(
                f"Deleting assignment '{assignment_id_text}' could not confirm "
                "that its Home Assistant entities are absent."
            )
        assignments = store_data.nilm_appliance_assignments_by_circuit.get(
            circuit_id, []
        )
        removed_assignments = [
            (index, candidate)
            for index, candidate in enumerate(assignments)
            if candidate.get("assignment_id") == assignment_id_text
        ]
        assignments[:] = [
            candidate
            for candidate in assignments
            if candidate.get("assignment_id") != assignment_id_text
        ]
        unassigned_evidence: list[tuple[str, str, str, dict[str, Any]]] = []
        for collection_name, record_id_key in (
            ("nilm_label_intervals_by_circuit", "interval_id"),
            ("nilm_session_history_by_circuit", "session_id"),
        ):
            collection = getattr(store_data, collection_name).get(circuit_id, ())
            for evidence in collection:
                if evidence.get("assignment_id") == assignment_id_text:
                    unassigned_evidence.append(
                        (
                            collection_name,
                            record_id_key,
                            str(evidence.get(record_id_key) or "").strip(),
                            evidence,
                        )
                    )
                    evidence.pop("assignment_id", None)
        signature_states: list[tuple[str, dict[str, Any], bool, Any]] = []
        for signature in store_data.nilm_signatures.get(circuit_id, ()):
            if signature.get("assignment_id") == assignment_id_text:
                signature_states.append(
                    (
                        str(signature.get("signature_id") or "").strip(),
                        signature,
                        "review_state" in signature,
                        signature.get("review_state"),
                    )
                )
                signature.pop("assignment_id", None)
                signature["review_state"] = "new"
        coordinator.store_persistence.mark_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        try:
            await coordinator.store_persistence.async_save_if_dirty(
                coordinator.current_time()
            )
        except Exception:
            for index, candidate in removed_assignments:
                assignments.insert(index, candidate)
            for collection_name, record_id_key, record_id, original in (
                unassigned_evidence
            ):
                collection = getattr(store_data, collection_name).get(circuit_id, ())
                evidence = next(
                    (
                        candidate
                        for candidate in collection
                        if record_id
                        and str(candidate.get(record_id_key) or "").strip() == record_id
                    ),
                    original,
                )
                evidence["assignment_id"] = assignment_id_text
            for signature_id, original, had_review_state, review_state in (
                signature_states
            ):
                signature = next(
                    (
                        candidate
                        for candidate in store_data.nilm_signatures.get(circuit_id, ())
                        if signature_id
                        and str(candidate.get("signature_id") or "").strip()
                        == signature_id
                    ),
                    original,
                )
                signature["assignment_id"] = assignment_id_text
                if had_review_state:
                    signature["review_state"] = review_state
                else:
                    signature.pop("review_state", None)
            coordinator.async_set_updated_data(coordinator.state)
            raise
        reload_entry = getattr(
            getattr(coordinator, "config_entry_controller", None),
            "async_reload",
            None,
        )
        if callable(reload_entry):
            await reload_entry()
        return True

    def _bind_nilm_signature_to_assignment(
        self,
        circuit_id: str,
        signature: dict[str, Any],
        assignment: dict[str, Any],
        fingerprint: str,
        *,
        replace_primary: bool,
    ) -> bool:
        """Attach one retained signature using the explicit-review mutation rules."""
        assignment_id = str(assignment.get("assignment_id") or "").strip()
        primary_id = configured_primary_assignment_id(circuit_id)
        if assignment_id == primary_id:
            previous_fingerprints = {
                value
                for value in self._clean_string_list(
                    assignment.get("signature_fingerprints")
                )
                if value != fingerprint and nilm_signature_is_assignable(value)
            }
            if previous_fingerprints and not replace_primary:
                return False
            assignment["signature_fingerprints"] = [fingerprint]
            for previous in self._coordinator.store_data.nilm_signatures.get(
                circuit_id, ()
            ):
                if previous is not signature and (
                    previous.get("assignment_id") == primary_id
                    or self._signature_fingerprint_value(
                        previous,
                        str(previous.get("signature_id") or ""),
                    )
                    in previous_fingerprints
                ):
                    previous.pop("assignment_id", None)
                    previous["review_state"] = "new"
                    previous.pop("user_label", None)
        else:
            self._append_unique(
                assignment.setdefault("signature_fingerprints", []),
                fingerprint,
            )
        signature["assignment_id"] = assignment_id
        signature["review_state"] = "assigned"
        signature["user_label"] = assignment["display_name"]
        signature.pop("ignored", None)
        signature_id = str(signature.get("signature_id") or "").strip()
        self._coordinator.ignored_nilm_signatures.discard((circuit_id, signature_id))
        self.remove_signature_from_other_assignments(
            circuit_id,
            fingerprint,
            assignment_id,
        )
        return True

    def _auto_link_configured_primary_signature(
        self,
        circuit_id: str,
        assignment: dict[str, Any],
        intervals: Iterable[Mapping[str, Any]],
    ) -> bool:
        """Bind safe primary evidence to exactly one retained signature."""
        primary_id = configured_primary_assignment_id(circuit_id)
        if (
            str(assignment.get("assignment_id") or "").strip() != primary_id
            or not nilm_assignment_is_active(assignment)
        ):
            return False
        saved_intervals = [
            interval for interval in intervals if isinstance(interval, Mapping)
        ]
        if not saved_intervals:
            return False
        matched_sessions: list[dict[str, Any]] = []
        candidate_fingerprints: set[str] = set()
        for session in self._coordinator.store_data.nilm_session_history_by_circuit.get(
            circuit_id, ()
        ):
            if not isinstance(session, dict) or not any(
                self._overlap_seconds(interval, session) > 0.0
                for interval in saved_intervals
            ):
                continue
            session_owner = str(session.get("assignment_id") or "").strip()
            fingerprint = str(session.get("signature_fingerprint") or "").strip()
            if (
                not session.get("end")
                or bool(session.get("ambiguous"))
                or bool(session.get("known_load_masked"))
                or not nilm_signature_is_assignable(fingerprint)
                or (session_owner and session_owner != primary_id)
            ):
                return False
            matched_sessions.append(session)
            candidate_fingerprints.add(fingerprint)
        if len(candidate_fingerprints) != 1:
            return False
        fingerprint = next(iter(candidate_fingerprints))
        retained_signatures = [
            signature
            for signature in self._coordinator.store_data.nilm_signatures.get(
                circuit_id, ()
            )
            if isinstance(signature, dict)
            if fingerprint
            in {
                str(signature.get(key) or "").strip()
                for key in (
                    "feedback_fingerprint",
                    "signature_fingerprint",
                    "signature_id",
                )
            }
            if not bool(signature.get("ignored"))
            if str(signature.get("review_state") or "").strip().lower()
            not in {"ignored", "merged"}
        ]
        if len(retained_signatures) != 1:
            return False
        signature = retained_signatures[0]
        signature_owner = str(
            signature.get("assignment_id")
            or signature.get("matched_assignment_id")
            or ""
        ).strip()
        if signature_owner and signature_owner != primary_id:
            return False
        assignments = (
            self._coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id, ()
            )
        )
        for candidate in assignments:
            if (
                fingerprint in self._clean_string_list(
                    candidate.get("signature_fingerprints")
                )
                and str(candidate.get("assignment_id") or "").strip() != primary_id
            ):
                return False
        if not self._bind_nilm_signature_to_assignment(
            circuit_id,
            signature,
            assignment,
            fingerprint,
            replace_primary=False,
        ):
            return False
        for session in matched_sessions:
            session["assignment_id"] = primary_id
            self._append_unique(
                assignment.setdefault("session_ids", []),
                str(session.get("session_id") or "").strip(),
            )
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        return True

    async def async_assign_nilm_signature(
        self,
        circuit_id: str,
        signature_id: str,
        *,
        label: str,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign a NILM signature to a durable appliance assignment."""
        signature = self.signature_for_review(circuit_id, signature_id)
        fingerprint = self._signature_fingerprint_value(signature, signature_id)
        assignment = self.upsert_assignment(
            circuit_id,
            label=label,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
            signature_fingerprint=fingerprint,
            lifecycle_state="assigned",
            confidence=signature.get("confidence", 1.0),
        )
        self._bind_nilm_signature_to_assignment(
            circuit_id,
            signature,
            assignment,
            fingerprint,
            replace_primary=True,
        )
        await self._async_save_nilm_review_change(circuit_id)
        return dict(assignment)

    async def async_assign_nilm_session(
        self,
        circuit_id: str,
        session_id: str,
        *,
        label: str,
        signature_fingerprint: str | None = None,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign a NILM session to a durable appliance assignment."""
        session_id_text = str(session_id or "").strip()
        if not session_id_text:
            raise ValueError("Missing session_id.")
        if signature_fingerprint is not None and not nilm_signature_is_assignable(
            signature_fingerprint
        ):
            raise ValueError(
                "Assign a complete detected component, not a raw edge session."
            )
        coordinator = self._coordinator
        assignment = self.upsert_assignment(
            circuit_id,
            label=label,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
            signature_fingerprint=signature_fingerprint,
            session_id=session_id_text,
            lifecycle_state="assigned",
        )
        assignment_id_text = str(assignment.get("assignment_id") or "").strip()
        assignments = coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
            circuit_id,
            [],
        )
        for candidate in assignments:
            if candidate is assignment:
                continue
            candidate["session_ids"] = [
                value
                for value in self._clean_string_list(candidate.get("session_ids"))
                if value != session_id_text
            ]
        for session in coordinator.store_data.nilm_session_history_by_circuit.get(
            circuit_id,
            (),
        ):
            if (
                isinstance(session, dict)
                and str(session.get("session_id") or "").strip() == session_id_text
            ):
                session["assignment_id"] = assignment_id_text
        coordinator.store_persistence.mark_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(
            coordinator.current_time()
        )
        return dict(assignment)

    async def async_assign_nilm_interval(
        self,
        circuit_id: str,
        interval_id: str,
        *,
        label: str,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Assign a NILM label interval to a durable appliance assignment."""
        async with self._review_transaction_lock:
            store_data = self._coordinator.store_data
            snapshots = {
                name: deepcopy(getattr(store_data, name))
                for name in (
                    "nilm_appliance_assignments_by_circuit",
                    "nilm_label_intervals_by_circuit",
                    "nilm_signatures",
                    "nilm_session_history_by_circuit",
                )
            }
            try:
                return await self._async_assign_nilm_interval(
                    circuit_id,
                    interval_id,
                    label=label,
                    appliance_id=appliance_id,
                    appliance_profile=appliance_profile,
                    assignment_id=assignment_id,
                )
            except Exception:
                for name, snapshot in snapshots.items():
                    setattr(store_data, name, snapshot)
                self._coordinator.async_set_updated_data(self._coordinator.state)
                raise

    async def _async_assign_nilm_interval(
        self,
        circuit_id: str,
        interval_id: str,
        *,
        label: str,
        appliance_id: str | None = None,
        appliance_profile: str | None = None,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        interval_id_text = str(interval_id or "").strip()
        coordinator = self._coordinator
        intervals = coordinator.store_data.nilm_label_intervals_by_circuit.setdefault(
            circuit_id,
            [],
        )
        interval = next(
            (item for item in intervals if item.get("interval_id") == interval_id_text),
            None,
        )
        if interval is None:
            raise ValueError(f"Unknown interval_id '{interval_id_text}'.")
        assignment = self.upsert_assignment(
            circuit_id,
            label=label or str(interval.get("label") or ""),
            appliance_id=appliance_id or str(interval.get("appliance_id") or ""),
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
            label_interval_id=interval_id_text,
            lifecycle_state="assigned",
            confidence=interval.get("confidence", 1.0),
        )
        assignments = coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
            circuit_id, ()
        )
        previous_interval_ids = {
            id(candidate): self._clean_string_list(
                candidate.get("label_interval_ids")
            )
            for candidate in assignments
        }
        for candidate in assignments:
            candidate["label_interval_ids"] = [
                value
                for value in self._clean_string_list(
                    candidate.get("label_interval_ids")
                )
                if value != interval_id_text
            ]
        self._append_unique(
            assignment.setdefault("label_interval_ids", []), interval_id_text
        )
        interval["assignment_id"] = assignment["assignment_id"]
        self._auto_link_configured_primary_signature(
            circuit_id,
            assignment,
            (interval,),
        )
        affected_assignments = [
            candidate
            for candidate in assignments
            if previous_interval_ids.get(id(candidate), [])
            != self._clean_string_list(candidate.get("label_interval_ids"))
        ]
        if not any(candidate is assignment for candidate in affected_assignments):
            affected_assignments.append(assignment)
        for candidate in affected_assignments:
            self._update_assignment_duration_bounds(circuit_id, candidate)
            self._rebuild_assignment_model(circuit_id, candidate)
        coordinator.store_persistence.mark_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(
            coordinator.current_time()
        )
        return dict(assignment)

    async def async_validate_nilm_session(
        self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a NILM session matched its appliance assignment."""
        return await self.async_record_nilm_session_validation(
            circuit_id,
            session_id,
            assignment_id=assignment_id,
            correct=True,
        )

    async def async_reject_nilm_session(
        self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a NILM session did not match its appliance assignment."""
        return await self.async_record_nilm_session_validation(
            circuit_id,
            session_id,
            assignment_id=assignment_id,
            correct=False,
        )

    async def async_validate_nilm_assignment_history(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Confirm assigned NILM sessions that overlap ground-truth intervals."""
        coordinator = self._coordinator
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        intervals = [
            interval
            for interval in coordinator.store_data.nilm_label_intervals_by_circuit.get(
                circuit_id,
                (),
            )
            if isinstance(interval, Mapping)
            and str(interval.get("ground_truth_entity_id") or "").strip()
            and self._assignment_interval_matches(interval, assignment)
        ]
        if not intervals:
            raise ValueError(
                "No matching ground-truth NILM label intervals were found for "
                "this assignment."
            )

        assignment_id_text = str(assignment.get("assignment_id") or "").strip()
        assignment_session_ids = set(
            self._clean_string_list(assignment.get("session_ids"))
        )
        matched_session_ids: list[str] = []
        conflicting_session_ids: list[str] = []
        matched_interval_ids: set[int] = set()
        power_errors: list[float] = []
        energy_errors: list[float] = []
        for session in coordinator.store_data.nilm_session_history_by_circuit.get(
            circuit_id,
            (),
        ):
            if not isinstance(session, Mapping):
                continue
            session_id = str(session.get("session_id") or "").strip()
            if not session_id:
                continue
            if not _nilm_session_assignment_matches(
                session,
                assignment_id=assignment_id_text,
                session_ids=assignment_session_ids,
            ):
                continue
            if not session.get("end"):
                continue
            overlapping_intervals = [
                interval
                for interval in intervals
                if self._overlap_seconds(interval, session) > 0
            ]
            if overlapping_intervals:
                self._append_unique(matched_session_ids, session_id)
                session_power = self._float_or_none(session.get("median_power_w"))
                session_energy = self._float_or_none(
                    session.get("estimated_energy_kwh")
                )
                for interval in overlapping_intervals:
                    matched_interval_ids.add(id(interval))
                    interval_power = self._float_or_none(interval.get("median_power_w"))
                    interval_energy = self._float_or_none(
                        interval.get(
                            "measured_energy_kwh",
                            interval.get("estimated_energy_kwh"),
                        ),
                    )
                    if session_power is not None and interval_power is not None:
                        power_errors.append(abs(session_power - interval_power))
                    if session_energy is not None and interval_energy is not None:
                        energy_errors.append(abs(session_energy - interval_energy))
            elif any(
                self._validation_coverage_overlap_seconds(interval, session) > 0
                for interval in intervals
            ):
                self._append_unique(conflicting_session_ids, session_id)

        confirmed = self._clean_string_list(assignment.get("confirmed_session_ids"))
        rejected = self._clean_string_list(assignment.get("rejected_session_ids"))
        newly_confirmed = [
            session_id
            for session_id in matched_session_ids
            if session_id not in confirmed
        ]
        newly_rejected = [
            session_id
            for session_id in conflicting_session_ids
            if session_id not in rejected
        ]
        if not matched_session_ids and not conflicting_session_ids:
            raise ValueError(
                "No matching ground-truth NILM sessions were found for this assignment."
            )

        for session_id in newly_confirmed:
            self._append_unique(confirmed, session_id)
            self._append_unique(assignment.setdefault("session_ids", []), session_id)
        rejected = [
            session_id for session_id in rejected if session_id not in newly_confirmed
        ]
        for session_id in newly_rejected:
            self._append_unique(rejected, session_id)
        confirmed = [
            session_id for session_id in confirmed if session_id not in newly_rejected
        ]

        now_dt = coordinator.current_time()
        now = now_dt.isoformat()
        current_confidence = self._nonnegative_float_value(
            assignment.get("confidence"),
            default=0.0,
        )
        confidence = min(
            1.0,
            round(current_confidence + (0.05 * len(newly_confirmed)), 3),
        )
        if newly_rejected:
            confidence = max(0.0, round(confidence - (0.15 * len(newly_rejected)), 3))
        assignment["confidence"] = confidence
        assignment["confirmed_session_ids"] = confirmed
        assignment["rejected_session_ids"] = rejected
        self._update_assignment_duration_bounds(circuit_id, assignment)
        self._rebuild_assignment_model(circuit_id, assignment)
        assignment["confirmed_sessions"] = len(confirmed)
        assignment["rejected_sessions"] = len(rejected)
        assignment["adjusted_sessions"] = len(
            self._clean_string_list(assignment.get("adjusted_session_ids")),
        )
        ground_truth_interval_count = len(intervals)
        matched_ground_truth_count = len(matched_interval_ids)
        missed_ground_truth_count = max(
            ground_truth_interval_count - matched_ground_truth_count,
            0,
        )
        false_positive_denominator = len(confirmed) + len(rejected)
        assignment["ground_truth_interval_count"] = ground_truth_interval_count
        assignment["matched_ground_truth_count"] = matched_ground_truth_count
        assignment["missed_ground_truth_count"] = missed_ground_truth_count
        assignment["false_positive_rate"] = (
            round(len(rejected) / false_positive_denominator, 3)
            if false_positive_denominator
            else 0.0
        )
        assignment["false_negative_rate"] = (
            round(missed_ground_truth_count / ground_truth_interval_count, 3)
            if ground_truth_interval_count
            else 0.0
        )
        assignment["median_power_error"] = (
            round(median(power_errors), 3) if power_errors else None
        )
        assignment["energy_estimate_error"] = (
            round(median(energy_errors), 3) if energy_errors else None
        )
        validation_starts: list[datetime] = []
        validation_ends: list[datetime] = []
        for interval in intervals:
            validation_start = self._datetime_or_none(
                interval.get("validation_start") or interval.get("start"),
            )
            validation_end = self._datetime_or_none(
                interval.get("validation_end") or interval.get("end"),
            )
            if validation_start is not None:
                validation_starts.append(validation_start)
            if validation_end is not None:
                validation_ends.append(validation_end)
        if validation_starts and validation_ends:
            assignment["validation_window_start"] = min(validation_starts).isoformat()
            assignment["validation_window_end"] = max(validation_ends).isoformat()
        has_conflicts = bool(conflicting_session_ids)
        if has_conflicts and assignment.get("lifecycle_state") != "retired":
            assignment["lifecycle_state"] = "conflict"
        elif assignment.get("lifecycle_state") not in {"published", "retired"}:
            assignment["lifecycle_state"] = "validated"
        assignment["last_validation"] = (
            "direct_meter_conflict" if has_conflicts else "history"
        )
        assignment["last_validated_at"] = now
        if has_conflicts:
            assignment["last_rejected_at"] = now
        assignment["updated_at"] = now
        coordinator.store_persistence.mark_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now_dt)
        return dict(assignment)

    async def async_confirm_nilm_configured_primary(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Confirm the configured appliance identity for a primary-mixed source."""
        expected_id = configured_primary_assignment_id(circuit_id)
        if str(assignment_id or "").strip() != expected_id:
            raise ValueError(
                f"Assignment '{assignment_id}' is not the configured primary."
            )
        config = self._coordinator.circuit_registry.config_for_circuit(circuit_id)
        if nilm_source_kind(config) is not NilmSourceKind.PRIMARY_MIXED:
            raise ValueError(
                f"Circuit '{circuit_id}' has no configured primary assignment."
            )
        assignment = self.assignment_for_id(circuit_id, expected_id)
        state = str(assignment.get("lifecycle_state") or "").strip().lower()
        if (
            state in {"ignored", "retired", "conflict"}
            or assignment.get("conversion_state") == "direct_meter"
        ):
            raise ValueError("Restore or resolve this configured primary first.")
        if state != "published":
            assignment["lifecycle_state"] = "validated"
        now_dt = self._coordinator.current_time()
        now = now_dt.isoformat()
        assignment["last_validation"] = "configured_primary"
        assignment["last_validated_at"] = now
        assignment["updated_at"] = now
        self._coordinator.store_persistence.mark_dirty()
        self._coordinator.async_set_updated_data(self._coordinator.state)
        await self._coordinator.store_persistence.async_save_if_dirty(now_dt)
        return dict(assignment)

    async def async_record_nilm_session_validation(
        self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None,
        correct: bool,
    ) -> dict[str, Any]:
        """Apply one user validation decision to a NILM appliance assignment."""
        session_id_text = str(session_id or "").strip()
        assignment = self.assignment_for_session(
            circuit_id,
            session_id_text,
            assignment_id=assignment_id,
        )
        self._append_unique(assignment.setdefault("session_ids", []), session_id_text)
        confirmed = self._clean_string_list(assignment.get("confirmed_session_ids"))
        rejected = self._clean_string_list(assignment.get("rejected_session_ids"))
        current_confidence = self._nonnegative_float_value(
            assignment.get("confidence"),
            default=0.0,
        )
        coordinator = self._coordinator
        now_dt = coordinator.current_time()
        now = now_dt.isoformat()
        if correct:
            already_confirmed = session_id_text in confirmed
            self._append_unique(confirmed, session_id_text)
            rejected = [value for value in rejected if value != session_id_text]
            if not already_confirmed:
                assignment["confidence"] = min(
                    1.0,
                    round(current_confidence + 0.05, 3),
                )
            if assignment.get("lifecycle_state") not in {"published", "retired"}:
                assignment["lifecycle_state"] = "validated"
            assignment["last_validation"] = "correct"
            assignment["last_validated_at"] = now
        else:
            already_rejected = session_id_text in rejected
            self._append_unique(rejected, session_id_text)
            confirmed = [value for value in confirmed if value != session_id_text]
            if not already_rejected:
                assignment["confidence"] = max(
                    0.0,
                    round(current_confidence - 0.15, 3),
                )
            if assignment.get("lifecycle_state") != "retired":
                assignment["lifecycle_state"] = "needs_validation"
            assignment["last_validation"] = "wrong_appliance"
            assignment["last_rejected_at"] = now
        assignment["confirmed_session_ids"] = confirmed
        assignment["rejected_session_ids"] = rejected
        self._update_assignment_duration_bounds(circuit_id, assignment)
        assignment["confirmed_sessions"] = len(confirmed)
        assignment["rejected_sessions"] = len(rejected)
        assignment["adjusted_sessions"] = len(
            self._clean_string_list(assignment.get("adjusted_session_ids")),
        )
        false_positive_denominator = len(confirmed) + len(rejected)
        assignment["false_positive_rate"] = (
            round(len(rejected) / false_positive_denominator, 3)
            if false_positive_denominator
            else 0.0
        )
        assignment["false_negative_rate"] = self._nonnegative_float_value(
            assignment.get("false_negative_rate"),
            default=0.0,
        )
        assignment["median_power_error"] = self._round_optional_number(
            assignment.get("median_power_error"),
        )
        assignment["energy_estimate_error"] = self._round_optional_number(
            assignment.get("energy_estimate_error"),
        )
        assignment["updated_at"] = now
        self._rebuild_assignment_model(circuit_id, assignment)
        coordinator.store_persistence.mark_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now_dt)
        return dict(assignment)

    def _update_assignment_duration_bounds(
        self,
        circuit_id: str,
        assignment: dict[str, Any],
    ) -> None:
        confirmed = set(
            self._clean_string_list(assignment.get("confirmed_session_ids"))
        )
        confirmed_aliases: dict[str, str] = {}
        durations: list[float] = []
        for session in self._coordinator.store_data.nilm_session_history_by_circuit.get(
            circuit_id,
            (),
        ):
            if not isinstance(session, Mapping):
                continue
            preserved_close = session.get("_duration_bound_close")
            preserved_close = (
                preserved_close if isinstance(preserved_close, Mapping) else None
            )
            session_ids = {str(session.get("session_id") or "").strip()}
            if preserved_close is not None:
                preserved_session_id = str(
                    preserved_close.get("session_id") or ""
                ).strip()
                session_ids.add(preserved_session_id)
                session_id = str(session.get("session_id") or "").strip()
                if session_id in confirmed and preserved_session_id:
                    confirmed_aliases[session_id] = preserved_session_id
            if confirmed.isdisjoint(session_ids):
                continue
            if preserved_close is not None:
                preserved_duration = self._nonnegative_float_value(
                    preserved_close.get("duration_seconds"),
                    default=0.0,
                )
                if preserved_duration > 0.0:
                    durations.append(preserved_duration)
                    continue
            start = self._datetime_or_none(session.get("start"))
            end = self._datetime_or_none(session.get("end"))
            if start is not None and end is not None and end > start:
                durations.append((end - start).total_seconds())
        if not durations:
            for key in (
                "typical_duration_seconds",
                "min_duration_seconds",
                "max_duration_seconds",
            ):
                assignment.pop(key, None)
        else:
            typical = float(median(durations))
            # ponytail: half/double the median until labelled volume supports
            # percentiles.
            assignment["typical_duration_seconds"] = round(typical, 3)
            minimum = max(30.0, min(min(durations), typical * 0.5))
            assignment["min_duration_seconds"] = round(minimum, 3)
            assignment["max_duration_seconds"] = round(
                max(minimum, max(durations), typical * 2.0),
                3,
            )
        if self._sample_processor is not None:
            self._sample_processor.refresh_session_history(
                circuit_id,
                self._coordinator.store_data,
            )
        if confirmed_aliases:
            assignment["confirmed_session_ids"] = self._clean_string_list(
                confirmed_aliases.get(session_id, session_id)
                for session_id in assignment.get("confirmed_session_ids", ())
            )

    def apply_alert_feedback(
        self,
        alert: AlertEvidence,
        action: str,
        now: datetime,
    ) -> None:
        """Apply alert feedback to a NILM assignment."""
        if alert.features.get("source") != "nilm":
            return
        assignment_id = str(alert.features.get("assignment_id") or "").strip()
        if not assignment_id:
            return
        try:
            assignment = self.assignment_for_id(alert.circuit_id, assignment_id)
        except ValueError:
            return
        current_confidence = self._nonnegative_float_value(
            assignment.get("confidence"),
            default=0.0,
        )
        session_id = ""
        if _alert_feature(alert) == "nilm_appliance_finished":
            notification_key = str(alert.features.get("notification_key") or "").strip()
            notification_key_parts = notification_key.split(":", 1)
            if len(notification_key_parts) == 2:
                session_id = notification_key_parts[1].strip()
        confirmed = self._clean_string_list(assignment.get("confirmed_session_ids"))
        rejected = self._clean_string_list(assignment.get("rejected_session_ids"))
        if action == "correct":
            assignment["confidence"] = min(1.0, round(current_confidence + 0.05, 3))
            assignment["last_validation"] = "correct"
            if session_id:
                self._append_unique(confirmed, session_id)
                rejected = [value for value in rejected if value != session_id]
        elif action == "wrong_appliance":
            assignment["confidence"] = max(0.0, round(current_confidence - 0.15, 3))
            assignment["last_validation"] = "wrong_appliance"
            assignment["lifecycle_state"] = "needs_validation"
            if session_id:
                self._append_unique(rejected, session_id)
                confirmed = [value for value in confirmed if value != session_id]
        else:
            return
        assignment["confirmed_session_ids"] = confirmed
        assignment["rejected_session_ids"] = rejected
        self._update_assignment_duration_bounds(alert.circuit_id, assignment)
        self._rebuild_assignment_model(alert.circuit_id, assignment)
        assignment["confirmed_sessions"] = len(confirmed)
        assignment["rejected_sessions"] = len(rejected)
        assignment["adjusted_sessions"] = len(
            self._clean_string_list(assignment.get("adjusted_session_ids")),
        )
        false_positive_denominator = len(confirmed) + len(rejected)
        assignment["false_positive_rate"] = (
            round(len(rejected) / false_positive_denominator, 3)
            if false_positive_denominator
            else 0.0
        )
        assignment["updated_at"] = now.isoformat()

    def assignment_for_session(
        self,
        circuit_id: str,
        session_id: str,
        *,
        assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the assignment that owns one NILM session."""
        session_id_text = str(session_id or "").strip()
        if not session_id_text:
            raise ValueError("Missing session_id.")
        assignment_id_text = str(assignment_id or "").strip()
        if assignment_id_text:
            assignment = self.assignment_for_id(circuit_id, assignment_id_text)
            self._append_unique(
                assignment.setdefault("session_ids", []),
                session_id_text,
            )
            return assignment
        assignments = (
            self._coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id,
                [],
            )
        )
        for assignment in assignments:
            if session_id_text in assignment.get("session_ids", ()):
                return assignment
        raise ValueError(
            f"Assign NILM session '{session_id_text}' to an appliance before "
            "validating it."
        )

    async def async_ignore_nilm_signature(
        self,
        circuit_id: str,
        signature_id: str,
    ) -> None:
        """Persist an ignored NILM signature marker."""
        coordinator = self._coordinator
        coordinator.ignored_nilm_signatures.add((circuit_id, signature_id))
        signatures = coordinator.store_data.nilm_signatures.setdefault(circuit_id, [])
        for signature in signatures:
            if signature.get("signature_id") == signature_id:
                signature["ignored"] = True
                assignment = self.upsert_assignment(
                    circuit_id,
                    label=self._signature_assignment_label(signature, signature_id),
                    signature_fingerprint=self._signature_fingerprint_value(
                        signature,
                        signature_id,
                    ),
                    lifecycle_state="ignored",
                    confidence=signature.get("confidence", 1.0),
                )
                signature["assignment_id"] = assignment["assignment_id"]
                await self._async_save_nilm_review_change(circuit_id)
                return
        signature = {"signature_id": signature_id, "ignored": True}
        assignment = self.upsert_assignment(
            circuit_id,
            label=signature_id,
            signature_fingerprint=signature_id,
            lifecycle_state="ignored",
        )
        signature["assignment_id"] = assignment["assignment_id"]
        signatures.append(signature)
        await self._async_save_nilm_review_change(circuit_id)

    async def async_restore_nilm_item(
        self,
        circuit_id: str,
        *,
        assignment_id: str | None = None,
        signature_id: str | None = None,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        """Restore one hidden item or revert one direct-meter conversion."""
        assignment_id_text = str(assignment_id or "").strip()
        signature_id_text = str(signature_id or "").strip()
        if bool(assignment_id_text) == bool(signature_id_text):
            raise ValueError("Pass exactly one of assignment_id or signature_id.")

        coordinator = self._coordinator
        requested_entry_id = str(entry_id or "").strip()
        current_entry_id = str(getattr(coordinator, "entry_id", "") or "").strip()
        if (
            requested_entry_id
            and current_entry_id
            and requested_entry_id != current_entry_id
        ):
            raise ValueError(
                f"entry_id '{requested_entry_id}' does not own circuit '{circuit_id}'."
            )
        registry = getattr(coordinator, "circuit_registry", None)
        config_for_circuit = getattr(registry, "config_for_circuit", None)
        if callable(config_for_circuit):
            if config_for_circuit(circuit_id) is None:
                raise ValueError(f"Unknown circuit_id '{circuit_id}'.")
        else:
            store_data = getattr(coordinator, "store_data", None)
            known_circuits = {
                *getattr(store_data, "nilm_signatures", {}).keys(),
                *getattr(
                    store_data,
                    "nilm_appliance_assignments_by_circuit",
                    {},
                ).keys(),
            }
            if circuit_id not in known_circuits:
                raise ValueError(f"Unknown circuit_id '{circuit_id}'.")
        signatures = coordinator.store_data.nilm_signatures.get(circuit_id, [])
        if signature_id_text:
            signature = next(
                (
                    item
                    for item in signatures
                    if item.get("signature_id") == signature_id_text
                ),
                None,
            )
            if signature is None:
                raise ValueError(
                    f"Unknown signature_id '{signature_id_text}' for circuit_id "
                    f"'{circuit_id}'."
                )
            fingerprint = self._signature_fingerprint_value(
                signature, signature_id_text
            )
            owner_id = str(signature.get("assignment_id") or "").strip()
            owner = (
                self.assignment_for_id(circuit_id, owner_id)
                if owner_id
                else self.assignment_for_signature(circuit_id, fingerprint)
            )
            for key in (
                "ignored",
                "merged_into",
                "merged_into_fingerprint",
                "assignment_id",
                "user_label",
            ):
                signature.pop(key, None)
            signature["review_state"] = "new"
            ignored = getattr(coordinator, "ignored_nilm_signatures", None)
            if isinstance(ignored, set):
                ignored.discard((circuit_id, signature_id_text))
            if owner is not None:
                owner["signature_fingerprints"] = [
                    value
                    for value in self._clean_string_list(
                        owner.get("signature_fingerprints")
                    )
                    if value != fingerprint
                ]
                owner_has_history = any(
                    self._clean_string_list(owner.get(key))
                    for key in ("session_ids", "label_interval_ids")
                )
                if not owner["signature_fingerprints"] and not owner_has_history:
                    assignments_by_circuit = (
                        coordinator.store_data.nilm_appliance_assignments_by_circuit
                    )
                    assignments = assignments_by_circuit.get(circuit_id, [])
                    assignments[:] = [item for item in assignments if item is not owner]
                else:
                    owner["lifecycle_state"] = "assigned"
                    owner["updated_at"] = coordinator.current_time().isoformat()
                    self._rebuild_assignment_model(circuit_id, owner)
            await self._async_save_nilm_review_change(circuit_id)
            return dict(signature)

        assignment = self.assignment_for_id(circuit_id, assignment_id_text)
        state = str(assignment.get("lifecycle_state") or "").strip().lower()
        direct_conversion = assignment.get("conversion_state") == "direct_meter"
        if state not in {"ignored", "retired"} and not direct_conversion:
            raise ValueError(f"Assignment '{assignment_id_text}' is not restorable.")
        if direct_conversion:
            for key in (
                "conversion_state",
                "direct_circuit_id",
                "converted_at",
                "pre_conversion_lifecycle_state",
                "keep_assignment_for_masking",
                "keep_published_estimate",
            ):
                assignment.pop(key, None)
        assignment["lifecycle_state"] = "assigned"
        assignment["publish_entities"] = False
        assignment["created_device"] = False
        assignment["updated_at"] = coordinator.current_time().isoformat()
        fingerprints = set(
            self._clean_string_list(assignment.get("signature_fingerprints"))
        )
        ignored = getattr(coordinator, "ignored_nilm_signatures", None)
        for signature in signatures:
            signature_fingerprint = self._signature_fingerprint_value(
                signature,
                str(signature.get("signature_id") or ""),
            )
            if (
                signature.get("assignment_id") != assignment_id_text
                and signature_fingerprint not in fingerprints
            ):
                continue
            signature["assignment_id"] = assignment_id_text
            signature["review_state"] = "assigned"
            signature.pop("ignored", None)
            if isinstance(ignored, set):
                ignored.discard((circuit_id, str(signature.get("signature_id") or "")))
        self._rebuild_assignment_model(circuit_id, assignment)
        await self._async_save_nilm_review_change(circuit_id)
        return dict(assignment)

    async def async_merge_nilm_signatures(
        self,
        circuit_id: str,
        source_signature_id: str,
        target_signature_id: str,
    ) -> None:
        """Persist that one NILM signature should be treated as another."""
        target = self.signature_for_review(circuit_id, target_signature_id)
        source = self.signature_for_review(circuit_id, source_signature_id)
        source["review_state"] = "merged"
        source["merged_into"] = target_signature_id
        if target.get("feedback_fingerprint"):
            source["merged_into_fingerprint"] = target["feedback_fingerprint"]
        target_fingerprint = self._signature_fingerprint_value(
            target,
            target_signature_id,
        )
        source_fingerprint = self._signature_fingerprint_value(
            source,
            source_signature_id,
        )
        assignment = self.assignment_for_signature(
            circuit_id,
            target_fingerprint,
        ) or self.assignment_for_signature(circuit_id, source_fingerprint)
        if assignment is not None:
            self._append_unique(
                assignment.setdefault("signature_fingerprints", []),
                source_fingerprint,
            )
            assignment["updated_at"] = self._coordinator.current_time().isoformat()
            source["assignment_id"] = assignment["assignment_id"]
            target["assignment_id"] = assignment["assignment_id"]
            self.remove_signature_from_other_assignments(
                circuit_id,
                source_fingerprint,
                assignment["assignment_id"],
            )
        await self._async_save_nilm_review_change(circuit_id)

    def signature_for_review(
        self,
        circuit_id: str,
        signature_id: str,
    ) -> dict[str, Any]:
        """Return a stored NILM signature, creating a review placeholder if needed."""
        signatures = self._coordinator.store_data.nilm_signatures.setdefault(
            circuit_id,
            [],
        )
        for signature in signatures:
            if signature.get("signature_id") == signature_id:
                return signature
        signature = {"signature_id": signature_id, "review_state": "new"}
        signatures.append(signature)
        return signature

    def assignment_for_signature(
        self,
        circuit_id: str,
        signature_fingerprint: str,
    ) -> dict[str, Any] | None:
        """Return the NILM assignment that owns one signature fingerprint."""
        assignments = (
            self._coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id,
                [],
            )
        )
        return next(
            (
                assignment
                for assignment in assignments
                if signature_fingerprint in assignment.get("signature_fingerprints", ())
            ),
            None,
        )

    def remove_signature_from_other_assignments(
        self,
        circuit_id: str,
        signature_fingerprint: str,
        assignment_id: str,
    ) -> None:
        """Ensure one signature fingerprint is attached to only one assignment."""
        if not signature_fingerprint:
            return
        assignments = (
            self._coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id,
                (),
            )
        )
        for assignment in assignments:
            if assignment.get("assignment_id") == assignment_id:
                continue
            fingerprints = assignment.get("signature_fingerprints")
            if not isinstance(fingerprints, list):
                continue
            assignment["signature_fingerprints"] = [
                value for value in fingerprints if value != signature_fingerprint
            ]

    async def _async_save_nilm_review_change(self, circuit_id: str) -> None:
        coordinator = self._coordinator
        coordinator.store_persistence.mark_dirty()
        self.refresh_state(circuit_id)
        refresh_ux = getattr(coordinator, "refresh_ux_state_for_circuit", None)
        if callable(refresh_ux):
            refresh_ux(circuit_id, coordinator.current_time())
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(
            coordinator.current_time()
        )

    async def async_rename_nilm_appliance(
        self,
        circuit_id: str,
        assignment_id: str,
        *,
        label: str,
    ) -> dict[str, Any]:
        """Rename a NILM appliance assignment without changing its stable ID."""
        label_text = str(label or "").strip()
        if not label_text:
            raise ValueError("Missing label.")
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        assignment["display_name"] = label_text
        self._rebuild_assignment_model(circuit_id, assignment)
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        await self.async_save_assignment_change()
        return dict(assignment)

    async def async_change_nilm_appliance_profile(
        self,
        circuit_id: str,
        assignment_id: str,
        *,
        appliance_profile: str,
    ) -> dict[str, Any]:
        """Change the appliance profile hint for a NILM assignment."""
        profile_text = str(appliance_profile or "").strip()
        if not profile_text:
            raise ValueError("Missing appliance_profile.")
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        assignment["appliance_profile"] = profile_text
        self._rebuild_assignment_model(circuit_id, assignment)
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        await self.async_save_assignment_change()
        return dict(assignment)

    async def async_set_nilm_helper_link(
        self,
        circuit_id: str,
        assignment_id: str,
        *,
        helper_circuit_id: str,
        relationship: str,
    ) -> dict[str, Any]:
        """Confirm one direct-circuit relationship for a NILM assignment."""
        assignment, helper_id, helper_config = self._helper_link_resources(
            circuit_id, assignment_id, helper_circuit_id
        )
        if relationship not in {"corroborates", "direct_component"}:
            raise ValueError(f"Unsupported helper relationship '{relationship}'.")
        direct_eligible = supports_direct_appliance_analysis(helper_config)
        if relationship == "direct_component" and not direct_eligible:
            raise ValueError(
                f"Helper circuit '{helper_id}' is not direct-appliance eligible."
            )
        links = [
            _normalized_helper_link(link)
            for link in assignment.get("helper_links", ())
            if isinstance(link, Mapping) and link.get("helper_circuit_id") != helper_id
        ]
        if len(links) >= 4:
            raise ValueError(
                "A NILM assignment can have at most four confirmed helper links."
            )
        if relationship == "direct_component" and any(
            link.get("relationship") == "direct_component" for link in links
        ):
            raise ValueError(
                "A NILM assignment can have only one direct_component link."
            )
        fingerprints = set(
            self._clean_string_list(assignment.get("signature_fingerprints"))
        )
        candidates = [
            (str(signature.get("feedback_fingerprint") or ""), candidate)
            for signature in self._coordinator.store_data.nilm_signatures.get(
                circuit_id, ()
            )
            if isinstance(signature, Mapping)
            and str(signature.get("feedback_fingerprint") or "") in fingerprints
            for candidate in signature.get("helper_candidates", ())
            if isinstance(candidate, Mapping)
            and candidate.get("helper_circuit_id") == helper_id
        ]
        selected = max(
            candidates,
            key=lambda item: (*_helper_candidate_sort_key(item[1]), item[0]),
            default=None,
        )
        candidate = selected[1] if selected else None
        link = _normalized_helper_link(candidate or {})
        link.update(
            helper_circuit_id=helper_id, relationship=relationship, status="confirmed"
        )
        link["confirmed_matched_on_count"] = int(link.get("matched_on_count") or 0)
        link["confirmed_matched_off_count"] = int(link.get("matched_off_count") or 0)
        links.append(link)
        links.sort(
            key=lambda item: (
                _nonnegative_float_value(item.get("confidence"), default=0.0),
                _helper_link_recency(item),
            ),
            reverse=True,
        )
        assignment["helper_links"] = links[:4]
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        await self.async_save_assignment_change()
        return dict(assignment)

    async def async_remove_nilm_helper_link(
        self,
        circuit_id: str,
        assignment_id: str,
        *,
        helper_circuit_id: str,
    ) -> dict[str, Any]:
        """Remove one confirmed helper relationship."""
        assignment, helper_id, _ = self._helper_link_resources(
            circuit_id, assignment_id, helper_circuit_id
        )
        assignment["helper_links"] = [
            dict(link)
            for link in assignment.get("helper_links", ())
            if isinstance(link, Mapping) and link.get("helper_circuit_id") != helper_id
        ]
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        await self.async_save_assignment_change()
        return dict(assignment)

    async def async_set_nilm_reference_link(
        self,
        circuit_id: str,
        assignment_id: str,
        *,
        state_entity_id: str | None = None,
        power_entity_id: str | None = None,
        threshold_w: Any = 0.0,
    ) -> dict[str, Any]:
        """Link authoritative state and optional measured-power evidence."""
        state_id = str(state_entity_id or "").strip()
        power_id = str(power_entity_id or "").strip()
        if not state_id and not power_id:
            raise ValueError("Select a reference state or power entity.")
        if isinstance(threshold_w, bool):
            raise ValueError("reference_threshold_w must be a non-negative number.")
        try:
            threshold = float(threshold_w)
        except (TypeError, ValueError) as err:
            raise ValueError(
                "reference_threshold_w must be a non-negative number."
            ) from err
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError("reference_threshold_w must be a non-negative number.")
        self._validate_reference_entities(state_id, power_id)

        assignment = self.assignment_for_id(circuit_id, assignment_id)
        if state_id:
            assignment["reference_state_entity_id"] = state_id
        else:
            assignment.pop("reference_state_entity_id", None)
        if power_id:
            assignment["reference_power_entity_id"] = power_id
        else:
            assignment.pop("reference_power_entity_id", None)
        assignment["reference_threshold_w"] = threshold
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        await self.async_save_assignment_change()
        return dict(assignment)

    def _validate_reference_entities(
        self,
        state_entity_id: str,
        power_entity_id: str,
    ) -> None:
        get_state = getattr(
            getattr(getattr(self._coordinator, "hass", None), "states", None),
            "get",
            None,
        )
        if not callable(get_state):
            return
        if state_entity_id:
            if state_entity_id.partition(".")[0] not in {
                "switch",
                "binary_sensor",
                "input_boolean",
            } or get_state(state_entity_id) is None:
                raise ValueError(
                    "Reference state entity must be a loaded on/off entity."
                )
        if not power_entity_id:
            return
        state = get_state(power_entity_id)
        attributes = getattr(state, "attributes", {})
        if not isinstance(attributes, Mapping):
            attributes = {}
        unit = str(attributes.get("unit_of_measurement") or "").strip()
        device_class = str(attributes.get("device_class") or "").strip()
        if (
            state is None
            or power_entity_id.partition(".")[0] != "sensor"
            or unit not in {"W", "kW", "mW", "MW"}
            or sensor_metadata_role_conflict(device_class=device_class, unit=unit)
            or sensor_role_from_metadata(device_class=device_class, unit=unit)
            is not SensorRole.REAL_POWER
        ):
            raise ValueError(
                "Reference power entity must unambiguously report real power in "
                "W, kW, mW, or MW."
            )

    async def async_remove_nilm_reference_link(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Remove reference entities without deleting imported intervals."""
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        for key in (
            "reference_state_entity_id",
            "reference_power_entity_id",
            "reference_threshold_w",
        ):
            assignment.pop(key, None)
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        await self.async_save_assignment_change()
        return dict(assignment)

    def _helper_link_resources(
        self,
        circuit_id: str,
        assignment_id: str,
        helper_circuit_id: str,
    ) -> tuple[dict[str, Any], str, Any]:
        registry = self._coordinator.circuit_registry
        if registry.config_for_circuit(circuit_id) is None:
            raise ValueError(f"Missing NILM source circuit '{circuit_id}'.")
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        helper_id = str(helper_circuit_id or "").strip()
        if helper_id == circuit_id:
            raise ValueError("A NILM source cannot link to itself.")
        helper_config = registry.config_for_circuit(helper_id)
        if helper_config is None:
            raise ValueError(f"Missing helper circuit '{helper_id}'.")
        return assignment, helper_id, helper_config

    async def async_convert_nilm_assignment_to_direct_meter(
        self,
        circuit_id: str,
        assignment_id: str,
        *,
        direct_circuit_id: str,
        keep_assignment_for_masking: bool = True,
        keep_published_estimate: bool = False,
    ) -> dict[str, Any]:
        """Link a NILM identity to a direct circuit without losing history."""
        direct_id = str(direct_circuit_id or "").strip()
        if not direct_id:
            raise ValueError("Missing direct_circuit_id.")
        if keep_published_estimate and not keep_assignment_for_masking:
            raise ValueError(
                "A published NILM estimate requires keeping its assignment."
            )
        configs = tuple(getattr(self._coordinator, "circuit_configs", ()) or ())
        if configs:
            direct_config = next(
                (
                    config
                    for config in configs
                    if str(getattr(config, "circuit_id", "")) == direct_id
                ),
                None,
            )
            if (
                direct_config is None
                or getattr(direct_config, "mode", None)
                in {CircuitMode.MAINS_NILM, CircuitMode.MIXED}
                or getattr(direct_config, "appliance_profile", None)
                in {
                    ApplianceProfile.MAINS_NILM,
                    ApplianceProfile.MIXED,
                    ApplianceProfile.SOLAR_INVERTER,
                }
            ):
                raise ValueError(
                    f"Direct circuit '{direct_id}' is not a configured "
                    "direct-meter circuit."
                )
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        previous = dict(assignment)
        assignment["appliance_key"] = (
            f"nilm:{str(assignment.get('assignment_id') or '').strip()}"
        )
        assignment["conversion_state"] = "direct_meter"
        assignment["direct_circuit_id"] = direct_id
        assignment["converted_at"] = self._coordinator.current_time().isoformat()
        assignment.setdefault(
            "pre_conversion_lifecycle_state",
            assignment.get("lifecycle_state"),
        )
        assignment["keep_assignment_for_masking"] = bool(keep_assignment_for_masking)
        assignment["keep_published_estimate"] = bool(keep_published_estimate)
        assignment["publish_entities"] = bool(keep_published_estimate)
        assignment["created_device"] = bool(keep_published_estimate)
        assignment["lifecycle_state"] = (
            "published"
            if keep_published_estimate
            else "converted"
            if keep_assignment_for_masking
            else "retired"
        )
        await self.async_save_assignment_change()
        if (
            not keep_published_estimate
            and await self._async_wait_for_assignment_entities(
                str(assignment.get("assignment_id") or ""),
                False,
            )
            is True
        ):
            assignment.clear()
            assignment.update(previous)
            await self.async_save_assignment_change()
            raise ValueError(
                "Converting the NILM assignment did not remove its estimated "
                "Home Assistant entities."
            )
        return dict(assignment)

    async def async_merge_nilm_assignments(
        self,
        circuit_id: str,
        source_assignment_id: str,
        target_assignment_id: str,
    ) -> dict[str, Any]:
        """Merge one NILM appliance assignment into another."""
        source_id = str(source_assignment_id or "").strip()
        target_id = str(target_assignment_id or "").strip()
        if not source_id or not target_id:
            raise ValueError("Missing source_assignment_id or target_assignment_id.")
        if source_id == target_id:
            raise ValueError(
                "source_assignment_id and target_assignment_id must be different."
            )
        source = self.assignment_for_id(circuit_id, source_id)
        target = self.assignment_for_id(circuit_id, target_id)
        target_confirmed = self._clean_string_list(target.get("confirmed_session_ids"))
        target_rejected = self._clean_string_list(target.get("rejected_session_ids"))
        for key in (
            "signature_fingerprints",
            "session_ids",
            "label_interval_ids",
            "confirmed_session_ids",
            "rejected_session_ids",
        ):
            values = target.setdefault(key, [])
            for value in self._clean_string_list(source.get(key)):
                self._append_unique(values, value)
        if target_id == configured_primary_assignment_id(circuit_id):
            target["signature_fingerprints"] = [
                value
                for value in self._clean_string_list(
                    target.get("signature_fingerprints")
                )
                if nilm_signature_is_assignable(value)
            ]
        confirmed = self._clean_string_list(target.get("confirmed_session_ids"))
        rejected = self._clean_string_list(target.get("rejected_session_ids"))
        target_confirmed_set = set(target_confirmed)
        target_rejected_set = set(target_rejected)
        confirmed = [
            session_id
            for session_id in confirmed
            if session_id not in target_rejected_set
            or session_id in target_confirmed_set
        ]
        rejected = [
            session_id
            for session_id in rejected
            if session_id not in target_confirmed_set
        ]
        confirmed_set = set(confirmed)
        rejected = [
            session_id for session_id in rejected if session_id not in confirmed_set
        ]
        target["confirmed_session_ids"] = confirmed
        target["rejected_session_ids"] = rejected
        target["confirmed_sessions"] = len(confirmed)
        target["rejected_sessions"] = len(rejected)
        validation_total = len(confirmed) + len(rejected)
        target["false_positive_rate"] = (
            round(len(rejected) / validation_total, 3) if validation_total else 0.0
        )
        target["confidence"] = max(
            self._nonnegative_float_value(target.get("confidence"), default=0.0),
            self._nonnegative_float_value(source.get("confidence"), default=0.0),
        )
        target["publish_entities"] = bool(
            target.get("publish_entities") or source.get("publish_entities")
        )
        target["created_device"] = bool(
            target.get("created_device") or source.get("created_device")
        )
        if source.get("lifecycle_state") == "published":
            target["lifecycle_state"] = "published"
        target["updated_at"] = self._coordinator.current_time().isoformat()

        assignments = (
            self._coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id,
                [],
            )
        )
        self._coordinator.store_data.nilm_appliance_assignments_by_circuit[
            circuit_id
        ] = [
            assignment
            for assignment in assignments
            if assignment.get("assignment_id") != source_id
        ]
        for signature in self._coordinator.store_data.nilm_signatures.get(
            circuit_id,
            [],
        ):
            if signature.get("assignment_id") == source_id:
                signature["assignment_id"] = target_id
        for (
            interval
        ) in self._coordinator.store_data.nilm_label_intervals_by_circuit.get(
            circuit_id,
            [],
        ):
            if interval.get("assignment_id") == source_id:
                interval["assignment_id"] = target_id
        for session in self._coordinator.store_data.nilm_session_history_by_circuit.get(
            circuit_id, []
        ):
            if session.get("assignment_id") == source_id:
                session["assignment_id"] = target_id
        self._update_assignment_duration_bounds(circuit_id, target)
        self._rebuild_assignment_model(circuit_id, target)
        await self.async_save_assignment_change()
        return dict(target)

    async def async_publish_nilm_appliance_assignment(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Publish estimated HA entities for a NILM assignment."""
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        blocked_reason = nilm_assignment_publication_reason(assignment)
        if blocked_reason is not None:
            raise ValueError(blocked_reason)
        previous = dict(assignment)
        assignment["publish_entities"] = True
        assignment["created_device"] = True
        assignment["lifecycle_state"] = "published"
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        await self.async_save_assignment_change()
        if await self._async_wait_for_assignment_entities(assignment_id, True) is False:
            assignment.clear()
            assignment.update(previous)
            await self.async_save_assignment_change()
            raise ValueError(
                f"Publishing assignment '{assignment_id}' did not create "
                "Home Assistant entities."
            )
        return dict(assignment)

    async def async_unpublish_nilm_appliance_assignment(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Stop publishing estimated HA entities for a NILM assignment."""
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        previous = dict(assignment)
        assignment["publish_entities"] = False
        assignment["created_device"] = False
        if assignment.get("lifecycle_state") == "published":
            assignment["lifecycle_state"] = "validated"
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        await self.async_save_assignment_change()
        if await self._async_wait_for_assignment_entities(assignment_id, False) is True:
            assignment.clear()
            assignment.update(previous)
            await self.async_save_assignment_change()
            raise ValueError(
                f"Unpublishing assignment '{assignment_id}' did not remove "
                "Home Assistant entities."
            )
        return dict(assignment)

    async def async_retire_nilm_appliance_assignment(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Retire a NILM assignment and stop publishing entities."""
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        assignment["publish_entities"] = False
        assignment["created_device"] = False
        assignment["lifecycle_state"] = "retired"
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        await self.async_save_assignment_change()
        return dict(assignment)

    def assignment_for_id(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Return one stored NILM assignment by stable ID."""
        assignment_id_text = str(assignment_id or "").strip()
        if not assignment_id_text:
            raise ValueError("Missing assignment_id.")
        assignments = (
            self._coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id,
                [],
            )
        )
        for assignment in assignments:
            if assignment.get("assignment_id") == assignment_id_text:
                return assignment
        raise ValueError(
            f"Unknown assignment_id '{assignment_id_text}' for circuit_id "
            f"'{circuit_id}'."
        )

    async def async_save_assignment_change(self) -> None:
        """Persist assignment changes and reload published NILM entities."""
        self._coordinator.store_persistence.mark_dirty()
        self._coordinator.async_set_updated_data(self._coordinator.state)
        await self._coordinator.store_persistence.async_save_if_dirty(
            self._coordinator.current_time()
        )
        reload_entry = getattr(
            getattr(self._coordinator, "config_entry_controller", None),
            "async_reload",
            None,
        )
        if callable(reload_entry):
            await reload_entry()

    def _assignment_entities_present(
        self,
        assignment_id: str,
        *,
        expected: bool,
    ) -> bool | None:
        hass = getattr(self._coordinator, "hass", None)
        entry_id = str(getattr(self._coordinator, "entry_id", "") or "")
        try:
            from homeassistant.helpers import device_registry as dr
            from homeassistant.helpers import entity_registry as er

            entity_registry = er.async_get(hass)
            device_registry = dr.async_get(hass)
        except (AttributeError, ImportError, KeyError, TypeError):
            entity_registry = None
            device_registry = None
        if entity_registry is not None and device_registry is not None and entry_id:
            unique_id_prefix = f"{entry_id}_nilm_{assignment_id}_"
            registered_unique_ids = {
                str(getattr(entry, "unique_id", ""))
                for entry in er.async_entries_for_config_entry(
                    entity_registry,
                    entry_id,
                )
                if getattr(entry, "platform", None) == DOMAIN
                and str(getattr(entry, "unique_id", "")).startswith(unique_id_prefix)
            }
            if expected:
                from ..sensor import NILM_VIRTUAL_SENSOR_DESCRIPTIONS

                expected_unique_ids = {
                    f"{unique_id_prefix}{description.key}"
                    for description in NILM_VIRTUAL_SENSOR_DESCRIPTIONS
                }
                expected_unique_ids.add(f"{unique_id_prefix}estimated_running")
                entity_present = expected_unique_ids <= registered_unique_ids
            else:
                entity_present = bool(registered_unique_ids)
            device_present = (
                device_registry.async_get_device(
                    identifiers={(DOMAIN, f"{entry_id}_nilm_{assignment_id}")},
                )
                is not None
            )
            return (
                entity_present and device_present
                if expected
                else entity_present or device_present
            )

        async_all = getattr(getattr(hass, "states", None), "async_all", None)
        if callable(async_all):
            return any(
                str(getattr(state, "attributes", {}).get("assignment_id") or "")
                == assignment_id
                for state in async_all()
            )
        return None

    async def _async_wait_for_assignment_entities(
        self,
        assignment_id: str,
        expected: bool,
    ) -> bool | None:
        present = self._assignment_entities_present(
            assignment_id,
            expected=expected,
        )
        for _ in range(20):
            if present is None or present is expected:
                return present
            await asyncio.sleep(0.05)
            present = self._assignment_entities_present(
                assignment_id,
                expected=expected,
            )
        return present


def _alert_feature(alert: AlertEvidence) -> str:
    if alert.feature:
        return alert.feature
    if alert.event_type is not None:
        return alert.event_type.value
    return "alert"


def _demo_seed_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _demo_nilm_edges(value: Any) -> list[NilmEdge]:
    edges: list[NilmEdge] = []
    for raw_edge in _demo_seed_list(value):
        timestamp = _datetime_or_none(raw_edge.pop("timestamp", None))
        if timestamp is None:
            continue
        try:
            edges.append(NilmEdge(timestamp=timestamp, **raw_edge))
        except TypeError:
            continue
    return edges


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _helper_link_recency(link: Mapping[str, Any]) -> float:
    observed = _datetime_or_none(link.get("last_observed"))
    if observed is None:
        return float("-inf")
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.timestamp()


def _helper_candidate_sort_key(
    link: Mapping[str, Any],
) -> tuple[float, float, int, int]:
    normalized = _normalized_helper_link(link)
    return (
        _helper_link_recency(normalized),
        normalized["confidence"],
        normalized["matched_on_count"],
        normalized["matched_off_count"],
    )


def _normalized_helper_link(link: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(link)
    for key in (
        "matched_on_count",
        "matched_off_count",
        "unmatched_source_count",
        "unmatched_helper_count",
        "source_event_count",
        "helper_event_count",
        "confirmed_matched_on_count",
        "confirmed_matched_off_count",
    ):
        count = _nonnegative_float_value(normalized.get(key), default=0.0)
        normalized[key] = int(count) if math.isfinite(count) else 0
    confidence = _nonnegative_float_value(normalized.get("confidence"), default=0.0)
    normalized["confidence"] = (
        min(confidence, 1.0) if math.isfinite(confidence) else 0.0
    )
    for key in (
        "start_lag_seconds",
        "stop_lag_seconds",
        "start_lag_mad_seconds",
        "stop_lag_mad_seconds",
    ):
        value = _float_or_none(normalized.get(key))
        normalized[key] = value if value is not None and math.isfinite(value) else None
    observed = _datetime_or_none(normalized.get("last_observed"))
    normalized["last_observed"] = observed.isoformat() if observed else None
    return normalized


def _round_optional_number(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    return round(parsed, 3)


def _nilm_label_interval_datetime(value: Any, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as err:
        raise ValueError(f"Invalid NILM label interval {field_name}.") from err
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _nilm_label_interval_id(
    circuit_id: str,
    start: str,
    end: str,
    label: str,
) -> str:
    seed = f"{circuit_id}|{start}|{end}|{label}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"label-{digest}"


def _nilm_signature_fingerprint_value(
    signature: Mapping[str, Any],
    fallback: str,
) -> str:
    return str(
        signature.get("feedback_fingerprint")
        or signature.get("signature_fingerprint")
        or signature.get("signature_id")
        or fallback
    ).strip()


def _nilm_signature_assignment_label(
    signature: Mapping[str, Any],
    fallback: str,
) -> str:
    return (
        str(signature.get("user_label") or "").strip()
        or str(signature.get("display_name") or "").strip()
        or str(signature.get("likely_type") or "").strip()
        or fallback
    )


def _nilm_assignment_interval_matches(
    interval: Mapping[str, Any],
    assignment: Mapping[str, Any],
) -> bool:
    interval_id = str(interval.get("interval_id") or "").strip()
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    if "assignment_id" in interval:
        return bool(assignment_id) and (
            str(interval.get("assignment_id") or "").strip() == assignment_id
        )
    if interval_id and interval_id in _clean_string_list(
        assignment.get("label_interval_ids")
    ):
        return True
    interval_appliance = (
        str(interval.get("appliance_id") or interval.get("label") or "")
        .strip()
        .casefold()
    )
    if not interval_appliance:
        return False
    return interval_appliance in {
        str(assignment.get("appliance_id") or "").strip().casefold(),
        str(assignment.get("display_name") or "").strip().casefold(),
    }


def _nilm_overlap_seconds(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> float:
    first_start = _datetime_or_none(first.get("start"))
    first_end = _datetime_or_none(first.get("end"))
    second_start = _datetime_or_none(second.get("start"))
    second_end = _datetime_or_none(second.get("end"))
    if not all((first_start, first_end, second_start, second_end)):
        return 0.0
    overlap_start = max(first_start, second_start)
    overlap_end = min(first_end, second_end)
    if overlap_end <= overlap_start:
        return 0.0
    return (overlap_end - overlap_start).total_seconds()


def _nilm_validation_coverage_overlap_seconds(
    interval: Mapping[str, Any],
    session: Mapping[str, Any],
) -> float:
    validation_start = interval.get("validation_start")
    validation_end = interval.get("validation_end")
    if not validation_start or not validation_end:
        return 0.0
    return _nilm_overlap_seconds(
        {"start": validation_start, "end": validation_end},
        session,
    )


def _nilm_assignment_appliance_id(label: str) -> str:
    slug = "".join(
        character.lower() if character.isalnum() else "_"
        for character in str(label or "").strip()
    ).strip("_")
    return "_".join(part for part in slug.split("_") if part)[:64] or "nilm"


def _nilm_assignment_id(circuit_id: str, appliance_id: str) -> str:
    seed = f"{circuit_id}|{appliance_id}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"assignment-{digest}"


def _nilm_session_assignment_matches(
    session: Mapping[str, Any],
    *,
    assignment_id: str,
    session_ids: set[str],
) -> bool:
    owner = str(session.get("assignment_id") or "").strip()
    if owner:
        return owner == assignment_id
    return str(session.get("session_id") or "").strip() in session_ids


def _append_unique(values: Any, value: Any) -> None:
    text = str(value or "").strip()
    if not text or text in values:
        return
    values.append(text)


def _clean_string_list(values: Any) -> list[str]:
    if isinstance(values, (str, bytes)):
        return []
    try:
        iterator = iter(values)
    except TypeError:
        return []
    cleaned: list[str] = []
    for value in iterator:
        text = str(value or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _nonnegative_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default
