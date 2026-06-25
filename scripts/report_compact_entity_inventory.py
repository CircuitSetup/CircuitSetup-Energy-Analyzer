from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEVELOPMENT_DIR = ROOT / "docs" / "development"
BEFORE_REPORT = DEVELOPMENT_DIR / "entity-inventory-before.json"


def main() -> None:
    """Write compact entity inventory and before/after count reports."""
    report = _build_after_report()
    report["git_head"] = _git_head()
    report["integration_version"] = _integration_version()

    DEVELOPMENT_DIR.mkdir(parents=True, exist_ok=True)
    (DEVELOPMENT_DIR / "entity-inventory-after.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (DEVELOPMENT_DIR / "entity-inventory-after.md").write_text(
        _inventory_markdown(report),
        encoding="utf-8",
    )
    (DEVELOPMENT_DIR / "entity-count-comparison.md").write_text(
        _comparison_markdown(report, _load_before_report()),
        encoding="utf-8",
    )


def _build_after_report() -> dict[str, Any]:
    from custom_components.circuitsetup_energy_analyzer.const import (
        CONF_ENTITY_DETAIL_LEVEL,
        CONF_SELECTED_ENTITY_GROUPS,
        ENTITY_DETAIL_EXPERT,
        ENTITY_DETAIL_SIMPLE,
        ENTITY_DETAIL_STANDARD,
    )
    from custom_components.circuitsetup_energy_analyzer.entity_catalog import (
        EntityGroup,
        desired_compact_entity_rules,
    )
    from scripts import entity_inventory

    scenarios = entity_inventory._scenario_definitions()
    detail_cases = (
        ("simple", ENTITY_DETAIL_SIMPLE, ()),
        ("standard", ENTITY_DETAIL_STANDARD, ()),
        ("expert_no_groups", ENTITY_DETAIL_EXPERT, ()),
        (
            "expert_all_groups",
            ENTITY_DETAIL_EXPERT,
            tuple(
                group.value
                for group in EntityGroup
                if group is not EntityGroup.CORE
            ),
        ),
    )
    scenario_reports = []
    for scenario in scenarios:
        variants: dict[str, Any] = {}
        for variant in entity_inventory.CONFIGURATION_VARIANTS:
            circuit = entity_inventory._circuit_for_variant(scenario, variant)
            configured_circuits = tuple(
                entity_inventory._circuit_for_variant(item, variant)
                for item in scenarios
            )
            coordinator = entity_inventory._coordinator_for(
                circuit,
                configured_circuits,
                variant,
            )
            current_row_list = list(
                entity_inventory._entity_rows_for_circuit(
                    circuit,
                    coordinator,
                    configured_circuits,
                )
            )
            current_row_list.extend(_switch_rows_for_circuit(circuit, coordinator))
            current_rows = {
                (row["domain"], row["key"]): row
                for row in current_row_list
                if row["created"]
            }
            detail_levels: dict[str, Any] = {}
            for case_name, detail_level, selected_groups in detail_cases:
                coordinator.options[CONF_ENTITY_DETAIL_LEVEL] = detail_level
                if selected_groups:
                    coordinator.options[CONF_SELECTED_ENTITY_GROUPS] = list(
                        selected_groups,
                    )
                else:
                    coordinator.options.pop(CONF_SELECTED_ENTITY_GROUPS, None)
                rules = desired_compact_entity_rules(
                    current_entities=set(current_rows),
                    circuit=circuit,
                    coordinator=coordinator,
                    detail_level=detail_level,
                    selected_groups=selected_groups,
                    legacy_compatibility_keys=(),
                )
                rows = [
                    current_rows[(rule.domain, rule.key)]
                    for rule in rules
                    if (rule.domain, rule.key) in current_rows
                ]
                detail_levels[case_name] = {
                    "detail_level": detail_level,
                    "selected_groups": list(selected_groups),
                    "created": _bucket(rows),
                }
            variants[variant] = {
                "circuit_id": circuit.circuit_id,
                "configuration": variant,
                "source_roles": [
                    sensor_ref.role.value for sensor_ref in circuit.sensors
                ],
                "detail_levels": detail_levels,
            }
        default_variant = variants["all_applicable_optional_settings"]
        scenario_reports.append(
            {
                "scenario_id": scenario.scenario_id,
                "appliance_profile": scenario.profile.value,
                "mode": scenario.mode.value,
                "variants": variants,
                "detail_levels": default_variant["detail_levels"],
            }
        )
    return {
        "report": "entity-inventory-after",
        "scope": "per-circuit compact entities only",
        "configuration_variants": list(entity_inventory.CONFIGURATION_VARIANTS),
        "detail_cases": [case[0] for case in detail_cases],
        "scenarios": scenario_reports,
    }


def _switch_rows_for_circuit(circuit: Any, coordinator: Any) -> list[dict[str, Any]]:
    from custom_components.circuitsetup_energy_analyzer import switch

    return [
        {
            "domain": "switch",
            "key": description.key,
            "name": f"{circuit.name} {description.name_suffix}",
            "entity_id": f"switch.{circuit.circuit_id}_{description.key}",
            "unique_id": f"{{entry_id}}_{circuit.circuit_id}_{description.key}",
            "tier": None,
            "enabled_default": description.entity_registry_enabled_default,
            "visible_default": description.entity_registry_visible_default,
            "control": True,
            "created": switch.switch_description_applies(
                description,
                circuit,
                coordinator,
            ),
        }
        for description in switch.CIRCUIT_SWITCH_DESCRIPTIONS
    ]


def _bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    domains = ("sensor", "binary_sensor", "button", "select", "number", "switch")
    counts = dict.fromkeys(domains, 0)
    for row in rows:
        counts[row["domain"]] = counts.get(row["domain"], 0) + 1
    return {
        **counts,
        "total": len(rows),
        "entity_ids": [row["entity_id"] for row in rows],
        "keys": [f"{row['domain']}:{row['key']}" for row in rows],
    }


def _inventory_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Entity Inventory After Compact Model",
        "",
        "This report is generated by "
        "`python scripts/report_compact_entity_inventory.py`.",
        "Counts are per-circuit compact entity rows and exclude integration-wide "
        "setup health, dashboard layout, entity detail, and global action controls.",
        "",
        "## Scenario Counts",
        "",
    ]
    for scenario in report["scenarios"]:
        lines.append(f"### {scenario['scenario_id']}")
        lines.append("")
        for variant, variant_report in scenario["variants"].items():
            lines.append(f"#### {variant}")
            lines.append("")
            lines.append(
                "| Detail case | Created | Sensor | Binary sensor | Button | Select | "
                "Number | Switch |"
            )
            lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
            for case_name, detail_report in variant_report["detail_levels"].items():
                created = detail_report["created"]
                lines.append(
                    f"| {case_name} | {created['total']} | "
                    f"{created['sensor']} | {created['binary_sensor']} | "
                    f"{created['button']} | {created['select']} | "
                    f"{created['number']} | {created['switch']} |"
                )
            lines.append("")
    return "\n".join(lines) + "\n"


def _comparison_markdown(
    after_report: dict[str, Any],
    before_report: dict[str, Any] | None,
) -> str:
    lines = [
        "# Entity Count Comparison",
        "",
        "This report compares the pre-compact entity inventory with compact "
        "creation rules for the `all_applicable_optional_settings` scenario "
        "variant.",
        "",
        "| Scenario | Before created | Simple | Standard | Expert, no groups | "
        "Expert, all groups |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    before_by_id = {
        scenario["scenario_id"]: scenario
        for scenario in (before_report or {}).get("scenarios", [])
    }
    simple_max = 0
    standard_max = 0
    expert_no_groups_max = 0
    expert_all_groups_max = 0
    for scenario in after_report["scenarios"]:
        detail_levels = scenario["detail_levels"]
        before_total = _before_created_total(before_by_id.get(scenario["scenario_id"]))
        simple_total = detail_levels["simple"]["created"]["total"]
        standard_total = detail_levels["standard"]["created"]["total"]
        expert_no_groups_total = detail_levels["expert_no_groups"]["created"]["total"]
        expert_all_groups_total = detail_levels["expert_all_groups"]["created"]["total"]
        simple_max = max(simple_max, simple_total)
        standard_max = max(standard_max, standard_total)
        expert_no_groups_max = max(expert_no_groups_max, expert_no_groups_total)
        expert_all_groups_max = max(expert_all_groups_max, expert_all_groups_total)
        lines.append(
            f"| {scenario['scenario_id']} | {before_total} | {simple_total} | "
            f"{standard_total} | {expert_no_groups_total} | "
            f"{expert_all_groups_total} |"
        )
    lines.extend(
        [
            "",
            "## Acceptance Summary",
            "",
            f"- Simple maximum: {simple_max} per-circuit entities.",
            f"- Standard maximum: {standard_max} per-circuit entities.",
            "- Expert without selected groups stays at "
            f"{expert_no_groups_max} per-circuit entities and does not recreate "
            "the full historical diagnostic surface.",
            "- Expert with every group selected stays at "
            f"{expert_all_groups_max} per-circuit entities.",
            "- The compact model keeps `select.<circuit>_alert_sensitivity` as "
            "the canonical sensitivity control and replaces legacy maintenance "
            "buttons with `switch.<circuit>_maintenance`.",
        ]
    )
    return "\n".join(lines) + "\n"


def _before_created_total(scenario: dict[str, Any] | None) -> int | str:
    if not scenario:
        return "missing"
    return scenario["detail_levels"]["simple"]["created"]["total"]


def _load_before_report() -> dict[str, Any] | None:
    if not BEFORE_REPORT.exists():
        return None
    return json.loads(BEFORE_REPORT.read_text(encoding="utf-8"))


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _integration_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "unknown"


if __name__ == "__main__":
    main()
