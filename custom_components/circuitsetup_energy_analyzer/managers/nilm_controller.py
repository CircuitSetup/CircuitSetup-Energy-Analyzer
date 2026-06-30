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
    ) -> None:
        self._coordinator = coordinator
        self._clean_string_list = clean_string_list
        self._append_unique = append_unique
        self._nonnegative_float_value = nonnegative_float_value

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
