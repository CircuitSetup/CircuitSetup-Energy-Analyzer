#!/usr/bin/env python3
"""Generate a Codex-readable static codegraph without importing project code.

The graph is intentionally conservative:
- Python import and definition edges are AST-derived.
- Local call edges are best effort.
- Home Assistant callbacks, dynamic dispatch, registries, and string-based services
  cannot be resolved completely by static analysis.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
}
SUPPORTED_SUFFIXES = {".py", ".js", ".json", ".yaml", ".yml"}
HA_ENTRYPOINT_NAMES = {
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
    "async_migrate_entry",
    "async_get_config_entry_diagnostics",
    "async_setup_services",
    "async_unload_services",
    "async_setup_panel",
    "async_unload_panel",
}
PLATFORM_MODULE_NAMES = {"sensor", "binary_sensor", "button", "select", "number"}


def write_lf_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


@dataclass(slots=True)
class Symbol:
    id: str
    module: str
    name: str
    qualified_name: str
    kind: str
    path: str
    lineno: int
    end_lineno: int
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    doc: str = ""
    calls: list[str] = field(default_factory=list)
    entrypoint_reason: str | None = None


@dataclass(slots=True)
class ModuleRecord:
    id: str
    path: str
    language: str
    kind: str
    loc: int
    doc: str = ""
    imports: list[dict[str, Any]] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    parse_error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=".",
        help="Repository root (default: current directory).",
    )
    parser.add_argument(
        "--source-root",
        default="custom_components/circuitsetup_energy_analyzer",
        help="Primary integration source root.",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/codegraph/generated",
        help="Output directory relative to the repository root.",
    )
    parser.add_argument(
        "--exclude-tests",
        action="store_true",
        help="Exclude tests/ and tests_homeassistant/ from the generated graph.",
    )
    parser.add_argument(
        "--max-mermaid-nodes",
        type=int,
        default=55,
        help="Maximum module nodes in the rendered Mermaid import graph.",
    )
    return parser.parse_args()


def git_output(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def path_is_excluded(path: Path, repo_root: Path, *, include_tests: bool) -> bool:
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    if any(part in EXCLUDED_DIR_NAMES for part in rel.parts):
        return True
    if not include_tests and rel.parts and rel.parts[0] in {"tests", "tests_homeassistant"}:
        return True
    return False


def iter_source_files(
    repo_root: Path,
    source_root: Path,
    *,
    include_tests: bool,
) -> list[Path]:
    roots = [source_root]
    if include_tests:
        roots.extend([repo_root / "tests", repo_root / "tests_homeassistant"])
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path_is_excluded(path, repo_root, include_tests=include_tests):
                continue
            if path.suffix.lower() in SUPPORTED_SUFFIXES:
                files.append(path)
    return sorted(set(files))


def module_name_for_path(path: Path, repo_root: Path) -> str:
    rel = path.relative_to(repo_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def first_doc_line(value: str | None) -> str:
    if not value:
        return ""
    for line in value.strip().splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def dotted_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    if isinstance(node, ast.Subscript):
        return dotted_name(node.value)
    if isinstance(node, ast.Constant):
        return repr(node.value)
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return node.__class__.__name__


def decorators_for(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    return [dotted_name(item) for item in node.decorator_list]


def call_names(node: ast.AST) -> list[str]:
    calls: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = dotted_name(child.func)
            if name:
                calls.add(name)
    return sorted(calls)


def entrypoint_reason(
    module_name: str,
    symbol_name: str,
    kind: str,
    bases: Iterable[str],
) -> str | None:
    base_names = set(bases)
    if symbol_name in HA_ENTRYPOINT_NAMES:
        return "Home Assistant lifecycle/API entrypoint"
    if module_name.rsplit(".", 1)[-1] in PLATFORM_MODULE_NAMES and symbol_name == "async_setup_entry":
        return "Home Assistant entity-platform setup"
    if symbol_name.endswith("ConfigFlow") or "ConfigFlow" in base_names:
        return "Home Assistant config flow"
    if symbol_name.endswith("OptionsFlow") or "OptionsFlow" in base_names:
        return "Home Assistant options flow"
    if symbol_name.endswith("Processor") and kind == "class":
        return "Feature processor"
    if symbol_name.endswith("View") and kind == "class":
        return "HTTP/API view"
    if symbol_name.endswith("Entity") and kind == "class":
        return "Home Assistant entity"
    return None


def parse_python(
    path: Path,
    repo_root: Path,
) -> tuple[ModuleRecord, list[Symbol], list[tuple[str, str]]]:
    rel = path.relative_to(repo_root).as_posix()
    module_name = module_name_for_path(path, repo_root)
    text = path.read_text(encoding="utf-8")
    loc = len(text.splitlines())
    record = ModuleRecord(
        id=module_name,
        path=rel,
        language="python",
        kind="python_module",
        loc=loc,
    )
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:
        record.parse_error = f"{exc.msg} at {exc.lineno}:{exc.offset}"
        return record, [], []

    record.doc = first_doc_line(ast.get_docstring(tree))
    symbols: list[Symbol] = []
    local_call_candidates: list[tuple[str, str]] = []

    for child in tree.body:
        if isinstance(child, ast.Import):
            for alias in child.names:
                record.imports.append(
                    {
                        "raw": alias.name,
                        "module": alias.name,
                        "name": alias.asname or alias.name,
                        "level": 0,
                        "kind": "import",
                        "lineno": child.lineno,
                    }
                )
        elif isinstance(child, ast.ImportFrom):
            record.imports.append(
                {
                    "raw": (
                        f"{'.' * child.level}{child.module or ''}:"
                        + ",".join(alias.name for alias in child.names)
                    ),
                    "module": child.module or "",
                    "names": [
                        {"name": alias.name, "asname": alias.asname}
                        for alias in child.names
                    ],
                    "level": child.level,
                    "kind": "from",
                    "lineno": child.lineno,
                }
            )

        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async_function" if isinstance(child, ast.AsyncFunctionDef) else "function"
            qname = f"{module_name}.{child.name}"
            symbol = Symbol(
                id=qname,
                module=module_name,
                name=child.name,
                qualified_name=qname,
                kind=kind,
                path=rel,
                lineno=child.lineno,
                end_lineno=getattr(child, "end_lineno", child.lineno),
                decorators=decorators_for(child),
                doc=first_doc_line(ast.get_docstring(child)),
                calls=call_names(child),
                entrypoint_reason=entrypoint_reason(
                    module_name,
                    child.name,
                    kind,
                    (),
                ),
            )
            symbols.append(symbol)
            for call in symbol.calls:
                local_call_candidates.append((symbol.id, call))

        elif isinstance(child, ast.ClassDef):
            bases = [dotted_name(base) for base in child.bases]
            qname = f"{module_name}.{child.name}"
            class_symbol = Symbol(
                id=qname,
                module=module_name,
                name=child.name,
                qualified_name=qname,
                kind="class",
                path=rel,
                lineno=child.lineno,
                end_lineno=getattr(child, "end_lineno", child.lineno),
                decorators=decorators_for(child),
                bases=bases,
                doc=first_doc_line(ast.get_docstring(child)),
                calls=[],
                entrypoint_reason=entrypoint_reason(
                    module_name,
                    child.name,
                    "class",
                    bases,
                ),
            )
            symbols.append(class_symbol)
            for item in child.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                kind = "async_method" if isinstance(item, ast.AsyncFunctionDef) else "method"
                method_qname = f"{qname}.{item.name}"
                method = Symbol(
                    id=method_qname,
                    module=module_name,
                    name=item.name,
                    qualified_name=method_qname,
                    kind=kind,
                    path=rel,
                    lineno=item.lineno,
                    end_lineno=getattr(item, "end_lineno", item.lineno),
                    decorators=decorators_for(item),
                    doc=first_doc_line(ast.get_docstring(item)),
                    calls=call_names(item),
                    entrypoint_reason=None,
                )
                symbols.append(method)
                for call in method.calls:
                    local_call_candidates.append((method.id, call))

    record.symbols = [item.id for item in symbols]
    return record, symbols, local_call_candidates


def parse_javascript(path: Path, repo_root: Path) -> ModuleRecord:
    rel = path.relative_to(repo_root).as_posix()
    text = path.read_text(encoding="utf-8")
    metadata: dict[str, Any] = {}
    metadata["api_paths"] = sorted(
        set(re.findall(r"""["'`](/api/[^"'`?\s]+)""", text))
    )
    metadata["service_calls"] = sorted(
        set(
            ".".join(match)
            for match in re.findall(
                r"""callService\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']""",
                text,
            )
        )
    )
    metadata["custom_elements"] = sorted(
        set(
            re.findall(
                r"""customElements\.define\(\s*["']([^"']+)["']""",
                text,
            )
        )
    )
    metadata["imports"] = sorted(
        set(
            re.findall(
                r"""(?:import\s+.*?\s+from\s+|import\s*)["']([^"']+)["']""",
                text,
            )
        )
    )
    return ModuleRecord(
        id=rel,
        path=rel,
        language="javascript",
        kind="javascript_module",
        loc=len(text.splitlines()),
        metadata=metadata,
    )


def parse_resource(path: Path, repo_root: Path) -> ModuleRecord:
    rel = path.relative_to(repo_root).as_posix()
    text = path.read_text(encoding="utf-8")
    metadata: dict[str, Any] = {}
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
            if path.name == "manifest.json":
                metadata = {
                    key: data.get(key)
                    for key in (
                        "domain",
                        "name",
                        "version",
                        "dependencies",
                        "after_dependencies",
                        "config_flow",
                        "iot_class",
                    )
                }
            else:
                metadata["top_level_keys"] = sorted(data) if isinstance(data, dict) else []
        except json.JSONDecodeError as exc:
            metadata["parse_error"] = str(exc)
    elif path.name == "services.yaml":
        metadata["service_names"] = re.findall(
            r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*$",
            text,
            flags=re.MULTILINE,
        )
    return ModuleRecord(
        id=rel,
        path=rel,
        language=path.suffix.lower().lstrip("."),
        kind="resource",
        loc=len(text.splitlines()),
        metadata=metadata,
    )


def resolve_relative_import(
    current_module: str,
    current_path: Path,
    import_record: dict[str, Any],
) -> list[str]:
    level = int(import_record.get("level", 0))
    raw_module = str(import_record.get("module", ""))
    if level == 0:
        return [raw_module] if raw_module else []

    package = current_module if current_path.name == "__init__.py" else current_module.rpartition(".")[0]
    relative = "." * level + raw_module
    try:
        base = importlib.util.resolve_name(relative, package)
    except (ImportError, ValueError):
        return []

    targets = [base] if raw_module else []
    if not raw_module:
        for item in import_record.get("names", []):
            name = item.get("name")
            if name and name != "*":
                targets.append(f"{base}.{name}")
    return targets or [base]


def best_internal_target(name: str, internal_modules: set[str]) -> str | None:
    if name in internal_modules:
        return name
    parts = name.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in internal_modules:
            return candidate
        parts.pop()
    return None


def classify_external(module_name: str) -> str:
    top = module_name.split(".", 1)[0]
    if top == "homeassistant":
        return "external:homeassistant"
    if top in sys.stdlib_module_names:
        return f"external:stdlib:{top}"
    return f"external:third_party:{top}"


def tarjan_scc(nodes: set[str], adjacency: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in adjacency.get(node, set()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])

        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            components.append(sorted(component))

    for node in sorted(nodes):
        if node not in indices:
            strongconnect(node)
    return components


def mermaid_id(value: str) -> str:
    return "n_" + re.sub(r"[^a-zA-Z0-9_]", "_", value)


def render_mermaid(
    modules: list[ModuleRecord],
    edges: list[dict[str, Any]],
    max_nodes: int,
) -> str:
    import_edges = [edge for edge in edges if edge["relation"] == "imports" and edge.get("internal")]
    indegree = Counter(edge["target"] for edge in import_edges)
    outdegree = Counter(edge["source"] for edge in import_edges)
    score = Counter()
    for module in modules:
        score[module.id] = indegree[module.id] + outdegree[module.id]
    selected = {
        item
        for item, _ in score.most_common(max_nodes)
        if score[item] > 0
    }
    if not selected:
        selected = {module.id for module in modules[:max_nodes]}

    lines = ["flowchart LR"]
    by_id = {module.id: module for module in modules}
    for node in sorted(selected):
        label = Path(by_id[node].path).name if node in by_id else node
        lines.append(f'  {mermaid_id(node)}["{label}"]')
    rendered: set[tuple[str, str]] = set()
    for edge in import_edges:
        source = edge["source"]
        target = edge["target"]
        if source not in selected or target not in selected:
            continue
        key = (source, target)
        if key in rendered:
            continue
        rendered.add(key)
        lines.append(f"  {mermaid_id(source)} --> {mermaid_id(target)}")
    return "\n".join(lines) + "\n"


def generate(repo_root: Path, source_root: Path, output_dir: Path, *, include_tests: bool, max_mermaid_nodes: int) -> None:
    files = iter_source_files(repo_root, source_root, include_tests=include_tests)
    modules: list[ModuleRecord] = []
    symbols: list[Symbol] = []
    local_call_candidates: list[tuple[str, str]] = []

    for path in files:
        if path.suffix.lower() == ".py":
            module, found_symbols, calls = parse_python(path, repo_root)
            modules.append(module)
            symbols.extend(found_symbols)
            local_call_candidates.extend(calls)
        elif path.suffix.lower() == ".js":
            modules.append(parse_javascript(path, repo_root))
        else:
            modules.append(parse_resource(path, repo_root))

    python_modules = {module.id for module in modules if module.language == "python"}
    path_by_module = {
        module.id: repo_root / module.path
        for module in modules
        if module.language == "python"
    }

    edges: list[dict[str, Any]] = []
    external_nodes: dict[str, dict[str, Any]] = {}
    import_adjacency: dict[str, set[str]] = defaultdict(set)
    indegree: Counter[str] = Counter()
    outdegree: Counter[str] = Counter()

    for module in modules:
        if module.language != "python":
            continue
        current_path = path_by_module[module.id]
        for item in module.imports:
            candidates = resolve_relative_import(module.id, current_path, item)
            if not candidates and item.get("level", 0) == 0:
                candidates = [str(item.get("module", ""))]
            for candidate in candidates:
                if not candidate:
                    continue
                target = best_internal_target(candidate, python_modules)
                if target:
                    edge = {
                        "source": module.id,
                        "target": target,
                        "relation": "imports",
                        "internal": True,
                        "lineno": item.get("lineno"),
                        "raw": item.get("raw"),
                    }
                    edges.append(edge)
                    import_adjacency[module.id].add(target)
                    indegree[target] += 1
                    outdegree[module.id] += 1
                else:
                    external_id = classify_external(candidate)
                    external_nodes.setdefault(
                        external_id,
                        {
                            "id": external_id,
                            "kind": "external_dependency",
                            "label": external_id.split(":", 2)[-1],
                        },
                    )
                    edges.append(
                        {
                            "source": module.id,
                            "target": external_id,
                            "relation": "imports",
                            "internal": False,
                            "lineno": item.get("lineno"),
                            "raw": item.get("raw"),
                        }
                    )

    # Best-effort local call edges.
    symbols_by_module_and_name: dict[tuple[str, str], str] = {}
    for symbol in symbols:
        if symbol.kind in {"function", "async_function"}:
            symbols_by_module_and_name[(symbol.module, symbol.name)] = symbol.id
    for source_symbol, call in local_call_candidates:
        module_name = source_symbol.rsplit(".", 1)[0]
        bare = call.split(".", 1)[0]
        target = symbols_by_module_and_name.get((module_name, bare))
        if target and target != source_symbol:
            edges.append(
                {
                    "source": source_symbol,
                    "target": target,
                    "relation": "calls_local",
                    "internal": True,
                    "confidence": "best_effort",
                }
            )

    graph_nodes: list[dict[str, Any]] = [
        {
            "id": module.id,
            "kind": module.kind,
            "path": module.path,
            "language": module.language,
            "loc": module.loc,
            "doc": module.doc,
            "metadata": module.metadata,
            "parse_error": module.parse_error,
            "symbols": module.symbols,
            "centrality": {
                "internal_import_indegree": indegree[module.id],
                "internal_import_outdegree": outdegree[module.id],
            },
        }
        for module in modules
    ]
    graph_nodes.extend(external_nodes.values())

    for symbol in symbols:
        edges.append(
            {
                "source": symbol.module,
                "target": symbol.id,
                "relation": "defines",
                "internal": True,
            }
        )

    components = tarjan_scc(python_modules, import_adjacency)
    cycles = [
        component
        for component in components
        if len(component) > 1
        or (
            len(component) == 1
            and component[0] in import_adjacency.get(component[0], set())
        )
    ]

    commit = git_output(repo_root, "rev-parse", "HEAD")
    branch = git_output(repo_root, "branch", "--show-current")
    status = git_output(repo_root, "status", "--porcelain")
    generated_at = datetime.now(timezone.utc).isoformat()

    graph = {
        "schema_version": "1.0",
        "graph_type": "ast_static_codegraph",
        "repository": {
            "root": str(repo_root),
            "commit": commit,
            "branch": branch,
            "dirty": bool(status),
            "generated_at": generated_at,
        },
        "scope": {
            "source_root": source_root.relative_to(repo_root).as_posix(),
            "tests_included": include_tests,
            "file_count": len(files),
            "python_module_count": len(python_modules),
            "symbol_count": len(symbols),
        },
        "limitations": [
            "Does not import or execute project code.",
            "Dynamic Home Assistant callback/service/entity registration is not fully resolvable.",
            "Local call edges are best effort and intentionally incomplete.",
            "String-based state paths, service names and frontend/backend bindings require semantic review.",
        ],
        "nodes": graph_nodes,
        "symbols": [asdict(symbol) for symbol in symbols],
        "edges": edges,
        "import_cycles": cycles,
        "entrypoints": [
            asdict(symbol)
            for symbol in symbols
            if symbol.entrypoint_reason is not None
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_lf_text(
        output_dir / "codegraph.generated.json",
        json.dumps(graph, indent=2, sort_keys=False),
    )
    write_lf_text(
        output_dir / "symbol_index.generated.json",
        json.dumps([asdict(symbol) for symbol in symbols], indent=2),
    )

    mermaid = render_mermaid(modules, edges, max_mermaid_nodes)
    write_lf_text(output_dir / "import_graph.generated.mmd", mermaid)

    central_modules = sorted(
        (
            (
                indegree[module.id] + outdegree[module.id],
                indegree[module.id],
                outdegree[module.id],
                module,
            )
            for module in modules
            if module.language == "python"
        ),
        reverse=True,
        key=lambda item: (item[0], item[1], item[3].id),
    )[:25]

    entrypoint_rows = "\n".join(
        f"| `{symbol.qualified_name}` | `{symbol.path}:{symbol.lineno}` | {symbol.entrypoint_reason} |"
        for symbol in symbols
        if symbol.entrypoint_reason
    ) or "| _None detected_ | | |"

    central_rows = "\n".join(
        f"| `{module.id}` | {total} | {incoming} | {outgoing} | `{module.path}` |"
        for total, incoming, outgoing, module in central_modules
    )

    cycle_text = (
        "\n".join(
            f"{index}. " + " -> ".join(f"`{item}`" for item in component)
            for index, component in enumerate(cycles, start=1)
        )
        if cycles
        else "No internal Python import cycles detected."
    )

    parse_errors = [module for module in modules if module.parse_error]
    parse_error_text = (
        "\n".join(f"- `{module.path}`: {module.parse_error}" for module in parse_errors)
        if parse_errors
        else "None."
    )

    markdown = f"""# Generated Codegraph

**Commit:** `{commit or 'unknown'}`
**Branch:** `{branch or 'unknown'}`
**Generated:** `{generated_at}`
**Tests included:** `{include_tests}`

## Scope

- Files: **{len(files)}**
- Python modules: **{len(python_modules)}**
- Symbols: **{len(symbols)}**
- Internal import edges: **{sum(1 for edge in edges if edge['relation'] == 'imports' and edge.get('internal'))}**
- External import edges: **{sum(1 for edge in edges if edge['relation'] == 'imports' and not edge.get('internal'))}**

## Entrypoints

| Symbol | Location | Reason |
|---|---|---|
{entrypoint_rows}

## Most connected internal modules

| Module | Total degree | Incoming imports | Outgoing imports | Path |
|---|---:|---:|---:|---|
{central_rows}

## Import cycles

{cycle_text}

## Parse errors

{parse_error_text}

## Import graph

```mermaid
{mermaid.strip()}
```

## Codex usage

- Query `codegraph.generated.json` for exact AST-derived import edges.
- Query `symbol_index.generated.json` for definitions and line ranges.
- Treat `calls_local` as best effort only.
- Read the curated `CODEGRAPH.md` for semantic/runtime relationships.
- Re-run this generator after structural changes.
"""
    write_lf_text(output_dir / "CODEGRAPH.generated.md", markdown)

    print(f"Wrote codegraph to {output_dir}")
    print(
        f"{len(files)} files, {len(python_modules)} Python modules, "
        f"{len(symbols)} symbols, {len(cycles)} import cycles"
    )


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    source_root = (repo_root / args.source_root).resolve()
    output_dir = (repo_root / args.output_dir).resolve()

    if not repo_root.exists():
        print(f"Repository root does not exist: {repo_root}", file=sys.stderr)
        return 2
    if not source_root.exists():
        print(f"Source root does not exist: {source_root}", file=sys.stderr)
        return 2

    generate(
        repo_root,
        source_root,
        output_dir,
        include_tests=not args.exclude_tests,
        max_mermaid_nodes=max(1, args.max_mermaid_nodes),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
