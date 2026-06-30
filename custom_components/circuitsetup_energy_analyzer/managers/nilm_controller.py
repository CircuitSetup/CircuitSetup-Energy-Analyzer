from __future__ import annotations

from collections.abc import Callable
from typing import Any


class NilmController:
    """Own NILM appliance assignment lifecycle workflows."""

    def __init__(
        self,
        coordinator: Any,
        *,
        clean_string_list: Callable[[Any], list[str]],
        append_unique: Callable[[list[str], Any], None],
        nonnegative_float_value: Callable[..., float],
        label_interval_datetime: Callable[[Any, str], Any],
        label_interval_id: Callable[[str, str, str, str], str],
        signature_fingerprint_value: Callable[[Any, str], str],
        label_interval_max_items: int,
        round_optional_number: Callable[[Any], float | None],
    ) -> None:
        self._coordinator = coordinator
        self._clean_string_list = clean_string_list
        self._append_unique = append_unique
        self._nonnegative_float_value = nonnegative_float_value
        self._label_interval_datetime = label_interval_datetime
        self._label_interval_id = label_interval_id
        self._signature_fingerprint_value = signature_fingerprint_value
        self._label_interval_max_items = label_interval_max_items
        self._round_optional_number = round_optional_number

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
        now_dt = coordinator._now_fn()
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
        del intervals[:-self._label_interval_max_items]

        coordinator._mark_store_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now_dt)
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
        now_dt = coordinator._now_fn()
        coordinator._mark_store_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now_dt)
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
        signature = coordinator._nilm_signature_for_review(circuit_id, signature_id)
        fingerprint = self._signature_fingerprint_value(signature, signature_id)
        assignment = coordinator._upsert_nilm_assignment(
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
        coordinator._remove_nilm_signature_from_other_assignments(
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
        assignment = coordinator._upsert_nilm_assignment(
            circuit_id,
            label=label,
            appliance_id=appliance_id,
            appliance_profile=appliance_profile,
            assignment_id=assignment_id,
            signature_fingerprint=signature_fingerprint,
            session_id=session_id_text,
            lifecycle_state="assigned",
        )
        coordinator._mark_store_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(coordinator._now_fn())
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
        assignment = coordinator._upsert_nilm_assignment(
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
        coordinator._mark_store_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(coordinator._now_fn())
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
        now_dt = coordinator._now_fn()
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
        coordinator._mark_store_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now_dt)
        return dict(assignment)

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

    async def _async_save_nilm_review_change(self, circuit_id: str) -> None:
        coordinator = self._coordinator
        coordinator._mark_store_dirty()
        coordinator._refresh_nilm_state(circuit_id)
        coordinator._refresh_ux_state_for_circuit(circuit_id, coordinator._now_fn())
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(coordinator._now_fn())

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
        assignment["updated_at"] = self._coordinator._now_fn().isoformat()
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
        assignment["updated_at"] = self._coordinator._now_fn().isoformat()
        await self.async_save_assignment_change()
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
        target["confirmed_sessions"] = len(
            self._clean_string_list(target.get("confirmed_session_ids"))
        )
        target["rejected_sessions"] = len(
            self._clean_string_list(target.get("rejected_session_ids"))
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
        target["updated_at"] = self._coordinator._now_fn().isoformat()

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
        assignment["publish_entities"] = True
        assignment["created_device"] = True
        assignment["lifecycle_state"] = "published"
        assignment["updated_at"] = self._coordinator._now_fn().isoformat()
        await self.async_save_assignment_change()
        return dict(assignment)

    async def async_unpublish_nilm_appliance_assignment(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Stop publishing estimated HA entities for a NILM assignment."""
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        assignment["publish_entities"] = False
        if assignment.get("lifecycle_state") == "published":
            assignment["lifecycle_state"] = "validated"
        assignment["updated_at"] = self._coordinator._now_fn().isoformat()
        await self.async_save_assignment_change()
        return dict(assignment)

    async def async_retire_nilm_appliance_assignment(
        self,
        circuit_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Retire a NILM assignment and stop publishing entities."""
        assignment = self.assignment_for_id(circuit_id, assignment_id)
        assignment["publish_entities"] = False
        assignment["lifecycle_state"] = "retired"
        assignment["updated_at"] = self._coordinator._now_fn().isoformat()
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
        self._coordinator._mark_store_dirty()
        self._coordinator.async_set_updated_data(self._coordinator.state)
        await self._coordinator._async_save_store(self._coordinator._now_fn())
        await self._coordinator._async_reload_config_entry()
