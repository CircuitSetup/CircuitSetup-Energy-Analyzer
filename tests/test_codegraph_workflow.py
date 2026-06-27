import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_codegraph_is_wired_into_codex_workflow() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    codex_readme = (ROOT / "docs" / "codegraph" / "CODEX_README.md").read_text(
        encoding="utf-8"
    )
    update_script = ROOT / ".codex" / "scripts" / "update-codegraph.ps1"

    assert "## Codegraph" in agents
    assert "docs/codegraph/CODEGRAPH.md" in agents
    assert ".codex/scripts/update-codegraph.ps1" in agents
    assert "docs/codegraph/codegraph.json" not in agents
    assert "docs/codegraph/generated/codegraph.generated.json" not in agents

    assert "docs/codegraph/generate_codegraph.py" in codex_readme
    assert "python generate_codegraph.py" not in codex_readme

    assert update_script.exists()
    update_script_text = update_script.read_text(encoding="utf-8")
    assert "docs\\codegraph\\generate_codegraph.py" in update_script_text
    assert "--output-dir docs/codegraph/generated" in update_script_text

    tracked_generated_files = subprocess.check_output(
        [
            "git",
            "ls-files",
            "docs/codegraph/codegraph.json",
            "docs/codegraph/generated",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    assert tracked_generated_files == []
