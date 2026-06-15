from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_release_workflow() -> dict[str, object]:
    return yaml.load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        ),
        Loader=yaml.BaseLoader,
    )


def _load_ci_workflow() -> dict[str, object]:
    return yaml.load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def test_ci_workflow_emits_required_home_assistant_contract_check() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]

    required_check_jobs = [
        job_id
        for job_id, job in jobs.items()
        if job.get("name") == "Home Assistant control entity contract"
    ]

    assert required_check_jobs == ["home-assistant-control-entity-contract"]
    required_check = jobs[required_check_jobs[0]]
    assert required_check["needs"] == "home-assistant-contract"


def test_release_workflow_runs_for_version_tags_and_manual_dispatch() -> None:
    workflow = _load_release_workflow()

    assert workflow["on"] == {
        "push": {"tags": ["v*.*.*"]},
        "workflow_dispatch": {
            "inputs": {
                "tag": {
                    "description": "Existing tag to publish, for example v0.7.3",
                    "required": "true",
                    "type": "string",
                }
            }
        }
    }


def test_release_workflow_resolves_dispatch_or_pushed_tag() -> None:
    workflow = _load_release_workflow()
    release_steps = workflow["jobs"]["release"]["steps"]
    checkout_step = next(
        step for step in release_steps if step["name"] == "Check out repository"
    )
    tag_step = next(
        step for step in release_steps if step["name"] == "Resolve release tag"
    )

    assert (
        checkout_step["with"]["ref"]
        == "${{ github.event_name == 'workflow_dispatch' && inputs.tag || github.ref }}"
    )
    assert 'echo "tag=${{ inputs.tag }}" >> "$GITHUB_OUTPUT"' in tag_step["run"]
    assert 'echo "tag=${GITHUB_REF_NAME}" >> "$GITHUB_OUTPUT"' in tag_step["run"]


def test_release_workflow_verifies_release_pr_batch() -> None:
    workflow = _load_release_workflow()
    release_steps = workflow["jobs"]["release"]["steps"]
    checkout_step = next(
        step for step in release_steps if step["name"] == "Check out repository"
    )
    guard_step = next(
        step for step in release_steps if step["name"] == "Verify release PR batch"
    )

    assert checkout_step["with"]["fetch-depth"] == "0"
    assert guard_step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert guard_step["env"]["RELEASE_TAG"] == "${{ steps.tag.outputs.tag }}"
    assert guard_step["env"]["MINIMUM_RELEASE_PRS"] == "2"
    assert "scripts/verify_release_batch.py" in guard_step["run"]
    assert "--tag \"$RELEASE_TAG\"" in guard_step["run"]
    assert "--minimum-prs \"$MINIMUM_RELEASE_PRS\"" in guard_step["run"]


def test_release_workflow_cleans_generated_notes_for_owner_entries() -> None:
    workflow = _load_release_workflow()
    release_steps = workflow["jobs"]["release"]["steps"]
    cleanup_step = next(
        step
        for step in release_steps
        if step["name"] == "Clean generated release notes"
    )

    assert cleanup_step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert cleanup_step["env"]["RELEASE_TAG"] == "${{ steps.tag.outputs.tag }}"
    assert "scripts/clean_release_notes.py" in cleanup_step["run"]
    assert "gh release edit \"$RELEASE_TAG\" --notes-file" in cleanup_step["run"]


def _load_release_batch_module():
    module_path = ROOT / "scripts" / "verify_release_batch.py"
    spec = importlib.util.spec_from_file_location("verify_release_batch", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_batch_guard_counts_distinct_associated_prs() -> None:
    guard = _load_release_batch_module()

    assert guard.distinct_pull_request_numbers(
        [
            [{"number": 66}, {"number": 66}],
            [{"number": 68}, {"number": "not-an-int"}],
            [],
        ]
    ) == {66, 68}


def test_release_batch_guard_requires_more_than_one_pr(capsys) -> None:
    guard = _load_release_batch_module()

    guard.require_minimum_pull_requests({66, 68}, minimum=2)

    with pytest.raises(SystemExit) as excinfo:
        guard.require_minimum_pull_requests({68}, minimum=2)

    assert excinfo.value.code == 1
    assert "at least 2 merged pull requests" in capsys.readouterr().err


def test_release_notes_cleanup_omits_owner_username_only() -> None:
    module_path = ROOT / "scripts" / "clean_release_notes.py"
    spec = importlib.util.spec_from_file_location("clean_release_notes", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    body = "\n".join(
        [
            "## What's Changed",
            "* Reveal Expert entity detail rows safely by @CircuitSetup in #88",
            "* External fix by @friend in #90",
        ]
    )

    assert module.clean_release_notes_body(body) == "\n".join(
        [
            "## What's Changed",
            "* Reveal Expert entity detail rows safely in #88",
            "* External fix by @friend in #90",
        ]
    )
