# Source Sensor Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit Home Assistant options action that rescans the already-selected source devices for added or renamed electrical sensors without requiring the user to resave source selection.

**Architecture:** Add one confirmation-only options-flow step and reuse the existing source payload, device expansion, validation, option merge, persistence, and reload pipeline. Add a narrow validation switch to the existing expansion helper so a refresh cannot silently replace device-derived sensors when no source device or no matching device sensor is available.

**Tech Stack:** Python 3.12, Home Assistant config entries, Voluptuous, pytest, JSON translations, Markdown documentation.

## Global Constraints

- The refresh is explicit; do not add background polling, a service, or a custom panel control.
- Preserve manual extra sources, circuit assignments, mains sources, and unrelated options.
- Do not add frontend JavaScript or bump `PANEL_MODULE_VERSION`.
- Put all new user-facing copy in `custom_components/circuitsetup_energy_analyzer/translations/en.json`.
- Work only on `feature/source-sensor-refresh` in the isolated `.worktrees/source-sensor-refresh` worktree.

---

### Task 1: Refresh Source Sensors Options Flow

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/config_flow.py`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `_options_source_payload(config_entry) -> dict[str, Any]`, `_async_source_selection_with_device_entities(hass, user_input) -> dict[str, Any]`, `validate_options_input(user_input) -> dict[str, Any]`, `_options_with_updates(config_entry, updates) -> dict[str, Any]`, `_options_with_merged_source_circuit_sensors(config_entry, options) -> dict[str, Any]`, and `_async_save_options_flow_config(flow, options) -> None`.
- Produces: `CircuitSetupEnergyAnalyzerOptionsFlow.async_step_refresh_sources(user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult` and `_async_source_selection_with_device_entities(hass: Any, user_input: Mapping[str, Any], *, require_device_entities: bool = False) -> dict[str, Any]`.

- [ ] **Step 1: Write failing menu, confirmation, success, and failure tests**

Update the options-menu assertion to include `"refresh_sources"` directly after `"sources"`, then add focused tests using the existing `SimpleNamespace` config-entry fixtures:

```python
@pytest.mark.asyncio
async def test_options_refresh_sources_step_requires_confirmation() -> None:
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_DEVICES: ["meter-device"],
            CONF_SOURCE_ENTITIES: ["sensor.old_power"],
        },
    )
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)

    result = await flow.async_step_refresh_sources()

    assert result["type"] == "form"
    assert result["step_id"] == "refresh_sources"
    assert not _schema_keys(result["data_schema"])
    assert entry.options[CONF_SOURCE_ENTITIES] == ["sensor.old_power"]


@pytest.mark.asyncio
async def test_options_refresh_sources_rescans_selected_devices(monkeypatch) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    async def discover(hass, source_devices):
        assert hass is flow.hass
        assert tuple(source_devices) == ("meter-device",)
        return ["sensor.renamed_power", "sensor.added_current"]

    monkeypatch.setattr(
        config_flow,
        "_async_discover_energy_source_entities_for_devices",
        discover,
    )
    class FakeConfigEntries:
        def __init__(self) -> None:
            self.reloads: list[str] = []

        def async_update_entry(self, entry, **kwargs) -> None:
            entry.options = dict(kwargs["options"])

        async def async_reload(self, entry_id: str) -> bool:
            self.reloads.append(entry_id)
            return True

    entry = SimpleNamespace(
        data={},
        options={
            CONF_SOURCE_DEVICES: ["meter-device"],
            CONF_EXTRA_SOURCE_ENTITIES: ["sensor.manual_power"],
            CONF_SOURCE_ENTITIES: ["sensor.old_power", "sensor.manual_power"],
            CONF_SENSITIVITY: "quiet",
            CONF_RETENTION_MODE: "diagnostic",
        },
        entry_id="entry-1",
    )
    config_entries = FakeConfigEntries()
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace(config_entries=config_entries)

    result = await flow.async_step_refresh_sources({})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SOURCE_ENTITIES] == [
        "sensor.renamed_power",
        "sensor.added_current",
        "sensor.manual_power",
    ]
    assert result["data"][CONF_EXTRA_SOURCE_ENTITIES] == ["sensor.manual_power"]
    assert result["data"][CONF_SENSITIVITY] == "quiet"
    assert result["data"][CONF_RETENTION_MODE] == "diagnostic"
    assert config_entries.reloads == ["entry-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_devices", "discovered", "error_key"),
    [
        ([], [], "no_source_devices"),
        (["meter-device"], [], "no_source_device_entities"),
    ],
)
async def test_options_refresh_sources_preserves_options_on_failure(
    monkeypatch,
    source_devices,
    discovered,
    error_key,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.config_flow as config_flow
    from custom_components.circuitsetup_energy_analyzer.config_flow import (
        CircuitSetupEnergyAnalyzerOptionsFlow,
    )

    async def discover(hass, selected_devices):
        return discovered

    monkeypatch.setattr(
        config_flow,
        "_async_discover_energy_source_entities_for_devices",
        discover,
    )
    original_options = {
        CONF_SOURCE_DEVICES: source_devices,
        CONF_EXTRA_SOURCE_ENTITIES: ["sensor.manual_power"],
        CONF_SOURCE_ENTITIES: ["sensor.old_power", "sensor.manual_power"],
    }
    entry = SimpleNamespace(data={}, options=dict(original_options))
    flow = CircuitSetupEnergyAnalyzerOptionsFlow(entry)
    flow.hass = SimpleNamespace()

    result = await flow.async_step_refresh_sources({})

    assert result["type"] == "form"
    assert result["step_id"] == "refresh_sources"
    assert result["errors"]["base"] == error_key
    assert entry.options == original_options
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
C:\Users\John\Documents\CS_energy_analyzer\.venv\Scripts\python.exe -m pytest tests\test_config_flow.py -k "options_flow_init_offers_assignment_and_source_editing or options_refresh_sources" -q
```

Expected: failures because the menu lacks `refresh_sources` and `async_step_refresh_sources` does not exist.

- [ ] **Step 3: Implement the minimal options step and guarded device refresh**

Add the menu option and constants:

```python
ERROR_NO_SOURCE_DEVICES = "no_source_devices"
ERROR_NO_SOURCE_DEVICE_ENTITIES = "no_source_device_entities"
```

Add the options-flow step:

```python
async def async_step_refresh_sources(
    self,
    user_input: dict[str, Any] | None = None,
) -> config_entries.ConfigFlowResult:
    """Refresh sensors discovered from the selected source devices."""
    if user_input is None:
        return self.async_show_form(
            step_id="refresh_sources",
            data_schema=vol.Schema({}),
        )

    try:
        validated = validate_options_input(
            await _async_source_selection_with_device_entities(
                getattr(self, "hass", None),
                _options_source_payload(self._config_entry),
                require_device_entities=True,
            )
        )
    except SetupValidationError as err:
        return self.async_show_form(
            step_id="refresh_sources",
            data_schema=vol.Schema({}),
            errors={"base": err.error_key},
        )

    updated_options = _options_with_updates(self._config_entry, validated)
    updated_options = _options_with_merged_source_circuit_sensors(
        self._config_entry,
        updated_options,
    )
    await _async_save_options_flow_config(self, updated_options)
    return self.async_create_entry(title="", data=updated_options)
```

Extend the existing helper without changing its default behavior:

```python
async def _async_source_selection_with_device_entities(
    hass: Any,
    user_input: Mapping[str, Any],
    *,
    require_device_entities: bool = False,
) -> dict[str, Any]:
    """Return source selection with selected devices expanded to source entities."""
    source_devices = _strict_string_list(
        user_input.get(CONF_SOURCE_DEVICES, []),
        invalid_error_key="invalid_source_devices",
    )
    if require_device_entities and not source_devices:
        raise SetupValidationError(ERROR_NO_SOURCE_DEVICES)
    extra_source_entities = _strict_string_list(
        user_input.get(CONF_EXTRA_SOURCE_ENTITIES, []),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    device_source_entities = await _async_discover_energy_source_entities_for_devices(
        hass,
        source_devices,
    )
    if require_device_entities and not device_source_entities:
        raise SetupValidationError(ERROR_NO_SOURCE_DEVICE_ENTITIES)
    merged = list(dict.fromkeys([*device_source_entities, *extra_source_entities]))
    return {
        **dict(user_input),
        CONF_SOURCE_DEVICES: source_devices,
        CONF_EXTRA_SOURCE_ENTITIES: extra_source_entities,
        CONF_SOURCE_ENTITIES: merged,
    }
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit the options-flow behavior**

```powershell
git add custom_components/circuitsetup_energy_analyzer/config_flow.py tests/test_config_flow.py
git commit -m "feat: refresh source device sensors"
```

---

### Task 2: English Copy And Setup Documentation

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/translations/en.json`
- Modify: `tests/test_user_facing_text.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the `refresh_sources` menu and form step from Task 1 plus errors `no_source_devices` and `no_source_device_entities`.
- Produces: Home Assistant-rendered English menu, confirmation, validation text, and a documented recovery workflow.

- [ ] **Step 1: Write failing translation contract assertions**

Update `test_options_flow_labels_are_human_readable_and_described` to expect:

```python
"refresh_sources": "🔄 Refresh Source Sensors",
```

and add:

```python
refresh_sources = strings["options"]["step"]["refresh_sources"]
assert refresh_sources["title"] == "Refresh Source Sensors"
assert "added or renamed" in refresh_sources["description"].lower()
assert "manual extra sources" in refresh_sources["description"].lower()
assert "reload" in refresh_sources["description"].lower()
assert refresh_sources["submit"] == "Refresh Source Sensors"
assert "existing settings were not changed" in strings["options"]["error"][
    "no_source_device_entities"
].lower()
```

Add `("options", "refresh_sources")` to the runtime English translation source test and permit this intentional confirmation step to use an empty schema:

```python
assert (
    translated_step.get("data")
    or translated_step.get("sections")
    or step == "refresh_sources"
)
```

- [ ] **Step 2: Run the translation test and verify it fails**

Run:

```powershell
C:\Users\John\Documents\CS_energy_analyzer\.venv\Scripts\python.exe -m pytest tests\test_user_facing_text.py -k "options_flow_labels_are_human_readable_and_described or runtime_english_translation_is_the_single_source" -q
```

Expected: failures because the refresh menu, step, and errors are not translated.

- [ ] **Step 3: Add English translations and README guidance**

Add this menu and step copy under `options.step`:

```json
"refresh_sources": "🔄 Refresh Source Sensors"
```

```json
"refresh_sources": {
  "title": "Refresh Source Sensors",
  "description": "Rescan the currently selected Source Devices for added or renamed electrical sensors. Manual extra sources and other settings will be preserved. Submit to refresh sensors and reload the integration.",
  "submit": "Refresh Source Sensors"
}
```

Add these option errors:

```json
"no_source_devices": "Select at least one Source Device in Edit Source Selection before refreshing.",
"no_source_device_entities": "No supported electrical sensors were found on the selected Source Devices. Existing settings were not changed."
```

Add this sentence after the setup table in `README.md`:

```markdown
After adding or renaming sensors on a selected source device, use **Refresh Source Sensors** in the integration options to rescan that device while preserving manual extra sources and the rest of the configuration.
```

- [ ] **Step 4: Validate JSON and run the focused translation tests**

Run:

```powershell
jq empty custom_components/circuitsetup_energy_analyzer/translations/en.json
C:\Users\John\Documents\CS_energy_analyzer\.venv\Scripts\python.exe -m pytest tests\test_user_facing_text.py -k "options_flow_labels_are_human_readable_and_described or runtime_english_translation_is_the_single_source" -q
```

Expected: valid JSON and all selected tests pass.

- [ ] **Step 5: Commit the user-facing workflow**

```powershell
git add custom_components/circuitsetup_energy_analyzer/translations/en.json tests/test_user_facing_text.py README.md
git commit -m "docs: explain source sensor refresh"
```

---

### Task 3: Full Verification

**Files:**
- Verify: all files changed by Tasks 1 and 2.

**Interfaces:**
- Consumes: the completed refresh flow, translations, tests, and README update.
- Produces: a clean, verified feature branch ready for review.

- [ ] **Step 1: Run focused regression tests**

```powershell
C:\Users\John\Documents\CS_energy_analyzer\.venv\Scripts\python.exe -m pytest tests\test_config_flow.py tests\test_user_facing_text.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the repository Home Assistant verification gate**

```powershell
.\.codex\scripts\verify-pr.ps1 -HomeAssistant
```

Expected: diff checks, lint, unit tests, and Home Assistant contract tests pass.

- [ ] **Step 3: Confirm scope and cache-buster stability**

```powershell
git status --short
git diff master...HEAD --stat
git diff master...HEAD -- custom_components/circuitsetup_energy_analyzer/panel.py
```

Expected: only the design/plan, config flow, tests, English translation, and README are changed; the panel diff is empty.

- [ ] **Step 4: Commit any verification-only fixes**

If verification required a source or test correction, stage only those intended files and commit with a specific message. If no correction was needed, do not create an empty commit.
