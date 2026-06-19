from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_ast_grep_is_wired_into_codex_workflow() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    setup_script = (ROOT / ".codex" / "scripts" / "setup-windows.ps1").read_text(
        encoding="utf-8"
    )

    assert "## Structural Search" in agents
    assert "ast-grep" in agents
    assert "sg run --lang python" in agents
    assert "rg" in agents

    assert "sg --version" in setup_script
    assert "ast-grep" in setup_script


def test_jq_is_wired_into_json_workflow() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    setup_script = (ROOT / ".codex" / "scripts" / "setup-windows.ps1").read_text(
        encoding="utf-8"
    )

    assert "## JSON Workflow" in agents
    assert "jq" in agents
    assert "jq -r" in agents
    assert "--arg" in agents
    assert "python -m json.tool" not in agents

    assert "jq --version" in setup_script
    assert "jqlang.jq" in setup_script
