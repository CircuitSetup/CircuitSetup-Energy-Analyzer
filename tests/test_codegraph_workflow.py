import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_codegraph_is_wired_into_codex_workflow() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "## Codegraph" in agents
    assert "docs/codegraph/CODEGRAPH.md" in agents
    assert "codegraph explore" in agents
    assert "codegraph init" in agents
    assert ".codex/scripts/update-codegraph.ps1" not in agents
    assert "docs/codegraph/codegraph.json" not in agents
    assert "docs/codegraph/generated/codegraph.generated.json" not in agents
    assert not (ROOT / "docs" / "codegraph" / "generate_codegraph.py").exists()
    assert not (ROOT / ".codex" / "scripts" / "update-codegraph.ps1").exists()

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
