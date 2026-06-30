from __future__ import annotations

from typing import Any


class NilmController:
    """Own NILM appliance assignment lifecycle workflows."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

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
