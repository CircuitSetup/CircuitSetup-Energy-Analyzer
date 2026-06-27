# CircuitSetup Energy Analyzer Codegraph Bundle

This bundle is designed for Codex and other code agents.

## Files

- `CODEGRAPH.md` — curated architecture, runtime flow, module ownership, critical contracts, and change-impact guide.
- `generate_codegraph.py` — dependency-free AST generator for exact imports, definitions, entrypoints, local-call hints, centrality, and import cycles from a local checkout.
- `CODEX_README.md` — concise agent instructions.

## Recommended use

From the repository root:

```bash
python path/to/generate_codegraph.py . --output-dir docs/codegraph/generated
```

The generator includes `tests/` and `tests_homeassistant/` by default. Use `--exclude-tests` only when you need a production-only graph.

Read the curated graph and generated graph together:

- curated graph = runtime intent and ownership;
- generated graph = local exact static structure for the checked-out commit.

Generated graph output is local-only and is not checked in.
