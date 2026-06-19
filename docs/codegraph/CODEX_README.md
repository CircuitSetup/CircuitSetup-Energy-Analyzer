# Codex Instructions for the CircuitSetup Codegraph

1. Read `CODEGRAPH.md`.
2. Confirm the repository checkout contains `f0dee7a` or a newer descendant.
3. Run the installed generator from the repository root:
   ```bash
   python docs/codegraph/generate_codegraph.py . --output-dir docs/codegraph/generated
   ```
4. Before editing a module:
   - inspect its node in `codegraph.json`;
   - inspect inbound and outbound AST imports in the generated JSON;
   - inspect the relevant change-impact section;
   - identify tests in `tests/` and `tests_homeassistant/`.
5. Do not infer a dynamic call is safe merely because the static graph has no edge.
6. Regenerate the graph after structural changes.
7. Include graph changes in the same commit/PR as structural code changes.
