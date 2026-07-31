from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from statistics import median
from typing import Any

from ..const import CONF_ENABLE_EXPERIMENTAL_NILM, DOMAIN
from ..demo import demo_nilm_workspace_seed, is_demo_config
from ..models import AlertEvidence, ApplianceProfile, CircuitMode
from ..nilm import NilmEdge


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
        return enabled and (
            config.mode is CircuitMode.MAINS_NILM
            or config.appliance_profile is ApplianceProfile.MAINS_NILM
        )

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
        """Process one NILM mains sample and apply resulting state updates."""
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
                coordinator.store_data.nilm_unknown_loads_by_circuit[circuit_id] = (
                    dict(unknown_loads)
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
        for circuit_id, signatures in coordinator.store_data.nilm_signatures.items():
            for signature in signatures:
                if signature.get("ignored") is True:
                    coordinator.ignored_nilm_signatures.add(
                        (circuit_id, str(signature.get("signature_id", "")))
                    )
            self.refresh_state(circuit_id)

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
    ) -> dict[str, Any]:
        """Create or update a durable NILM appliance assignment."""
        label_text = str(label or "").strip()
        if not label_text:
            raise ValueError("Missing label.")
        appliance_id_text = (
            str(appliance_id or "").strip()
            or self._assignment_appliance_id(label_text)
        )
        assignments = (
            self._coordinator.store_data.nilm_appliance_assignments_by_circuit.setdefault(
                circuit_id,
                [],
            )
        )
        assignment_id_text = str(assignment_id or "").strip()
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
            }
            assignment["appliance_key"] = (
                f"nilm:{assignment['assignment_id']}"
            )
            assignments.append(assignment)
        else:
            assignments[:] = [item for item in assignments if item is not assignment]
            assignments.append(assignment)
            assignment["display_name"] = label_text
            if appliance_profile:
                assignment["appliance_profile"] = str(appliance_profile).strip()
            assignment["lifecycle_state"] = lifecycle_state
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
        del assignments[:-self._assignment_max_items]
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
        history = (
            self._coordinator.store_data.nilm_session_history_by_circuit.get(
                circuit_id,
                (),
            )
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
            key=lambda session: self._datetime_or_none(
                session.get("end") or session.get("start")
            )
            or datetime.min.replace(tzinfo=UTC),
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
        del intervals[:-self._label_interval_max_items]

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
        coordinator.store_persistence.mark_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now_dt)
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
        coordinator = self._coordinator
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
        signature["assignment_id"] = assignment["assignment_id"]
        signature["review_state"] = "assigned"
        signature["user_label"] = assignment["display_name"]
        signature.pop("ignored", None)
        coordinator.ignored_nilm_signatures.discard((circuit_id, signature_id))
        self.remove_signature_from_other_assignments(
            circuit_id,
            fingerprint,
            assignment["assignment_id"],
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
        assignments = (
            coordinator.store_data.nilm_appliance_assignments_by_circuit.get(
                circuit_id,
                [],
            )
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
                and str(session.get("session_id") or "").strip()
                == session_id_text
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
        interval_id_text = str(interval_id or "").strip()
        coordinator = self._coordinator
        intervals = coordinator.store_data.nilm_label_intervals_by_circuit.setdefault(
            circuit_id,
            [],
        )
        interval = next(
            (
                item
                for item in intervals
                if item.get("interval_id") == interval_id_text
            ),
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
        interval["assignment_id"] = assignment["assignment_id"]
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
                    interval_power = self._float_or_none(
                        interval.get("median_power_w")
                    )
                    interval_energy = self._float_or_none(
                        interval.get("estimated_energy_kwh"),
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

        confirmed = self._clean_string_list(
            assignment.get("confirmed_session_ids")
        )
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
                "No matching ground-truth NILM sessions were found for this "
                "assignment."
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
        durations: list[float] = []
        for session in self._coordinator.store_data.nilm_session_history_by_circuit.get(
            circuit_id,
            (),
        ):
            if (
                not isinstance(session, Mapping)
                or str(session.get("session_id") or "").strip() not in confirmed
            ):
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
            return
        typical = float(median(durations))
        # ponytail: half/double the median until labelled volume supports percentiles.
        assignment["typical_duration_seconds"] = round(typical, 3)
        assignment["min_duration_seconds"] = round(
            max(30.0, min(min(durations), typical * 0.5)),
            3,
        )
        assignment["max_duration_seconds"] = round(
            max(max(durations), typical * 2.0),
            3,
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

    async def async_mark_nilm_signature_expected(
        self,
        circuit_id: str,
        signature_id: str,
    ) -> None:
        """Persist an expected NILM signature review decision."""
        signature = self.signature_for_review(circuit_id, signature_id)
        signature["expected"] = True
        signature["review_state"] = "expected"
        assignment = self.upsert_assignment(
            circuit_id,
            label=self._signature_assignment_label(signature, signature_id),
            signature_fingerprint=self._signature_fingerprint_value(
                signature,
                signature_id,
            ),
            lifecycle_state="expected",
            confidence=signature.get("confidence", 1.0),
        )
        signature["assignment_id"] = assignment["assignment_id"]
        await self._async_save_nilm_review_change(circuit_id)

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
                if signature_fingerprint
                in assignment.get("signature_fingerprints", ())
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
        coordinator.refresh_ux_state_for_circuit(
            circuit_id,
            coordinator.current_time(),
        )
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
        assignment["updated_at"] = self._coordinator.current_time().isoformat()
        await self.async_save_assignment_change()
        return dict(assignment)

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
        assignment["keep_assignment_for_masking"] = bool(
            keep_assignment_for_masking
        )
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
        target_confirmed = self._clean_string_list(
            target.get("confirmed_session_ids")
        )
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
            session_id
            for session_id in rejected
            if session_id not in confirmed_set
        ]
        target["confirmed_session_ids"] = confirmed
        target["rejected_session_ids"] = rejected
        target["confirmed_sessions"] = len(confirmed)
        target["rejected_sessions"] = len(rejected)
        validation_total = len(confirmed) + len(rejected)
        target["false_positive_rate"] = (
            round(len(rejected) / validation_total, 3)
            if validation_total
            else 0.0
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
        for interval in (
            self._coordinator.store_data.nilm_label_intervals_by_circuit.get(
                circuit_id,
                [],
            )
        ):
            if interval.get("assignment_id") == source_id:
                interval["assignment_id"] = target_id
        await self.async_save_assignment_change()
        return dict(target)

    async def async_publish_nilm_appliance_assignment(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Publish estimated HA entities for a NILM assignment."""
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        if assignment.get("conversion_state") == "direct_meter":
            raise ValueError(
                "A direct-meter conversion cannot republish duplicate NILM entities."
            )
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
        await self._coordinator.config_entry_controller.async_reload()

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
            device_present = device_registry.async_get_device(
                identifiers={(DOMAIN, f"{entry_id}_nilm_{assignment_id}")},
            ) is not None
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
    if interval_id and interval_id in _clean_string_list(
        assignment.get("label_interval_ids")
    ):
        return True
    assignment_id = str(assignment.get("assignment_id") or "").strip()
    if (
        assignment_id
        and str(interval.get("assignment_id") or "").strip() == assignment_id
    ):
        return True
    interval_appliance = str(
        interval.get("appliance_id") or interval.get("label") or ""
    ).strip().casefold()
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
