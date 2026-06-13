from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_release_workflow() -> dict[str, object]:
    return yaml.load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        ),
        Loader=yaml.BaseLoader,
    )


def test_release_workflow_is_manual_only() -> None:
    workflow = _load_release_workflow()

    assert workflow["on"] == {
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


def test_release_workflow_uses_dispatch_tag_only() -> None:
    workflow = _load_release_workflow()
    release_steps = workflow["jobs"]["release"]["steps"]
    checkout_step = next(
        step for step in release_steps if step["name"] == "Check out repository"
    )
    tag_step = next(
        step for step in release_steps if step["name"] == "Resolve release tag"
    )

    assert checkout_step["with"]["ref"] == "${{ inputs.tag }}"
    assert 'echo "tag=${{ inputs.tag }}" >> "$GITHUB_OUTPUT"' in tag_step["run"]
    assert "github.ref" not in tag_step["run"]
    assert "GITHUB_REF_NAME" not in tag_step["run"]
