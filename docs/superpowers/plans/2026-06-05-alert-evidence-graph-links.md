# Alert Evidence Graph Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user click an Energy Analyzer notification and land on a Home Assistant evidence view that explains why the alert was flagged, with graph-ready entities and the alert context visible together.

**Architecture:** Add pure URL/entity-selection helpers that turn existing `AlertEvidence` plus the configured circuit into an evidence dashboard path, graph entity list, and time window. Reuse the existing `Alert Evidence` sensor attributes and persistent notification path instead of creating a custom frontend panel in V1. Add dashboard YAML and blueprint support so persistent notifications and mobile notification actions can open the same evidence view.

**Tech Stack:** Python Home Assistant custom integration, Home Assistant persistent notifications with Markdown links, existing analyzer sensor attributes, Lovelace YAML using standard `entities`, `markdown`, and `history-graph` cards, pytest.

---

## Scope And Decisions

V1 should avoid a custom Lovelace card or custom frontend panel. Standard Home Assistant cards cannot dynamically render a graph based on a URL query parameter, so V1 will do the practical version:

- Persistent notifications include an `Open evidence graph` Markdown link.
- Alert Evidence entity attributes include `evidence_path`, `graph_entities`, `source_entities`, `graph_window_start`, and `graph_window_end`.
- The sample dashboard gets an `Alert evidence` section with the latest alert entity and graph cards for the relevant rollup/evidence entities.
- The alert blueprint exposes the same `evidence_path` for mobile notification `url` / `clickAction` usage.

This is enough for a user to click a notification and immediately see the related alert explanation and graph context. A custom dynamic frontend can be handled as a separate feature if the standard-card approach feels too limited.

## File Structure

- Create `custom_components/circuitsetup_energy_analyzer/alert_links.py`
  - Pure helpers for alert IDs, dashboard paths, graph entity selection, and alert time windows.
  - No Home Assistant imports.
- Modify `custom_components/circuitsetup_energy_analyzer/ux.py`
  - Enrich `alert_evidence_detail()` with graph/navigation metadata.
- Modify `custom_components/circuitsetup_energy_analyzer/coordinator.py`
  - Pass the circuit config into alert detail and notification creation.
- Modify `custom_components/circuitsetup_energy_analyzer/notifications.py`
  - Add a helper that builds persistent-notification Markdown with an evidence link.
- Modify `docs/dashboard-example.yaml`
  - Add an Alert Evidence section using standard HA cards.
- Modify `blueprints/automation/circuitsetup_energy_analyzer/energy_alert_notification.yaml`
  - Include evidence links in persistent notifications and expose template variables for mobile notification click/tap actions.
- Modify `README.md`
  - Explain how notification links and evidence graphs work.
- Modify tests:
  - `tests/test_alert_links.py`
  - `tests/test_ux.py`
  - `tests/test_services.py`
  - `tests/test_coordinator.py`
  - `tests/test_user_facing_text.py`

---

### Task 1: Add Pure Alert Link And Graph Entity Helpers

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/alert_links.py`
- Create: `tests/test_alert_links.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_alert_links.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
    Severity,
)


def _alert(feature: str = "leg_imbalance") -> AlertEvidence:
    return AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="hvac",
        severity=Severity.WARNING,
        message="Possible issue: HVAC leg imbalance",
        feature=feature,
        observed_value=62.0,
        baseline_value=20.0,
        change_ratio=2.1,
        repeated_count=3,
        first_seen=datetime(2026, 6, 5, 10, 0, tzinfo=UTC),
        last_seen=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        features={"leg_imbalance": 2.1, "real_power": 1.4},
    )


def _config() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.hvac_l1_watts", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.hvac_l2_watts", SensorRole.REAL_POWER, leg="b"),
            SensorRef("sensor.hvac_l1_current", SensorRole.CURRENT, leg="a"),
            SensorRef("sensor.hvac_l2_current", SensorRole.CURRENT, leg="b"),
            SensorRef("sensor.hvac_l1_reactive_power", SensorRole.REACTIVE_POWER, leg="a"),
            SensorRef("sensor.hvac_l2_reactive_power", SensorRole.REACTIVE_POWER, leg="b"),
            SensorRef("sensor.hvac_power_factor", SensorRole.POWER_FACTOR),
            SensorRef("sensor.hvac_energy", SensorRole.ENERGY),
        ),
    )


def test_alert_evidence_path_contains_alert_context() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        DEFAULT_ALERT_EVIDENCE_PATH,
        alert_evidence_path,
    )

    path = alert_evidence_path(_alert(), dashboard_path=DEFAULT_ALERT_EVIDENCE_PATH)
    parsed = urlparse(path)
    params = parse_qs(parsed.query)

    assert parsed.path == "/circuitsetup-energy-analyzer/alert-evidence"
    assert params["circuit_id"] == ["hvac"]
    assert params["feature"] == ["leg_imbalance"]
    assert params["alert_id"][0].startswith("circuitsetup_energy_analyzer_alert_hvac_")


def test_alert_graph_entities_prefer_feature_related_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_entities,
    )

    assert alert_graph_entities(_alert("leg_imbalance"), _config()) == (
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
        "sensor.hvac_l1_current",
        "sensor.hvac_l2_current",
    )
    assert alert_graph_entities(_alert("reactive_power"), _config()) == (
        "sensor.hvac_l1_reactive_power",
        "sensor.hvac_l2_reactive_power",
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
        "sensor.hvac_power_factor",
    )


def test_alert_graph_window_wraps_first_and_last_seen() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_window,
    )

    window = alert_graph_window(_alert(), padding=timedelta(hours=2))

    assert window == (
        datetime(2026, 6, 5, 8, 0, tzinfo=UTC),
        datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
    )
```

- [ ] **Step 2: Run the tests and confirm red**

Run:

```powershell
pytest tests/test_alert_links.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'custom_components.circuitsetup_energy_analyzer.alert_links'`.

- [ ] **Step 3: Implement the helper module**

Create `custom_components/circuitsetup_energy_analyzer/alert_links.py`:

```python
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from urllib.parse import urlencode

from .models import AlertEvidence, CircuitConfig, SensorRole
from .notifications import notification_id_for_alert

DEFAULT_ALERT_EVIDENCE_PATH = "/circuitsetup-energy-analyzer/alert-evidence"
MAX_GRAPH_ENTITIES = 8

_FEATURE_ROLE_HINTS: tuple[tuple[tuple[str, ...], tuple[SensorRole, ...]], ...] = (
    (("leg_imbalance", "phase", "capacity"), (SensorRole.REAL_POWER, SensorRole.CURRENT)),
    (("reactive", "var"), (SensorRole.REACTIVE_POWER, SensorRole.REAL_POWER, SensorRole.POWER_FACTOR)),
    (("power_factor", "pf"), (SensorRole.POWER_FACTOR, SensorRole.REAL_POWER, SensorRole.APPARENT_POWER)),
    (("apparent", "va"), (SensorRole.APPARENT_POWER, SensorRole.REAL_POWER, SensorRole.POWER_FACTOR)),
    (("energy", "goal", "billing", "cost", "utility"), (SensorRole.ENERGY, SensorRole.REAL_POWER)),
    (("demand", "always_on", "standby", "cycle", "activity"), (SensorRole.REAL_POWER, SensorRole.CURRENT)),
    (("voltage", "sag", "swell"), (SensorRole.VOLTAGE, SensorRole.REAL_POWER, SensorRole.CURRENT)),
)

_DEFAULT_ROLES = (
    SensorRole.REAL_POWER,
    SensorRole.CURRENT,
    SensorRole.REACTIVE_POWER,
    SensorRole.APPARENT_POWER,
    SensorRole.POWER_FACTOR,
    SensorRole.ENERGY,
)


def alert_evidence_path(
    alert: AlertEvidence,
    *,
    dashboard_path: str = DEFAULT_ALERT_EVIDENCE_PATH,
) -> str:
    """Return a relative HA URL for an alert evidence dashboard view."""
    clean_path = "/" + dashboard_path.strip("/")
    query = urlencode(
        {
            "alert_id": notification_id_for_alert(alert),
            "circuit_id": alert.circuit_id,
            "feature": _alert_feature(alert),
        },
    )
    return f"{clean_path}?{query}"


def alert_graph_entities(
    alert: AlertEvidence,
    config: CircuitConfig | None,
    *,
    max_entities: int = MAX_GRAPH_ENTITIES,
) -> tuple[str, ...]:
    """Return source entities that best explain the alert on a graph."""
    if config is None:
        return ()

    roles = _roles_for_feature(_alert_feature(alert))
    selected: list[str] = []
    for role in roles:
        for sensor in config.sensors:
            if sensor.role is role and sensor.entity_id not in selected:
                selected.append(sensor.entity_id)
                if len(selected) >= max_entities:
                    return tuple(selected)
    return tuple(selected)


def alert_source_entities(config: CircuitConfig | None) -> tuple[str, ...]:
    """Return every configured source entity for this circuit."""
    if config is None:
        return ()
    return tuple(dict.fromkeys(sensor.entity_id for sensor in config.sensors))


def alert_graph_window(
    alert: AlertEvidence,
    *,
    padding: timedelta = timedelta(hours=2),
) -> tuple[datetime, datetime]:
    """Return the start and end datetime that should surround alert evidence."""
    start = alert.first_seen or alert.timestamp
    end = alert.last_seen or alert.timestamp
    return start - padding, end + padding


def _roles_for_feature(feature: str) -> tuple[SensorRole, ...]:
    normalized = feature.lower()
    for tokens, roles in _FEATURE_ROLE_HINTS:
        if any(token in normalized for token in tokens):
            return roles
    return _DEFAULT_ROLES


def _alert_feature(alert: AlertEvidence) -> str:
    if alert.feature:
        return alert.feature
    if alert.event_type is not None:
        return alert.event_type.value
    return "alert"
```

- [ ] **Step 4: Run the tests and confirm green**

Run:

```powershell
pytest tests/test_alert_links.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/circuitsetup_energy_analyzer/alert_links.py tests/test_alert_links.py
git commit -m "Add alert evidence graph link helpers"
```

---

### Task 2: Enrich Alert Evidence Sensor Attributes

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/ux.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/coordinator.py`
- Modify: `tests/test_ux.py`
- Modify: `tests/test_coordinator.py`

- [ ] **Step 1: Update the failing UX test**

In `tests/test_ux.py`, update `test_alert_evidence_detail_is_json_safe_and_explains_change()` so it builds a `CircuitConfig` and expects graph metadata:

```python
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
            SensorRef("sensor.fridge_reactive_power", SensorRole.REACTIVE_POWER),
            SensorRef("sensor.fridge_power_factor", SensorRole.POWER_FACTOR),
        ),
    )

    detail = alert_evidence_detail(
        alert,
        config=config,
        dashboard_path="/circuitsetup-energy-analyzer/alert-evidence",
    )

    assert detail["evidence_path"].startswith(
        "/circuitsetup-energy-analyzer/alert-evidence?"
    )
    assert detail["graph_entities"] == [
        "sensor.fridge_reactive_power",
        "sensor.fridge_power",
        "sensor.fridge_power_factor",
    ]
    assert detail["source_entities"] == [
        "sensor.fridge_power",
        "sensor.fridge_reactive_power",
        "sensor.fridge_power_factor",
    ]
    assert detail["graph_window_start"] == "2026-06-02T08:00:00+00:00"
    assert detail["graph_window_end"] == "2026-06-02T14:30:00+00:00"
```

Keep the existing assertions for `alert_id`, `message`, `observed_value`, `baseline_value`, and `contributing_metrics`.

- [ ] **Step 2: Run the UX test and confirm red**

Run:

```powershell
pytest tests/test_ux.py::test_alert_evidence_detail_is_json_safe_and_explains_change -q
```

Expected: fail because `alert_evidence_detail()` does not accept `config` or return the new keys.

- [ ] **Step 3: Update `ux.alert_evidence_detail()`**

In `custom_components/circuitsetup_energy_analyzer/ux.py`, import the helpers:

```python
from .alert_links import (
    DEFAULT_ALERT_EVIDENCE_PATH,
    alert_evidence_path,
    alert_graph_entities,
    alert_graph_window,
    alert_source_entities,
)
```

Change the function signature:

```python
def alert_evidence_detail(
    alert: AlertEvidence,
    *,
    config: CircuitConfig | None = None,
    dashboard_path: str = DEFAULT_ALERT_EVIDENCE_PATH,
) -> dict[str, Any]:
```

Inside the function, compute:

```python
    graph_start, graph_end = alert_graph_window(alert)
```

Add these keys to the returned dict:

```python
        "evidence_path": alert_evidence_path(alert, dashboard_path=dashboard_path),
        "graph_entities": list(alert_graph_entities(alert, config)),
        "source_entities": list(alert_source_entities(config)),
        "graph_window_start": graph_start.isoformat(),
        "graph_window_end": graph_end.isoformat(),
```

- [ ] **Step 4: Pass circuit config from the coordinator**

In `custom_components/circuitsetup_energy_analyzer/coordinator.py`, change:

```python
self.state.alert_evidence_by_circuit[circuit_id] = alert_evidence_detail(alert)
```

to:

```python
self.state.alert_evidence_by_circuit[circuit_id] = alert_evidence_detail(
    alert,
    config=self._config_for_circuit(circuit_id),
)
```

- [ ] **Step 5: Update coordinator tests that compare alert evidence dictionaries**

Search:

```powershell
rg -n "alert_evidence_by_circuit|alert_evidence_detail" tests/test_coordinator.py tests/test_entities.py
```

For exact dictionary comparisons, add the new keys. For tests that do not care about graph metadata, assert selected keys instead of full dictionary equality:

```python
detail = coordinator.state.alert_evidence_by_circuit["fridge"]
assert detail["alert_id"]
assert detail["message"] == "Possible issue"
assert "evidence_path" in detail
assert isinstance(detail["graph_entities"], list)
```

- [ ] **Step 6: Run the focused tests**

Run:

```powershell
pytest tests/test_ux.py tests/test_entities.py tests/test_coordinator.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add custom_components/circuitsetup_energy_analyzer/ux.py custom_components/circuitsetup_energy_analyzer/coordinator.py tests/test_ux.py tests/test_entities.py tests/test_coordinator.py
git commit -m "Expose alert evidence graph metadata"
```

---

### Task 3: Add Evidence Links To Persistent Notifications

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/notifications.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/coordinator.py`
- Modify: `tests/test_services.py`
- Modify: `tests/test_coordinator.py`

- [ ] **Step 1: Add failing notification-message tests**

In `tests/test_services.py`, add:

```python
def test_alert_notification_message_includes_evidence_link_and_graph_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        alert_notification_message,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="hvac",
        severity=Severity.WARNING,
        message="Possible issue: HVAC leg imbalance",
        feature="leg_imbalance",
        observed_value=62.0,
        baseline_value=20.0,
        change_ratio=2.1,
        repeated_count=3,
        first_seen=datetime(2026, 6, 5, 10, 0, tzinfo=UTC),
        last_seen=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
    )
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.hvac_l1_watts", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.hvac_l2_watts", SensorRole.REAL_POWER, leg="b"),
            SensorRef("sensor.hvac_l1_current", SensorRole.CURRENT, leg="a"),
            SensorRef("sensor.hvac_l2_current", SensorRole.CURRENT, leg="b"),
        ),
    )

    message = alert_notification_message(alert, config=config)

    assert "Possible issue: HVAC leg imbalance" in message
    assert "[Open evidence graph](/circuitsetup-energy-analyzer/alert-evidence?" in message
    assert "sensor.hvac_l1_watts" in message
    assert "sensor.hvac_l2_current" in message
    assert "Observed value: 62.0" in message
    assert "Baseline value: 20.0" in message
```

Update imports at the top of `tests/test_services.py`:

```python
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
```

- [ ] **Step 2: Run the test and confirm red**

Run:

```powershell
pytest tests/test_services.py::test_alert_notification_message_includes_evidence_link_and_graph_entities -q
```

Expected: fail because `alert_notification_message` does not exist.

- [ ] **Step 3: Implement notification message helper**

In `custom_components/circuitsetup_energy_analyzer/notifications.py`, import:

```python
from .alert_links import (
    DEFAULT_ALERT_EVIDENCE_PATH,
    alert_evidence_path,
    alert_graph_entities,
)
from .models import AlertEvidence, CircuitConfig
```

Add:

```python
def alert_notification_message(
    alert: AlertEvidence,
    *,
    config: CircuitConfig | None = None,
    dashboard_path: str = DEFAULT_ALERT_EVIDENCE_PATH,
) -> str:
    """Return Markdown notification text with a link to alert evidence."""
    path = alert_evidence_path(alert, dashboard_path=dashboard_path)
    graph_entities = alert_graph_entities(alert, config)
    entity_text = (
        "\n\nGraph entities: " + ", ".join(graph_entities)
        if graph_entities
        else ""
    )
    return (
        f"{alert.message}\n\n"
        f"[Open evidence graph]({path})\n\n"
        f"Observed value: {alert.observed_value}\n"
        f"Baseline value: {alert.baseline_value}\n"
        f"Repeated observations: {alert.repeated_count}"
        f"{entity_text}"
    )
```

Change `async_create_alert_notification()` signature:

```python
async def async_create_alert_notification(
    hass: Any,
    alert: AlertEvidence,
    *,
    config: CircuitConfig | None = None,
    dashboard_path: str = DEFAULT_ALERT_EVIDENCE_PATH,
) -> None:
```

Change the `create()` call to pass:

```python
        alert_notification_message(
            alert,
            config=config,
            dashboard_path=dashboard_path,
        ),
```

- [ ] **Step 4: Pass config from coordinator notifications**

In `custom_components/circuitsetup_energy_analyzer/coordinator.py`, change:

```python
await notifications.async_create_alert_notification(self.hass, alert)
```

to:

```python
await notifications.async_create_alert_notification(
    self.hass,
    alert,
    config=self._config_for_circuit(alert.circuit_id),
)
```

- [ ] **Step 5: Update notification monkeypatch tests**

Search:

```powershell
rg -n "async def fake_notification\\(hass, alert\\)" tests/test_coordinator.py
```

Change each fake to accept keyword arguments:

```python
async def fake_notification(hass, alert, **kwargs) -> None:
    notifications.append(alert)
```

Where the test should verify the config is passed, use:

```python
seen: list[tuple[AlertEvidence, object]] = []

async def fake_notification(hass, alert, **kwargs) -> None:
    seen.append((alert, kwargs.get("config")))

assert seen[0][1].circuit_id == "fridge"
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
pytest tests/test_services.py tests/test_coordinator.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add custom_components/circuitsetup_energy_analyzer/notifications.py custom_components/circuitsetup_energy_analyzer/coordinator.py tests/test_services.py tests/test_coordinator.py
git commit -m "Link alert notifications to evidence graphs"
```

---

### Task 4: Add Alert Evidence Section To Dashboard YAML

**Files:**
- Modify: `docs/dashboard-example.yaml`
- Modify: `tests/test_user_facing_text.py`

- [ ] **Step 1: Add failing dashboard test**

In `tests/test_user_facing_text.py`, add:

```python
def test_dashboard_example_includes_alert_evidence_graph_section() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text()
    refs = set(_dashboard_entity_refs(dashboard_text))

    assert "Alert evidence" in dashboard_text
    assert "Open from notifications" in dashboard_text
    assert "sensor.hvac_alert_evidence" in refs
    assert "sensor.hvac_leg_imbalance" in refs
    assert "sensor.hvac_power_quality_score" in refs
    assert "sensor.hvac_reactive_power_drift" in refs
    assert "sensor.hvac_power_factor_drift" in refs
```

- [ ] **Step 2: Run the test and confirm red**

Run:

```powershell
pytest tests/test_user_facing_text.py::test_dashboard_example_includes_alert_evidence_graph_section -q
```

Expected: fail because the dashboard does not yet include the new section.

- [ ] **Step 3: Add the dashboard section**

In `docs/dashboard-example.yaml`, add a new section after `Power quality detail`:

```yaml
  - type: grid
    title: Alert evidence
    cards:
      - type: markdown
        title: Open from notifications
        content: >
          Possible-issue notifications include an Open evidence graph link.
          Use this section to review the latest alert evidence, source entities,
          and graph context before making changes to CT orientation, circuit
          assignments, thresholds, or appliance settings.
      - type: entities
        title: Latest HVAC alert evidence
        entities:
          - entity: sensor.hvac_alert_evidence
          - entity: sensor.hvac_electrical_health
          - entity: sensor.hvac_power_quality_evidence
          - entity: sensor.hvac_leg_imbalance_status
          - entity: sensor.hvac_metric_consistency_status
      - type: history-graph
        title: HVAC evidence graph
        hours_to_show: 72
        entities:
          - entity: sensor.hvac_leg_imbalance
          - entity: sensor.hvac_power_quality_score
          - entity: sensor.hvac_reactive_power_drift
          - entity: sensor.hvac_apparent_power_drift
          - entity: sensor.hvac_power_factor_drift
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/test_user_facing_text.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add docs/dashboard-example.yaml tests/test_user_facing_text.py
git commit -m "Add alert evidence graph dashboard section"
```

---

### Task 5: Update The Alert Blueprint For Evidence Links And Mobile Click Actions

**Files:**
- Modify: `blueprints/automation/circuitsetup_energy_analyzer/energy_alert_notification.yaml`
- Modify: `tests/test_user_facing_text.py`

- [ ] **Step 1: Add failing blueprint test assertions**

In `tests/test_user_facing_text.py`, update `test_alert_blueprint_is_user_friendly_and_actionable()` to assert:

```python
    assert "evidence_path" in blueprint_text
    assert "Open evidence graph" in blueprint_text
    assert "clickAction" in blueprint_text
    assert "url:" in blueprint_text
```

- [ ] **Step 2: Run the test and confirm red**

Run:

```powershell
pytest tests/test_user_facing_text.py::test_alert_blueprint_is_user_friendly_and_actionable -q
```

Expected: fail because the blueprint does not expose evidence links yet.

- [ ] **Step 3: Add evidence path variables**

In `blueprints/automation/circuitsetup_energy_analyzer/energy_alert_notification.yaml`, add under `variables:`:

```yaml
  evidence_path: >-
    {% if trigger.to_state and trigger.to_state.attributes.evidence_path %}
      {{ trigger.to_state.attributes.evidence_path }}
    {% else %}
      /circuitsetup-energy-analyzer/alert-evidence
    {% endif %}
```

In the persistent notification message, add:

```yaml
                [Open evidence graph]({{ evidence_path }})
```

Add a short comment in `alert_actions` description:

```yaml
      description: Optional actions such as mobile notifications, lights, or scripts. Mobile app actions can use {{ evidence_path }} as both data.url and data.clickAction.
```

Add one disabled-by-default example to the blueprint description text, not as an executable action:

```yaml
  description: Create friendly notifications and optional follow-up actions when selected CircuitSetup Energy Analyzer alert entities report a possible issue. For Companion App mobile notifications, use data.url and data.clickAction with the evidence_path template variable.
```

Do not force every user to configure a mobile notification service. The existing `alert_actions` input remains the flexible place for phone notifications.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/test_user_facing_text.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add blueprints/automation/circuitsetup_energy_analyzer/energy_alert_notification.yaml tests/test_user_facing_text.py
git commit -m "Expose evidence graph links in alert blueprint"
```

---

### Task 6: Document Notification-To-Graph Usage

**Files:**
- Modify: `README.md`
- Modify: `tests/test_user_facing_text.py`

- [ ] **Step 1: Add failing README test assertions**

In `tests/test_user_facing_text.py`, update `test_readme_includes_practical_usage_guide()` or add a new test:

```python
def test_readme_explains_notification_evidence_graph_links() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme_text.split())

    assert "Open evidence graph" in readme_text
    assert "Alert Evidence" in readme_text
    assert "evidence_path" in readme_text
    assert "graph_entities" in readme_text
    assert "Companion App" in readme_text
    assert "clickAction" in readme_text
    assert "Persistent notifications include a Markdown link" in normalized
```

- [ ] **Step 2: Run the test and confirm red**

Run:

```powershell
pytest tests/test_user_facing_text.py::test_readme_explains_notification_evidence_graph_links -q
```

Expected: fail because README does not explain these links yet.

- [ ] **Step 3: Add README guidance**

In `README.md`, under `### When an alert appears`, add:

```markdown
Persistent notifications include a Markdown link named `Open evidence graph`.
The link opens the Alert Evidence dashboard section with the alert ID, circuit,
and feature in the URL. The related `Alert Evidence` entity also exposes
`evidence_path`, `graph_entities`, `source_entities`, `graph_window_start`, and
`graph_window_end` attributes so dashboard cards, blueprints, and mobile
notifications can point to the same context.

For Companion App mobile notifications, use the alert blueprint and set the
mobile notification `data.url` and Android `data.clickAction` fields to
`{{ evidence_path }}`. This opens the same Home Assistant evidence view when the
phone notification is tapped.
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/test_user_facing_text.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add README.md tests/test_user_facing_text.py
git commit -m "Document alert evidence graph links"
```

---

### Task 7: Final Verification And Optional Live HA Check

**Files:**
- No new files expected.
- Verify all modified files.

- [ ] **Step 1: Run full tests**

Run:

```powershell
pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Check generated entity references and dashboard YAML**

Run:

```powershell
python - <<'PY'
from pathlib import Path
import yaml
yaml.safe_load(Path("docs/dashboard-example.yaml").read_text())
print("dashboard yaml ok")
PY
```

Expected: prints `dashboard yaml ok`.

- [ ] **Step 3: Inspect git diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected: no unstaged changes after the task commits, or only intentional changes if the implementer chooses a single final commit instead of per-task commits.

- [ ] **Step 4: Optional live Home Assistant check**

If the Home Assistant MCP or logged-in Chrome session is available:

1. Install or reload the updated integration.
2. Trigger a demo alert or create a persistent notification using an existing active alert.
3. Confirm the notification body contains `Open evidence graph`.
4. Click the link and confirm Home Assistant opens the CircuitSetup Energy Analyzer dashboard evidence section.
5. Confirm the `sensor.<circuit>_alert_evidence` attributes include `evidence_path`, `graph_entities`, and graph window timestamps.

- [ ] **Step 5: Final commit if needed**

If any final verification-only changes were made:

```powershell
git add README.md docs/dashboard-example.yaml blueprints/automation/circuitsetup_energy_analyzer/energy_alert_notification.yaml custom_components/circuitsetup_energy_analyzer tests
git commit -m "Verify alert evidence graph link feature"
```

---

## Self-Review

- Spec coverage: The plan covers notification click links, graph context, evidence attributes, dashboard cards, blueprint mobile usage, README instructions, and tests.
- Scope check: V1 intentionally uses standard Home Assistant cards and notification links. It does not require a custom Lovelace card, custom panel, or JavaScript frontend.
- Test coverage: Pure helpers, UX attributes, notification message Markdown, coordinator config passing, dashboard YAML, blueprint text, and README guidance all get tests.
- Home Assistant constraints: Standard dashboard cards cannot dynamically filter by URL query parameter. The plan still includes alert ID/circuit/feature in the link for traceability and future frontend expansion, while V1 dashboard cards show evidence context in a static, reliable way.
- Placeholder scan: No implementation step depends on unspecified files or unnamed behavior.
