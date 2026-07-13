"""Contract checks for the browser E2E and accessibility gate."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_browser_projects_cover_static_and_home_assistant_runs() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["test:e2e"] == "playwright test"
    assert "@playwright/test" in package["devDependencies"]
    assert "@axe-core/playwright" in package["devDependencies"]

    config = (ROOT / "playwright.config.js").read_text(encoding="utf-8")
    assert "Desktop Chromium" in config
    assert "Mobile Chromium" in config
    assert "Home Assistant Chromium" in config
    assert "reuseExistingServer: false" in config
    assert "retain-on-failure" in config
    assert "only-on-failure" in config


def test_ci_runs_browser_gate_and_uploads_failure_artifacts() -> None:
    workflow_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]
    browser_job = jobs["browser-e2e"]

    assert browser_job["name"] == "Browser E2E and accessibility"
    steps = browser_job["steps"]
    commands = "\n".join(str(step.get("run", "")) for step in steps)
    assert "npm ci" in commands
    assert "playwright install --with-deps chromium" in commands
    assert "npm run test:e2e" in commands
    assert "pytest tests_homeassistant/test_browser_e2e.py -q" in commands
    assert any(
        step.get("uses", "").startswith("actions/upload-artifact@")
        and step.get("if") == "failure()"
        for step in steps
    )
